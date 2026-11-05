"""Shared Mongo handle — import `client`/`db` from here (server.py, routers, seed.py)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel

load_dotenv(Path(__file__).parent.parent / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

logger = logging.getLogger(__name__)

# One entry per collection: every field a route filters, sorts, or dedupes on. Applied by ensure_indexes() at startup.
INDEXES: dict[str, list[IndexModel]] = {
    "status_checks": [IndexModel([("timestamp", DESCENDING)], name="timestamp_desc")],
    "users": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("email", ASCENDING)], name="email", unique=True),
    ],
    "sessions": [
        IndexModel([("token", ASCENDING)], name="token", unique=True),
        IndexModel([("created_at", ASCENDING)], name="ttl", expireAfterSeconds=30 * 24 * 3600),
    ],
    "groups": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("member_ids", ASCENDING)], name="member_ids"),
        IndexModel([("approver_ids", ASCENDING)], name="approver_ids"),
    ],
    "requests": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("requester_id", ASCENDING), ("created_at", DESCENDING)], name="requester_created"),
        IndexModel([("group_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)], name="group_status_created"),
    ],
    "messages": [IndexModel([("group_id", ASCENDING), ("created_at", DESCENDING)], name="group_created")],
    "notifications": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
    ],
    "counters": [IndexModel([("id", ASCENDING)], name="id", unique=True)],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)

