"""Reading a photo the app sent as base64: size limits and a real type check."""

import asyncio
import base64
import binascii
import io

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600
MAX_PIXELS = 40_000_000  # refuses "decompression bomb" uploads before decoding them


def image_type(data: bytes) -> tuple[str, str] | None:
    """(mime type, file extension) from the magic bytes, or None if it is not
    a JPEG, PNG or WebP. Never trust the client's label."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def decode_photo(encoded: str, max_bytes: int) -> tuple[bytes, str, str]:
    """(bytes, mime type, extension), or the right 4xx for a bad upload."""
    # Size first: decoding an unbounded payload could pin a lot of memory.
    if len(encoded) > max_bytes * 4 // 3 + 1024:
        raise HTTPException(413, "That photo is too large.")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "That photo couldn't be read.")
    if not image:
        raise HTTPException(400, "That photo is empty.")
    if len(image) > max_bytes:
        raise HTTPException(413, "That photo is too large.")
    kind = image_type(image)
    if kind is None:
        raise HTTPException(415, "Only JPEG, PNG or WebP photos can be used.")
    return image, kind[0], kind[1]


def _reencode(data: bytes) -> bytes:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)  # honour the phone's rotation, then drop the tag
            im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            # A fresh JPEG with no EXIF, so the photo's location and camera details are gone.
            im.save(out, "JPEG", quality=85, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise HTTPException(415, "That photo couldn't be read. Try another one.")


async def clean_photo(data: bytes) -> tuple[bytes, str, str]:
    """Re-encode an upload as a plain JPEG: no metadata (EXIF location), at most
    1600 px on a side. (bytes, mime type, extension)."""
    return await asyncio.to_thread(_reencode, data), "image/jpeg", "jpg"
