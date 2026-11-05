from fastapi import APIRouter, Depends, HTTPException

from lib.auth import current_user
from lib.db import db
from models.schemas import Notification, OkOut, UserPublic

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[Notification])
async def list_notifications(user: UserPublic = Depends(current_user)):
    docs = await db.notifications.find({"user_id": user.id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return [Notification(**d) for d in docs]


@router.post("/read-all", response_model=OkOut)
async def read_all(user: UserPublic = Depends(current_user)):
    await db.notifications.update_many({"user_id": user.id, "read": False}, {"$set": {"read": True}})
    return OkOut()


@router.post("/{notification_id}/read", response_model=OkOut)
async def read_one(notification_id: str, user: UserPublic = Depends(current_user)):
    res = await db.notifications.update_one({"id": notification_id, "user_id": user.id}, {"$set": {"read": True}})
    if not res.matched_count:
        raise HTTPException(404, "Notification not found")
    return OkOut()

