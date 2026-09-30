import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _clean_origin(entry: str) -> str:
    """Normalise one CORS_ORIGINS entry.

    A browser never puts a trailing slash in `Origin`, so a pasted
    "https://app.vercel.app/" would silently match nothing and look like the
    deployment was still broken. Same class of mistake as a trailing slash on
    SUPABASE_URL, which is already trimmed above.
    """
    return entry.strip().rstrip("/")


def _origin_to_regex(origin: str) -> str:
    """Turn a wildcard origin into a regex Starlette can fullmatch.

    `*` stands for any run of characters up to the next path separator, so
    `https://app-*.vercel.app` covers every preview deploy of the project
    while still refusing `https://app-x.vercel.app.evil.test`.
    """
    return re.escape(origin).replace(r"\*", "[^/]+")


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
    # An entry may contain `*` as a wildcard host segment; Vercel hands every
    # preview deploy a new subdomain, and an exact-match list would reject
    # each one with a 400 "Disallowed CORS origin".
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
        """Every non-empty entry, wildcards included."""
        return [
            cleaned
            for entry in self.cors_origins.split(",")
            if (cleaned := _clean_origin(entry))
        ]

    @property
    def exact_origins(self) -> list[str]:
        """The literal origins, for Starlette's exact-match allow list.

        Wildcard entries are left out because a literal list entry can never
        match a preview subdomain; they are served by `cors_origin_regex`
        instead.
        """
        return [o for o in self.allowed_origins if "*" not in o]

    @property
    def cors_origin_regex(self) -> str | None:
        """Wildcard entries as one alternation, or None when there are none.

        Starlette only ever fullmatches a single pattern, so the wildcards are
        joined into one. Exact origins are excluded: they are already covered
        by `allow_origins` and leaving them out keeps the regex from growing
        for no benefit.
        """
        patterns = [_origin_to_regex(o) for o in self.allowed_origins if "*" in o]
        return "|".join(patterns) if patterns else None


settings = Settings()
