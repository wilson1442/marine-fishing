import secrets

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://marine_user:marine_fishing_2026@localhost:5432/marine_fishing"

    # Redis (optional)
    redis_url: str = "redis://localhost:6379/0"

    # API Keys
    aisstream_api_key: str = ""

    # App config
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    # Frontend
    serve_frontend: bool = True
    frontend_dir: str = "/opt/marine-fishing/frontend"

    # Admin auth
    admin_secret_key: str = secrets.token_hex(32)
    admin_token_expiry_hours: int = 24

    # Zoho CRM
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_api_domain: str = "https://www.zohoapis.com"

    # Backups
    backup_dir: str = "/opt/marine-fishing/backups"
    ssh_key_dir: str = "/opt/marine-fishing/.ssh"
    backup_schedule_file: str = "/opt/marine-fishing/backups/.schedule.json"

    class Config:
        env_file = "/opt/marine-fishing/api/.env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
