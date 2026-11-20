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
from app.core.language import get_language
from app.models.photo import EstimatedFood
from app.services.estimates import estimate_foods
from app.services.gemini_service import identify_foods
from app.services.regions import is_region
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
    # Where the person mostly eats (a key from services/regions.py), sent by
    # the app so no database lookup delays the scan. Context for naming dishes
    # only; an unknown value is ignored.
    region: str | None = Field(None, max_length=40)


@router.post("", response_model=list[EstimatedFood])
async def estimate_photo(
    request: PhotoRequest,
    background: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    lang: str = Depends(get_language),
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
    region = request.region if request.region and is_region(request.region) else None
    try:
        mime = sniff_image_mime(image_bytes)
        note = (request.note or "").strip()
        extras = {}
        if note:
            extras["note"] = note
        if region:
            extras["region"] = region
        if lang != "en":
            extras["lang"] = lang
        detected = await identify_foods(image_bytes, mime_type=mime, **extras)
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
    for food in foods:
        local = food.pop("local_name", None)
        if local:
            food["display_name"] = local
    usda_done = time.monotonic()

    # A dish the database has no entry for (a regional stew, street food) gets
    # a typical value with its basis stated, so it can still be logged. Only
    # unmatched items cost this extra call; the photo is not sent again. Any
    # failure just leaves them unmatched, as before.
    for food in foods:
        if food.get("matched"):
            food["source"], food["confidence"] = "usda", "high"
    unmatched = [f for f in foods if not f.get("matched")]
    estimated = 0
    if unmatched:
        estimates = await estimate_foods([f["name"] for f in unmatched], region, **({"lang": lang} if lang != "en" else {}))
        for food in unmatched:
            found = estimates.get(food["name"])
            if found is None:
                continue
            food.update(
                calories_per_100g=found["calories_per_100g"],
                protein_g_per_100g=found["protein_g_per_100g"],
                carbs_g_per_100g=found["carbs_g_per_100g"],
                fat_g_per_100g=found["fat_g_per_100g"],
                source="ai_estimate",
                confidence="medium",
                estimate_basis=found["basis"],
            )
            estimated += 1
    finished = time.monotonic()
    matched = sum(1 for f in foods if f.get("matched"))
    log.info(
        "scan_done status=ok ms_total=%d ms_gemini=%d ms_usda=%d ms_estimate=%d items=%d matched=%d estimated=%d",
        (finished - started) * 1000, (gemini_done - started) * 1000, (usda_done - gemini_done) * 1000,
        (finished - usda_done) * 1000, len(foods), matched, estimated,
    )
    background.add_task(record_usage, user_id, Feature.PHOTO_SCAN, day)
    return foods


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)
