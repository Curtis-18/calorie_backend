"""Supabase Storage for snap photos, through its REST API with the service key.

Photos live in a private bucket: nobody can open one without a short-lived
signed link from here. Every failure becomes [StorageUnavailable] so callers
can answer with a clean 5xx instead of leaking upstream details.
"""

import logging

import httpx

from app.core.config import settings

log = logging.getLogger("calorie_backend")

SIGNED_URL_SECONDS = 3600


class StorageUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(settings.supabase_service_role_key)


def _base() -> str:
    return f"{settings.supabase_url}/storage/v1"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not key:
        raise StorageUnavailable("SUPABASE_SERVICE_ROLE_KEY is not set")
    return {"Authorization": f"Bearer {key}", "apikey": key}


async def upload(path: str, data: bytes, mime_type: str) -> None:
    url = f"{_base()}/object/{settings.snaps_bucket}/{path}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                url, content=data, timeout=30.0,
                headers={**_headers(), "Content-Type": mime_type, "x-upsert": "true"},
            )
    except httpx.HTTPError as exc:
        raise StorageUnavailable(f"upload failed: {exc!r}") from exc
    if r.status_code >= 300:
        log.error("storage upload %s: %s", r.status_code, r.text[:300])
        raise StorageUnavailable(f"upload failed with {r.status_code}")


async def sign(paths: list[str]) -> dict[str, str | None]:
    """A temporary viewing link for each path (None if one can't be made)."""
    if not paths:
        return {}
    url = f"{_base()}/object/sign/{settings.snaps_bucket}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                url, json={"expiresIn": SIGNED_URL_SECONDS, "paths": paths},
                headers=_headers(), timeout=20.0,
            )
    except httpx.HTTPError as exc:
        raise StorageUnavailable(f"sign failed: {exc!r}") from exc
    if r.status_code >= 300:
        log.error("storage sign %s: %s", r.status_code, r.text[:300])
        raise StorageUnavailable(f"sign failed with {r.status_code}")

    out: dict[str, str | None] = {p: None for p in paths}
    for item in r.json():
        signed = item.get("signedURL")
        if item.get("path") in out and signed and not item.get("error"):
            out[item["path"]] = f"{_base()}{signed}"
    return out


async def delete(paths: list[str]) -> None:
    if not paths:
        return
    url = f"{_base()}/object/{settings.snaps_bucket}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.request("DELETE", url, json={"prefixes": paths}, headers=_headers(), timeout=20.0)
    except httpx.HTTPError as exc:
        raise StorageUnavailable(f"delete failed: {exc!r}") from exc
    if r.status_code >= 300:
        log.error("storage delete %s: %s", r.status_code, r.text[:300])
        raise StorageUnavailable(f"delete failed with {r.status_code}")
