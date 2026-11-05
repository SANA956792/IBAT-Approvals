"""Pydantic v2 models. Every model here has a hand-written TS mirror in frontend/src/lib/types.ts."""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, EmailStr, Field, model_validator


def _utc(d: datetime) -> datetime:
    # motor returns naive datetimes; normalise so JSON carries the +00:00 offset
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


UTCDateTime = Annotated[datetime, AfterValidator(_utc)]
Role = Literal["admin", "approver", "employee"]
ReqType = Literal["payment", "leave", "office_work"]
Status = Literal["pending", "approved", "rejected"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


# ---------- users / auth ----------
class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    role: Role
    department: str = ""
    created_at: UTCDateTime


class UserBrief(BaseModel):
    id: str
    name: str
    email: str
    role: Role


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    department: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RoleUpdate(BaseModel):
    role: Role


class OkOut(BaseModel):
    ok: bool = True


# ---------- groups ----------
class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    member_ids: list[str] = []
    approver_ids: list[str] = []


class GroupOut(BaseModel):
    id: str
    name: str
    description: str
    member_ids: list[str]
    approver_ids: list[str]
    members: list[UserBrief]
    approvers: list[UserBrief]
    request_count: int
    pending_count: int
    created_at: UTCDateTime


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class Message(BaseModel):
    id: str = Field(default_factory=new_id)
    group_id: str
    user_id: str
    user_name: str
    text: str
    created_at: UTCDateTime = Field(default_factory=now_utc)


# ---------- approval requests ----------
class RequestIn(BaseModel):
    type: ReqType
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    group_id: str
    approver_id: str
    amount: Optional[float] = None
    currency: Literal["INR", "USD"] = "INR"
    vendor: str = Field(default="", max_length=120)
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None
    leave_type: str = Field(default="", max_length=40)
    priority: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="after")
    def _check_type_fields(self) -> "RequestIn":
        if self.type == "payment" and (self.amount is None or self.amount <= 0):
            raise ValueError("Payment requests need an amount greater than 0")
        if self.type == "leave":
            if not self.start_date or not self.end_date:
                raise ValueError("Leave requests need a start and end date")
            if self.end_date < self.start_date:
                raise ValueError("End date must be on or after start date")
        return self


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=new_id)
    code: str
    type: ReqType
    title: str
    description: str = ""
    group_id: str
    group_name: str
    approver_id: str
    approver_name: str
    requester_id: str
    requester_name: str
    amount: Optional[float] = None
    currency: Literal["INR", "USD"] = "INR"
    vendor: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    leave_type: str = ""
    priority: Literal["low", "medium", "high"] = "medium"
    status: Status = "pending"
    comment: str = ""
    reviewed_by_id: Optional[str] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[UTCDateTime] = None
    created_at: UTCDateTime = Field(default_factory=now_utc)


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=1000)


class Stats(BaseModel):
    pending_for_me: int
    my_pending: int
    my_approved: int
    my_rejected: int
    my_total: int
    unread_notifications: int
    today: str


# ---------- notifications ----------
class Notification(BaseModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    title: str
    body: str = ""
    link: str = ""
    read: bool = False
    created_at: UTCDateTime = Field(default_factory=now_utc)

