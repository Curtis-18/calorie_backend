import base64
import json
import logging

import httpx

from app.core.config import settings

log = logging.getLogger("calorie_backend")

PROMPT = """Identify each distinct food item visible in this image.
For each item, estimate its portion size in grams.
Respond with ONLY a JSON array, no other text, in this exact shape:
[{"name": "food name", "estimated_grams": 150}]
If you cannot identify any food, respond with an empty array: []"""

# Every shape the API has come back with when a candidate is blocked or
# safety-filtered. Previously this raised a bare IndexError/KeyError and
# surfaced to the user as an opaque 500.
_API_ERRORS = {
    "response_mime_type": "application/json",
    "response_json_schema": {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "estimated_grams": {"type": "NUMBER"},
            },
            "required": ["name", "estimated_grams"],
        },
    },
}


def _extract_items(data: dict) -> list[dict]:
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "no candidates returned"
        raise RuntimeError(f"gemini returned nothing: {reason}")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    raw_text = "".join(p.get("text", "") for p in parts if p.get("text"))
    if not raw_text.strip():
        raise RuntimeError("gemini returned an empty response")

    parsed = json.loads(raw_text)
    if not isinstance(parsed, list):
        raise RuntimeError("gemini returned a non-array payload")

    items = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        try:
            grams = float(entry.get("estimated_grams") or 0)
        except (TypeError, ValueError):
            grams = 0.0
        if grams <= 0:
            continue
        items.append({"name": str(name), "estimated_grams": grams})
    return items


async def identify_foods(image_bytes: bytes, mime_type: str) -> list[dict]:
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": mime_type, "data": encoded_image}},
                ]
            }
        ],
        "generationConfig": _API_ERRORS,
    }

    url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json=payload,
            timeout=30.0,
        )
        if response.status_code >= 400:
            log.error("gemini error %s: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        data = response.json()

    return _extract_items(data)
