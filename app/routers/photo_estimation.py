import base64
import binascii
import logging
import time
import uuid
from datetime import date as date_type

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dates import resolve_today
from app.core.features import Feature, record_usage, require_feature
from app.core.rate_limit import photo_scans
from app.core.security import get_current_user_id
from app.models.photo import EstimatedFood
from app.services.gemini_service import identify_foods
from app.services.usda_service import enrich_detected_foods

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/estimate-photo", tags=["photo-estimation"])


def sniff_image_mime(data: bytes) -> str:
    """Detect the real image type from its magic bytes.

    Every upload used to be labelled image/jpeg. Camera captures are JPEG, but
    a web upload or a gallery image can be PNG, WebP or HEIC, and a wrong label
    risks Gemini misreading or rejecting the image. Falls back to JPEG, the
    common case.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"heim", b"heis"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heif"):
            return "image/heif"
    return "image/jpeg"


class PhotoRequest(BaseModel):
    image: str = Field(..., description="Base64 encoded image")
    # The person's own date, for the daily usage count. Optional: older
    # clients send nothing and are counted on the UTC date.
    date: date_type | None = None
    # What the person said about the meal (speech turned into text on their
    # phone). Short, and passed to the model as data, never as instructions.
    note: str | None = Field(None, max_length=300)


@router.post("", response_model=list[EstimatedFood])
async def estimate_photo(
    request: PhotoRequest,
    background: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    # Check the encoded length first: decoding an unbounded payload lets one
    # request pin a few hundred MB of RAM on a small Render instance.
    if len(request.image) > settings.max_photo_bytes * 4 // 3 + 1024:
        raise HTTPException(status_code=413, detail="Image too large")

    try:
        image_bytes = base64.b64decode(request.image, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 image data")

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image")
    if len(image_bytes) > settings.max_photo_bytes:
        raise HTTPException(status_code=413, detail="Image too large")

    photo_scans.check("photo", user_id, "You've scanned a lot of photos. Try again in a little while.")
    require_feature(user_id, Feature.PHOTO_SCAN)
    day = resolve_today(request.date)

    # One line per scan, so speed and match rate can be read from the Render
    # log before anything is changed (handover: PRODUCT ROADMAP P0.2). Only
    # numbers: no food names, nothing about the person beyond the log's own id.
    started = time.monotonic()
    try:
        mime = sniff_image_mime(image_bytes)
        note = (request.note or "").strip()
        detected = await (
            identify_foods(image_bytes, mime_type=mime, note=note) if note else identify_foods(image_bytes, mime_type=mime)
        )
    except Exception as exc:  # noqa: BLE001
        # Log the detail, return something that doesn't leak upstream keys
        # or internal URLs to the client.
        log.exception("photo estimation failed")
        log.info("scan_done status=gemini_failed ms_gemini=%d", _ms(started))
        raise HTTPException(status_code=502, detail="Photo analysis service unavailable")
    gemini_done = time.monotonic()

    # Macros are filled in here, in parallel, instead of the client making one
    # /foods/search round-trip per detected food over a mobile connection.
    foods = await enrich_detected_foods(detected)
    finished = time.monotonic()
    matched = sum(1 for f in foods if f.get("matched"))
    log.info(
        "scan_done status=ok ms_total=%d ms_gemini=%d ms_usda=%d items=%d matched=%d",
        (finished - started) * 1000, (gemini_done - started) * 1000, (finished - gemini_done) * 1000,
        len(foods), matched,
    )
    background.add_task(record_usage, user_id, Feature.PHOTO_SCAN, day)
    return foods


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)
