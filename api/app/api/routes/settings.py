from fastapi import APIRouter
import json
import os

router = APIRouter()

SITE_SETTINGS_FILE = "/opt/marine-fishing/api/site_settings.json"


@router.get("/settings/google-maps-key")
def get_google_maps_key():
    """Public endpoint: return the Google Maps API key (if configured)."""
    if os.path.exists(SITE_SETTINGS_FILE):
        with open(SITE_SETTINGS_FILE, "r") as f:
            data = json.load(f)
        key = data.get("google_maps_api_key", "")
        if key:
            return {"google_maps_api_key": key}
    return {}
