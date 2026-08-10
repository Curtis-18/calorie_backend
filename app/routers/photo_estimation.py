# app/routers/photo_estimation.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user_id
from app.services.gemini_service import identify_foods
import base64

router = APIRouter(prefix="/estimate-photo", tags=["photo-estimation"])

class PhotoRequest(BaseModel):
    image: str  # Base64 encoded image

@router.post("")
async def estimate_photo(
    request: PhotoRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        image_bytes = base64.b64decode(request.image)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data")

    try:
        return await identify_foods(image_bytes, mime_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Photo analysis failed: {e}")