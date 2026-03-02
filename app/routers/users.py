# ---------------------------------------------------------------------------
# app/routers/users.py
# ---------------------------------------------------------------------------
# Purpose : User account and chat message endpoints.
#
# Endpoints:
#   GET  /api/users/{user_id}   – fetch single user
#   POST /api/login             – verify credentials
#   POST /api/logout            – no-op logout
#   GET  /api/users/count       – total registered users
#   GET  /api/chats             – list recent chats
#   POST /api/chats             – post a new chat message
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..models import (
    AuthResponse,
    ChatCreate,
    ChatRead,
    UserCount,
    UserCreate,
    UserRead,
    normalize_username,
)

router = APIRouter(prefix="/api", tags=["Users"])

_db = None  # type: ignore


def set_database(db) -> None:  # noqa: ANN001
    global _db
    _db = db


@router.get("/users/count", response_model=UserCount)
async def user_count():
    cnt = await run_in_threadpool(_db.count_users)
    return UserCount(count=cnt)


@router.get("/users/{user_id}", response_model=UserRead)
async def fetch_user(user_id: int):
    rec = await run_in_threadpool(_db.get_user_by_id, user_id)
    if rec is None:
        raise HTTPException(404, "User not found.")
    return UserRead(**rec.__dict__)


@router.post("/login", response_model=AuthResponse)
async def login_user(payload: UserCreate):
    try:
        uname = normalize_username(payload.username)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    rec = await run_in_threadpool(_db.verify_credentials, uname, payload.password)
    if rec is None:
        raise HTTPException(401, "Invalid credentials.")
    return AuthResponse(**rec.__dict__, message="Login successful.")


@router.post("/logout")
async def logout_user():
    return {"status": "ok", "message": "Logged out."}


@router.get("/chats", response_model=List[ChatRead])
async def list_chats(limit: int = 50):
    recs = await run_in_threadpool(_db.list_chat_messages, limit)
    return [ChatRead(**r.__dict__) for r in recs]


@router.post("/chats", response_model=ChatRead, status_code=201)
async def post_chat(payload: ChatCreate):
    if not payload.message.strip():
        raise HTTPException(400, "Message cannot be empty.")
    user = await run_in_threadpool(_db.get_user_by_id, payload.user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    rec = await run_in_threadpool(
        _db.store_chat_message, payload.user_id, payload.message.strip()
    )
    return ChatRead(**rec.__dict__)
