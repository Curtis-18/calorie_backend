"""Make the key pair browser push notifications are signed with.

Run it once, on your own machine:

    .venv/bin/python scripts/generate_vapid_keys.py

Then in the Render dashboard (Environment) set:
    VAPID_PUBLIC_KEY   = the public key it prints (safe to share)
    VAPID_PRIVATE_KEY  = the private key it prints (a SECRET: never commit it or paste it in chat)
    PUSH_MODE          = web

Keep the pair: a new pair makes every existing browser subscription stop working.
"""

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    vapid = Vapid()
    vapid.generate_keys()
    private = _b64(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(
        vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")


if __name__ == "__main__":
    main()
