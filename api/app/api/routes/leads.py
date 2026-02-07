import re
import time
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory token cache
_token_cache: dict = {"access_token": None, "expires_at": 0}

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class LeadRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    region: str = ""
    message: str = ""

    @field_validator("first_name", "last_name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v

    @field_validator("region", "message")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


# ---------- Zoho helpers ----------

async def _get_zoho_access_token() -> str | None:
    """Get a valid access token, refreshing if needed. Returns None if Zoho is not configured."""
    settings = get_settings()
    if not settings.zoho_client_id or not settings.zoho_refresh_token:
        return None

    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://accounts.zoho.com/oauth/v2/token",
            params={
                "refresh_token": settings.zoho_refresh_token,
                "client_id": settings.zoho_client_id,
                "client_secret": settings.zoho_client_secret,
                "grant_type": "refresh_token",
            },
        )
        data = resp.json()

    if "access_token" not in data:
        logger.error("Zoho token refresh failed: %s", data)
        return None

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return data["access_token"]


async def _push_to_zoho(lead: LeadRequest) -> tuple[bool, str | None, str | None]:
    """Push a lead to Zoho CRM. Returns (success, zoho_lead_id, error_message)."""
    token = await _get_zoho_access_token()
    if token is None:
        return False, None, "Zoho CRM not configured"

    settings = get_settings()
    payload = {
        "data": [
            {
                "First_Name": lead.first_name,
                "Last_Name": lead.last_name,
                "Email": lead.email,
                "City": lead.region,
                "Description": lead.message,
                "Lead_Source": "Website",
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.zoho_api_domain}/crm/v2/Leads",
                json=payload,
                headers={"Authorization": f"Zoho-oauthtoken {token}"},
            )
            data = resp.json()

        record = data.get("data", [{}])[0]
        if record.get("status") == "success":
            zoho_id = record.get("details", {}).get("id")
            return True, zoho_id, None
        else:
            err = record.get("message", str(data))
            logger.error("Zoho lead creation failed: %s", err)
            return False, None, err
    except Exception as exc:
        logger.error("Zoho API error: %s", exc)
        return False, None, str(exc)


# ---------- Endpoint ----------

LEADS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    region VARCHAR(100),
    message TEXT,
    zoho_synced BOOLEAN DEFAULT FALSE,
    zoho_lead_id VARCHAR(100),
    zoho_error TEXT,
    created_at TIMESTAMP DEFAULT NOW()
)
"""


def _ensure_table(db: Session):
    db.execute(text(LEADS_TABLE_DDL))
    db.commit()


@router.post("")
async def create_lead(lead: LeadRequest, db: Session = Depends(get_db)):
    _ensure_table(db)

    # Insert into local DB
    result = db.execute(
        text("""
            INSERT INTO leads (first_name, last_name, email, region, message)
            VALUES (:first_name, :last_name, :email, :region, :message)
            RETURNING id
        """),
        {
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "email": lead.email,
            "region": lead.region,
            "message": lead.message,
        },
    )
    db.commit()
    lead_id = result.scalar()

    # Push to Zoho CRM
    synced, zoho_lead_id, zoho_error = await _push_to_zoho(lead)

    db.execute(
        text("""
            UPDATE leads
            SET zoho_synced = :synced, zoho_lead_id = :zoho_lead_id, zoho_error = :zoho_error
            WHERE id = :id
        """),
        {
            "synced": synced,
            "zoho_lead_id": zoho_lead_id,
            "zoho_error": zoho_error,
            "id": lead_id,
        },
    )
    db.commit()

    return {"id": lead_id, "message": "Thank you! We'll be in touch shortly."}
