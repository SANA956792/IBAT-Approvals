import io
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from lib.auth import approver_group_ids, current_user, load_visible_group, request_visibility
from lib.dates import today_iso
from lib.db import db
from models.schemas import ApprovalRequest, DecisionIn, Notification, RequestIn, Stats, UserPublic, now_utc

router = APIRouter(tags=["requests"])
Scope = Literal["all", "mine", "inbox"]
TYPE_LABEL = {"payment": "Payment", "leave": "Leave", "office_work": "Office Work"}


async def _notify(user_ids: list[str], title: str, body: str, link: str) -> None:
    docs = [Notification(user_id=u, title=title, body=body, link=link).model_dump() for u in dict.fromkeys(user_ids)]
    if docs:
        await db.notifications.insert_many(docs)


async def _build_query(user: UserPublic, scope: Scope, status: Optional[str], type: Optional[str],
                       group_id: Optional[str], q: Optional[str]) -> dict:
    clauses: list[dict] = [await request_visibility(user)]
    if scope == "mine":
        clauses.append({"requester_id": user.id})
    elif scope == "inbox":
        clauses.append({"group_id": {"$in": await approver_group_ids(user)}})
        clauses.append({"requester_id": {"$ne": user.id}})
    if status:
        clauses.append({"status": status})
    if type:
        clauses.append({"type": type})
    if group_id:
        clauses.append({"group_id": group_id})
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        clauses.append({"$or": [{"title": rx}, {"code": rx}, {"requester_name": rx}, {"vendor": rx}, {"description": rx}]})
    return {"$and": [c for c in clauses if c]} if any(clauses) else {}


@router.get("/requests", response_model=list[ApprovalRequest])
async def list_requests(scope: Scope = "all", status: Optional[str] = None, type: Optional[str] = None,
                        group_id: Optional[str] = None, q: Optional[str] = None,
                        user: UserPublic = Depends(current_user)):
    query = await _build_query(user, scope, status, type, group_id, q)
    docs = await db.requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return [ApprovalRequest(**d) for d in docs]


@router.get("/requests/export")
async def export_requests(scope: Scope = "all", status: Optional[str] = None, type: Optional[str] = None,
                          group_id: Optional[str] = None, q: Optional[str] = None,
                          user: UserPublic = Depends(current_user)):
    query = await _build_query(user, scope, status, type, group_id, q)
    docs = await db.requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(10000)
    rows = [ApprovalRequest(**d) for d in docs]

    wb = Workbook()
    ws = wb.active
    ws.title = "Approvals"
    headers = ["Request ID", "Type", "Title", "Group", "Requested By", "Approver", "Status", "Amount", "Currency",
               "Vendor/Payee", "Leave Type", "From", "To", "Priority", "Description", "Reviewer Comment",
               "Reviewed By", "Reviewed At", "Created At"]
    ws.append(headers)
    head_fill = PatternFill("solid", fgColor="0B1118")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(vertical="center")
    fills = {"pending": "FEF3C7", "approved": "D1FAE5", "rejected": "FFE4E6"}
    for r in rows:
        ws.append([
            r.code, TYPE_LABEL[r.type], r.title, r.group_name, r.requester_name, r.approver_name, r.status.title(),
            r.amount, r.currency if r.type == "payment" else "", r.vendor, r.leave_type, r.start_date or "",
            r.end_date or "", r.priority.title(), r.description, r.comment, r.reviewed_by_name or "",
            r.reviewed_at.strftime("%Y-%m-%d %H:%M") if r.reviewed_at else "", r.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
        ws.cell(row=ws.max_row, column=7).fill = PatternFill("solid", fgColor=fills[r.status])
    widths = [12, 12, 32, 20, 18, 18, 11, 12, 9, 20, 12, 12, 12, 10, 40, 32, 18, 17, 17]
    for i, w in enumerate(widths):
        ws.column_dimensions[ws.cell(row=1, column=i + 1).column_letter].width = w
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"approvals_{today_iso()}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/requests/{request_id}", response_model=ApprovalRequest)
async def get_request(request_id: str, user: UserPublic = Depends(current_user)):
    vis = await request_visibility(user)
    doc = await db.requests.find_one({"$and": [{"id": request_id}, vis]} if vis else {"id": request_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Request not found")
    return ApprovalRequest(**doc)


@router.post("/requests", response_model=ApprovalRequest)
async def create_request(body: RequestIn, user: UserPublic = Depends(current_user)):
    group = await load_visible_group(user, body.group_id)  # must belong to the group (admin: any)
    if body.approver_id not in group.get("approver_ids", []):
        raise HTTPException(400, "Selected approver is not an approver of this group")
    if body.approver_id == user.id:
        raise HTTPException(400, "You can't approve your own request — pick another approver")
    approver = await db.users.find_one({"id": body.approver_id}, {"_id": 0, "name": 1})
    if not approver:
        raise HTTPException(400, "Approver not found")
    counter = await db.counters.find_one_and_update(
        {"id": "requests"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    data = body.model_dump()
    if body.type != "payment":
        data.update(amount=None, vendor="")
    if body.type != "leave":
        data.update(start_date=None, end_date=None, leave_type="")
    req = ApprovalRequest(
        **data, code=f"REQ-{1000 + counter['seq']}", group_name=group["name"], approver_name=approver["name"],
        requester_id=user.id, requester_name=user.name,
    )
    await db.requests.insert_one(req.model_dump())
    others = [a for a in group.get("approver_ids", []) if a not in (user.id, body.approver_id)]
    await _notify([body.approver_id], f"New {TYPE_LABEL[req.type]} request for you",
                  f"{user.name}: {req.title} ({req.code})", f"/approvals?open={req.id}")
    await _notify(others, f"New request in {group['name']}", f"{user.name}: {req.title} ({req.code})",
                  f"/approvals?open={req.id}")
    return req


@router.post("/requests/{request_id}/decision", response_model=ApprovalRequest)
async def decide(request_id: str, body: DecisionIn, user: UserPublic = Depends(current_user)):
    vis = await request_visibility(user)
    doc = await db.requests.find_one({"$and": [{"id": request_id}, vis]} if vis else {"id": request_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Request not found")
    if user.role == "employee" or doc["group_id"] not in await approver_group_ids(user):
        raise HTTPException(403, "Only an approver of this group can decide")
    if doc["requester_id"] == user.id:
        raise HTTPException(403, "You can't approve or reject your own request")
    if doc["status"] != "pending":
        raise HTTPException(409, f"This request was already {doc['status']}")
    if body.decision == "rejected" and not body.comment.strip():
        raise HTTPException(400, "Please add a reason when rejecting")
    update = {"status": body.decision, "comment": body.comment.strip(), "reviewed_by_id": user.id,
              "reviewed_by_name": user.name, "reviewed_at": now_utc()}
    res = await db.requests.find_one_and_update(
        {"id": request_id, "status": "pending"}, {"$set": update}, projection={"_id": 0}, return_document=True)
    if not res:
        raise HTTPException(409, "This request was already decided")
    verb = "approved" if body.decision == "approved" else "rejected"
    await _notify([doc["requester_id"]], f"Your request was {verb}",
                  f"{doc['title']} ({doc['code']}) by {user.name}" + (f": {body.comment.strip()}" if body.comment.strip() else ""),
                  f"/?open={request_id}")
    return ApprovalRequest(**res)


@router.get("/stats", response_model=Stats)
async def stats(user: UserPublic = Depends(current_user)):
    agids = await approver_group_ids(user) if user.role != "employee" else []
    pending_for_me = await db.requests.count_documents(
        {"group_id": {"$in": agids}, "status": "pending", "requester_id": {"$ne": user.id}}) if agids else 0
    mine = {"requester_id": user.id}
    return Stats(
        pending_for_me=pending_for_me,
        my_pending=await db.requests.count_documents({**mine, "status": "pending"}),
        my_approved=await db.requests.count_documents({**mine, "status": "approved"}),
        my_rejected=await db.requests.count_documents({**mine, "status": "rejected"}),
        my_total=await db.requests.count_documents(mine),
        unread_notifications=await db.notifications.count_documents({"user_id": user.id, "read": False}),
        today=today_iso(),
    )

