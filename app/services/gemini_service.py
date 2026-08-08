import base64
import json
import httpx
from app.core.config import settings

PROMPT = """Identify each distinct food item visible in this image.
For each item, estimate its portion size in grams.
Respond with ONLY a JSON array, no other text, in this exact shape:
[{"name": "food name", "estimated_grams": 150}]
If you cannot identify any food, respond with an empty array: []"""

async def identify_foods(image_bytes: bytes, mime_type: str) -> list[dict]:
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded_image,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
        },
    }

    url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(raw_text)