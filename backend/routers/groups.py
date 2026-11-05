from fastapi import APIRouter, Depends, HTTPException

from lib.auth import current_user, load_visible_group, require_roles
from lib.db import db
from models.schemas import GroupIn, GroupOut, Message, MessageIn, OkOut, UserBrief, UserPublic, new_id, now_utc

router = APIRouter(prefix="/groups", tags=["groups"])
admin_only = require_roles("admin")


async def _briefs(ids: list[str]) -> dict[str, UserBrief]:
    docs = await db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}).to_list(5000)
    return {d["id"]: UserBrief(**d) for d in docs}


async def _to_out(groups: list[dict]) -> list[GroupOut]:
    ids = list({uid for g in groups for uid in g.get("member_ids", []) + g.get("approver_ids", [])})
    users = await _briefs(ids)
    out = []
    for g in groups:
        total = await db.requests.count_documents({"group_id": g["id"]})
        pending = await db.requests.count_documents({"group_id": g["id"], "status": "pending"})
        out.append(GroupOut(
            **g,
            members=[users[i] for i in g.get("member_ids", []) if i in users],
            approvers=[users[i] for i in g.get("approver_ids", []) if i in users],
            request_count=total, pending_count=pending,
        ))
    return out


async def _validate(body: GroupIn) -> tuple[list[str], list[str]]:
    member_ids = list(dict.fromkeys(body.member_ids))
    approver_ids = list(dict.fromkeys(body.approver_ids))
    users = await _briefs(member_ids + approver_ids)
    missing = [i for i in member_ids + approver_ids if i not in users]
    if missing:
        raise HTTPException(400, "Some selected users do not exist")
    if any(users[i].role == "employee" for i in approver_ids):
        raise HTTPException(400, "Only users with Approver or Admin role can be group approvers")
    if not approver_ids:
        raise HTTPException(400, "Select at least one approver for the group")
    return member_ids, approver_ids


@router.get("", response_model=list[GroupOut])
async def list_groups(user: UserPublic = Depends(current_user)):
    q = {} if user.role == "admin" else {"$or": [{"member_ids": user.id}, {"approver_ids": user.id}]}
    groups = await db.groups.find(q, {"_id": 0}).sort("name", 1).to_list(1000)
    return await _to_out(groups)


@router.post("", response_model=GroupOut)
async def create_group(body: GroupIn, admin: UserPublic = Depends(admin_only)):
    member_ids, approver_ids = await _validate(body)
    g = {
        "id": new_id(), "name": body.name.strip(), "description": body.description.strip(),
        "member_ids": member_ids, "approver_ids": approver_ids,
        "created_by": admin.id, "created_at": now_utc(),
    }
    await db.groups.insert_one(dict(g))
    g.pop("created_by")
    return (await _to_out([g]))[0]


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: str, user: UserPublic = Depends(current_user)):
    g = await load_visible_group(user, group_id)
    return (await _to_out([g]))[0]


@router.put("/{group_id}", response_model=GroupOut)
async def update_group(group_id: str, body: GroupIn, _: UserPublic = Depends(admin_only)):
    member_ids, approver_ids = await _validate(body)
    g = await db.groups.find_one_and_update(
        {"id": group_id},
        {"$set": {"name": body.name.strip(), "description": body.description.strip(),
                  "member_ids": member_ids, "approver_ids": approver_ids}},
        projection={"_id": 0}, return_document=True,
    )
    if not g:
        raise HTTPException(404, "Group not found")
    await db.requests.update_many({"group_id": group_id}, {"$set": {"group_name": g["name"]}})
    return (await _to_out([g]))[0]


@router.delete("/{group_id}", response_model=OkOut)
async def delete_group(group_id: str, _: UserPublic = Depends(admin_only)):
    res = await db.groups.delete_one({"id": group_id})
    if not res.deleted_count:
        raise HTTPException(404, "Group not found")
    await db.messages.delete_many({"group_id": group_id})
    return OkOut()


@router.get("/{group_id}/messages", response_model=list[Message])
async def list_messages(group_id: str, user: UserPublic = Depends(current_user)):
    await load_visible_group(user, group_id)
    docs = await db.messages.find({"group_id": group_id}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return [Message(**d) for d in reversed(docs)]


@router.post("/{group_id}/messages", response_model=Message)
async def post_message(group_id: str, body: MessageIn, user: UserPublic = Depends(current_user)):
    await load_visible_group(user, group_id)
    msg = Message(group_id=group_id, user_id=user.id, user_name=user.name, text=body.text.strip())
    await db.messages.insert_one(msg.model_dump())
    return msg

