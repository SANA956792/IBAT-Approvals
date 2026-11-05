"""Seed demo data. Run: cd /app/backend && python seed.py [--reset]
Skips if users already exist unless --reset is passed (which wipes app collections)."""

import asyncio
import sys
from datetime import timedelta

from lib.auth import hash_password
from lib.db import db, ensure_indexes
from models.schemas import ApprovalRequest, Message, new_id, now_utc

COLLECTIONS = ["users", "sessions", "groups", "requests", "messages", "notifications", "counters"]

USERS = [
    ("admin", "Priya Sharma", "admin@company.com", "admin123", "admin", "Management"),
    ("rahul", "Rahul Verma", "approver@company.com", "approver123", "approver", "Finance"),
    ("anita", "Anita Desai", "anita@company.com", "approver123", "approver", "HR"),
    ("arjun", "Arjun Mehta", "employee@company.com", "employee123", "employee", "Sales"),
    ("sneha", "Sneha Iyer", "sneha@company.com", "employee123", "employee", "Operations"),
]


async def main(reset: bool) -> None:
    if reset:
        for c in COLLECTIONS:
            await db[c].drop()
    elif await db.users.count_documents({}):
        print("Users exist — skipping (use --reset to reseed)")
        return
    await ensure_indexes()
    now = now_utc()
    u = {}
    for key, name, email, pw, role, dept in USERS:
        u[key] = {"id": new_id(), "name": name, "email": email, "role": role, "department": dept,
                  "password_hash": hash_password(pw), "created_at": now - timedelta(days=30)}
    await db.users.insert_many([dict(v) for v in u.values()])

    groups_spec = [
        ("acc", "Accounts & Finance", "Vendor payments, reimbursements and invoices", ["arjun", "sneha"], ["rahul"]),
        ("hr", "HR Operations", "Leave and people requests", ["arjun", "sneha"], ["anita"]),
        ("it", "IT & DevOps", "Hardware, software and access requests", ["arjun"], ["rahul"]),
        ("adm", "General Admin", "Office supplies, travel and facilities", ["sneha", "arjun"], ["anita", "rahul"]),
    ]
    g = {}
    for key, name, desc, members, approvers in groups_spec:
        g[key] = {"id": new_id(), "name": name, "description": desc, "member_ids": [u[m]["id"] for m in members],
                  "approver_ids": [u[a]["id"] for a in approvers], "created_by": u["admin"]["id"],
                  "created_at": now - timedelta(days=25)}
    await db.groups.insert_many([dict(v) for v in g.values()])

    reqs = [
        ("payment", "Office internet bill - October", "acc", "rahul", "arjun", dict(amount=4720, vendor="Airtel Business"), "pending", "", 0.2),
        ("payment", "Client dinner reimbursement", "acc", "rahul", "sneha", dict(amount=3850, vendor="Taj Restaurant"), "approved", "Approved, receipt verified.", 2),
        ("payment", "Laptop purchase for new hire", "acc", "rahul", "arjun", dict(amount=78500, vendor="Dell India"), "pending", "", 1),
        ("payment", "Conference sponsorship", "acc", "rahul", "sneha", dict(amount=150000, vendor="TechSummit"), "rejected", "Budget exceeded for this quarter.", 5),
        ("leave", "Family function", "hr", "anita", "arjun", dict(start_date="2026-11-03", end_date="2026-11-05", leave_type="Casual"), "pending", "", 0.5),
        ("leave", "Fever - sick leave", "hr", "anita", "sneha", dict(start_date="2026-10-14", end_date="2026-10-15", leave_type="Sick"), "approved", "Get well soon!", 8),
        ("leave", "Annual vacation", "hr", "anita", "sneha", dict(start_date="2026-12-20", end_date="2026-12-31", leave_type="Annual"), "pending", "", 0.1),
        ("office_work", "VPN access for remote work", "it", "rahul", "arjun", dict(priority="high"), "approved", "Access granted.", 3),
        ("office_work", "Replace broken office chair", "adm", "anita", "sneha", dict(priority="low"), "pending", "", 1.5),
        ("office_work", "Book travel to Mumbai client", "adm", "rahul", "arjun", dict(priority="medium"), "rejected", "Please use video call this time.", 6),
        ("payment", "Stationery restock", "adm", "anita", "sneha", dict(amount=2200, vendor="Office Mart"), "approved", "", 4),
    ]
    docs = []
    for i, (typ, title, gk, ak, rk, extra, status, comment, days_ago) in enumerate(reqs):
        created = now - timedelta(days=days_ago)
        reviewed = status != "pending"
        docs.append(ApprovalRequest(
            id=new_id(), code=f"REQ-{1001 + i}", type=typ, title=title, description=f"{title}. Please review.",
            group_id=g[gk]["id"], group_name=g[gk]["name"], approver_id=u[ak]["id"], approver_name=u[ak]["name"],
            requester_id=u[rk]["id"], requester_name=u[rk]["name"], status=status, comment=comment,
            reviewed_by_id=u[ak]["id"] if reviewed else None, reviewed_by_name=u[ak]["name"] if reviewed else None,
            reviewed_at=created + timedelta(hours=5) if reviewed else None, created_at=created, **extra,
        ).model_dump())
    await db.requests.insert_many(docs)
    await db.counters.insert_one({"id": "requests", "seq": len(docs)})

    msgs = [
        ("acc", "rahul", "Team, please attach invoices with every payment request.", 26),
        ("acc", "arjun", "Sure Rahul. Submitted the internet bill just now.", 5),
        ("acc", "rahul", "Thanks Arjun, will review by evening.", 4),
        ("hr", "anita", "Reminder: apply for December leave before 15th Nov.", 30),
        ("hr", "sneha", "Done! Applied for annual leave.", 3),
        ("adm", "sneha", "The chair in cabin 3 is broken, raised a request.", 36),
    ]
    await db.messages.insert_many([Message(group_id=g[gk]["id"], user_id=u[uk]["id"], user_name=u[uk]["name"],
                                           text=t, created_at=now - timedelta(hours=h)).model_dump()
                                   for gk, uk, t, h in msgs])
    print(f"Seeded {len(u)} users, {len(g)} groups, {len(docs)} requests, {len(msgs)} messages")


if __name__ == "__main__":
    asyncio.run(main("--reset" in sys.argv))

