import base64
import json
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import httpx
from app.core.security import get_current_user_id

router = APIRouter(prefix="/estimate-photo", tags=["photo-estimation"] )

class PhotoRequest(BaseModel):
    image: str # Base64 encoded image

@router.post("")
async def estimate_photo(
    request: PhotoRequest,
    user_id: str = Depends(get_current_user_id)
):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured on server")

    model = "gemini-1.5-flash" # Use the latest stable model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    prompt = """
    Identify each distinct food item visible in this photo of a meal.
    For each item, estimate its portion size in grams and its calories per 100g.
    Respond with ONLY a JSON array in this exact shape:
    [{"name": "white rice", "estimatedGrams": 150, "caloriesPer100g": 130}, ...]
    """

    async with httpx.AsyncClient( ) as client:
        response = await client.post(
            url,
            json={
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": request.image
                            }
                        }
                    ]
                }]
            },
            timeout=30.0
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    try:
        data = response.json()
        raw_text = data['candidates'][0]['content']['parts'][0]['text']
        # Clean potential markdown formatting
        cleaned = raw_text.replace('```json', '').replace('```', '').strip()
        return json.loads(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Gemini response: {str(e)}")
