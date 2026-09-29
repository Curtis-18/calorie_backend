import base64
import binascii
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_user_id
from app.services.gemini_service import identify_foods

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/estimate-photo", tags=["photo-estimation"])


class PhotoRequest(BaseModel):
    image: str = Field(..., description="Base64 encoded image")


@router.post("")
async def estimate_photo(
    request: PhotoRequest,
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

    try:
        return await identify_foods(image_bytes, mime_type="image/jpeg")
    except Exception as exc:  # noqa: BLE001
        # Log the detail, return something that doesn't leak upstream keys
        # or internal URLs to the client.
        log.exception("photo estimation failed")
        raise HTTPException(status_code=502, detail="Photo analysis service unavailable")
