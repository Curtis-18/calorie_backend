from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    usda_api_key: str
    usda_base_url: str = "https://api.nal.usda.gov/fdc/v1"
    gemini_api_key: str
    gemini_model: str = "gemini-3.6-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    supabase_url: str
    database_url: str
    jwt_audience: str = "authenticated"

    # Comma separated. Render/Supabase dashboards hand out a bare
    # postgresql:// string, which asyncpg can't speak, so rewrite it here
    # rather than making the deploy fail with "No module named 'psycopg'".
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    # Ceiling for the base64 photo payload on /estimate-photo.
    max_photo_bytes: int = 8 * 1024 * 1024

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg_driver(cls, v: str) -> str:
        v = v.strip()
        for sync_driver in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgres://"):
            if v.startswith(sync_driver):
                return v.replace(sync_driver, "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("supabase_url", "usda_base_url", "gemini_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
