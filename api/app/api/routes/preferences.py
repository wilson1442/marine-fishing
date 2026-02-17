"""User preferences API — persist per-user settings (favorite species, home port, map defaults, etc.)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_access

router = APIRouter()


class PreferencesBody(BaseModel):
    preferences: dict


def _ensure_preferences_table(db: Session):
    """Create the user_preferences table if it doesn't exist."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES registered_users(id) ON DELETE CASCADE,
            preferences JSONB NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT NOW(),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id)
    """))
    db.commit()


def _get_user_id(auth: dict) -> int:
    """Extract user_id from auth dict, raising 401 if not a logged-in user."""
    user_id = auth.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")
    return user_id


@router.get("")
def get_preferences(
    db: Session = Depends(get_db),
    auth: dict = Depends(require_api_access),
):
    """Return the current user's preferences (or {} if none set)."""
    user_id = _get_user_id(auth)
    _ensure_preferences_table(db)

    row = db.execute(
        text("SELECT preferences FROM user_preferences WHERE user_id = :uid"),
        {"uid": user_id},
    ).fetchone()

    return {"preferences": row.preferences if row else {}}


@router.put("")
def update_preferences(
    body: PreferencesBody,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_api_access),
):
    """Merge provided keys into the user's preferences (partial update)."""
    user_id = _get_user_id(auth)
    _ensure_preferences_table(db)

    row = db.execute(
        text("""
            INSERT INTO user_preferences (user_id, preferences, updated_at)
            VALUES (:uid, :prefs, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET preferences = user_preferences.preferences || :prefs,
                    updated_at = NOW()
            RETURNING preferences
        """),
        {"uid": user_id, "prefs": body.preferences},
    ).fetchone()
    db.commit()

    return {"preferences": row.preferences if row else body.preferences}


@router.delete("")
def delete_preferences(
    db: Session = Depends(get_db),
    auth: dict = Depends(require_api_access),
):
    """Reset user preferences to defaults (empty object)."""
    user_id = _get_user_id(auth)
    _ensure_preferences_table(db)

    db.execute(
        text("DELETE FROM user_preferences WHERE user_id = :uid"),
        {"uid": user_id},
    )
    db.commit()

    return {"preferences": {}}
