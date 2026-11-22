# FILE: backend/config.py
# Settings from env (pydantic BaseSettings)

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ── Supabase ──────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "ES256"

    def __init__(self, **values):
        super().__init__(**values)
        if not self.supabase_jwt_secret and self.jwt_secret:
            self.supabase_jwt_secret = self.jwt_secret

    # ── Backend ───────────────────────────────────
    backend_secret_key: str = ""
    cors_origins: List[str] = ["http://localhost:3000"]
    database_url: str = ""

    # ── External APIs (FREE TIER) ─────────────────
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # ── Storage ───────────────────────────────────
    supabase_storage_bucket: str = "sentinel-evidence"
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = ""

    # ── Email ─────────────────────────────────────
    resend_api_key: str = ""
    email_from: str = "noreply@yourdomain.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
