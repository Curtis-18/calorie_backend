import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.services.account_service import AccountDeletionFailed, delete_account

log = logging.getLogger("calorie_backend")

router = APIRouter(tags=["account"])


@router.delete("/me", status_code=204)
async def delete_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete the signed-in person's account and all of their data. There is
    no undo; the app asks them to confirm first."""
    try:
        await delete_account(db, user_id)
    except AccountDeletionFailed:
        log.exception("account deletion failed")
        raise HTTPException(status_code=502, detail="Couldn't delete your account just now. Please try again.")
    log.info("account deleted: %s", user_id)
    return None
