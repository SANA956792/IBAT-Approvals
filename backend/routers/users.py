from fastapi import APIRouter, Depends, HTTPException

from lib.auth import require_roles
from lib.db import db
from models.schemas import RoleUpdate, UserPublic

router = APIRouter(prefix="/users", tags=["users"])
admin_only = require_roles("admin")


@router.get("", response_model=list[UserPublic])
async def list_users(_: UserPublic = Depends(admin_only)):
    docs = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("name", 1).to_list(2000)
    return [UserPublic(**d) for d in docs]


@router.patch("/{user_id}/role", response_model=UserPublic)
async def update_role(user_id: str, body: RoleUpdate, admin: UserPublic = Depends(admin_only)):
    if user_id == admin.id:
        raise HTTPException(400, "You can't change your own role")
    res = await db.users.find_one_and_update(
        {"id": user_id}, {"$set": {"role": body.role}},
        projection={"_id": 0, "password_hash": 0}, return_document=True,
    )
    if not res:
        raise HTTPException(404, "User not found")
    if body.role == "employee":  # an employee can no longer approve
        await db.groups.update_many({"approver_ids": user_id}, {"$pull": {"approver_ids": user_id}})
    return UserPublic(**res)

