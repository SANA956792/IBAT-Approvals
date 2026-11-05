"""Session-cookie auth + the single authorization helpers every router uses.

Model: RBAC (admin / approver / employee) + group relationship (member / approver of a group).
The principal is re-read from Mongo on every request, so role changes apply immediately.
"""

import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from passlib.context import CryptContext

from lib.db import db
from models.schemas import UserPublic, now_utc

SESSION_COOKIE = "approvo_session"
SESSION_DAYS = 30
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(p: str) -> str:
    return pwd.hash(p)


def verify_password(p: str, h: str) -> bool:
    try:
        return pwd.verify(p, h)
    except Exception:
        return False


async def start_session(response: Response, user_id: str) -> None:
    token = secrets.token_urlsafe(32)
    await db.sessions.insert_one({"token": token, "user_id": user_id, "created_at": now_utc()})
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax",
        max_age=int(timedelta(days=SESSION_DAYS).total_seconds()), path="/",
    )


async def end_session(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.sessions.delete_one({"token": token})
    response.delete_cookie(SESSION_COOKIE, path="/")


async def current_user(request: Request) -> UserPublic:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    sess = await db.sessions.find_one({"token": token})
    if not sess:
        raise HTTPException(401, "Session expired")
    user = await db.users.find_one({"id": sess["user_id"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "User not found")
    return UserPublic(**user)


def require_roles(*roles: str):
    async def dep(user: UserPublic = Depends(current_user)) -> UserPublic:
        if user.role not in roles:
            raise HTTPException(403, "You don't have permission for this action")
        return user
    return dep


# ---------- relationship scope ----------
async def my_group_ids(user: UserPublic) -> list[str]:
    """Groups the user belongs to (member or approver). Admin sees all."""
    q = {} if user.role == "admin" else {"$or": [{"member_ids": user.id}, {"approver_ids": user.id}]}
    return [g["id"] async for g in db.groups.find(q, {"id": 1})]


async def approver_group_ids(user: UserPublic) -> list[str]:
    q = {} if user.role == "admin" else {"approver_ids": user.id}
    return [g["id"] async for g in db.groups.find(q, {"id": 1})]


async def request_visibility(user: UserPublic) -> dict:
    """Mongo predicate for requests this user may see — applied in the query, never fetch-then-filter."""
    if user.role == "admin":
        return {}
    gids = await my_group_ids(user)
    return {"$or": [{"requester_id": user.id}, {"group_id": {"$in": gids}}]}


async def load_visible_group(user: UserPublic, group_id: str) -> dict:
    q: dict = {"id": group_id}
    if user.role != "admin":
        q["$or"] = [{"member_ids": user.id}, {"approver_ids": user.id}]
    g = await db.groups.find_one(q, {"_id": 0})
    if not g:
        raise HTTPException(404, "Group not found")
    return g

