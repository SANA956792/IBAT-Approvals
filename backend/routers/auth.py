from fastapi import APIRouter, Depends, HTTPException, Request, Response

from lib.auth import current_user, end_session, hash_password, start_session, verify_password
from lib.db import db
from models.schemas import LoginIn, OkOut, RegisterIn, UserPublic, new_id, now_utc

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic)
async def register(body: RegisterIn, response: Response):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "An account with this email already exists")
    user = {
        "id": new_id(), "name": body.name.strip(), "email": email, "role": "employee",
        "department": body.department.strip(), "password_hash": hash_password(body.password),
        "created_at": now_utc(),
    }
    await db.users.insert_one(dict(user))
    await start_session(response, user["id"])
    return UserPublic(**user)


@router.post("/login", response_model=UserPublic)
async def login(body: LoginIn, response: Response):
    user = await db.users.find_one({"email": body.email.lower()}, {"_id": 0})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid email or password")
    await start_session(response, user["id"])
    return UserPublic(**user)


@router.post("/logout", response_model=OkOut)
async def logout(request: Request, response: Response):
    await end_session(request, response)
    return OkOut()


@router.get("/me", response_model=UserPublic)
async def me(user: UserPublic = Depends(current_user)):
    return user

