# ---------------------------------------------------------------------------
# app/services/database.py
# ---------------------------------------------------------------------------
# Purpose : Lightweight SQLite gateway for user accounts and chat messages.
#
# Classes:
#   UserRecord               – dataclass for a user row
#   ChatRecord               – dataclass for a chat row
#   UserAlreadyExistsError   – duplicate-username error
#   DatabaseGateway          – CRUD helper with context-managed connections
#
# Inputs : base_dir (Path) – folder that contains ``data/app.sqlite3``.
# ---------------------------------------------------------------------------
from __future__ import annotations

import hashlib
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

import bcrypt

logger = logging.getLogger(__name__)


@dataclass
class UserRecord:
    id: int
    username: str
    created_at: str


@dataclass
class ChatRecord:
    id: int
    user_id: int
    username: str
    message: str
    created_at: str


class UserAlreadyExistsError(RuntimeError):
    """Raised when a duplicated username is inserted."""


class DatabaseGateway:
    """SQLite helper exposing persistence methods for users and chats."""

    def __init__(self, base_dir: Optional[Path] = None, db_path: str = "") -> None:
        if db_path:
            self.db_path = Path(db_path)
            self.data_dir = self.db_path.parent
        else:
            self.base_dir = base_dir or Path(__file__).resolve().parent.parent
            self.data_dir = self.base_dir / "data"
            self.db_path = self.data_dir / "app.sqlite3"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def initialise(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (DATETIME('now'))
                );
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (DATETIME('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            conn.commit()
        logger.info("Database initialized at %s", self.db_path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ---------- helpers ----------

    @staticmethod
    def _hash(password: str) -> str:
        """Hash password with bcrypt (60-char modular crypt string)."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def _verify(password: str, stored_hash: str) -> bool:
        """Verify password against stored hash. Supports bcrypt and legacy SHA-256."""
        if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        # Legacy SHA-256 fallback
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash

    # ---------- CRUD ----------

    def create_user(self, username: str, password: str) -> UserRecord:
        ph = self._hash(password)
        with self.connection() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, ph),
                )
            except sqlite3.IntegrityError as exc:
                raise UserAlreadyExistsError(username) from exc
            uid = cur.lastrowid
            conn.commit()
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (uid,),
            ).fetchone()
        result = UserRecord(**dict(row))
        logger.info("User created: %s", username)
        return result

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return UserRecord(**dict(row)) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[UserRecord]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return UserRecord(**dict(row)) if row else None

    def verify_credentials(self, username: str, password: str) -> Optional[UserRecord]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        row_dict = dict(row)
        if not self._verify(password, row_dict["password_hash"]):
            return None
        # If legacy hash, upgrade to bcrypt transparently
        if not row_dict["password_hash"].startswith("$2b$"):
            new_hash = self._hash(password)
            with self.connection() as conn:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row_dict["id"]))
                conn.commit()
        return UserRecord(id=row_dict["id"], username=row_dict["username"], created_at=row_dict["created_at"])

    def store_chat_message(self, user_id: int, message: str) -> ChatRecord:
        with self.connection() as conn:
            cur = conn.execute(
                "INSERT INTO chats (user_id, message) VALUES (?, ?)",
                (user_id, message),
            )
            cid = cur.lastrowid
            conn.commit()
            row = conn.execute(
                "SELECT c.id, c.user_id, u.username, c.message, c.created_at "
                "FROM chats c JOIN users u ON u.id=c.user_id WHERE c.id=?",
                (cid,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Insert succeeded but row not found")
        return ChatRecord(**dict(row))

    def list_chat_messages(self, limit: int = 50) -> List[ChatRecord]:
        limit = max(1, min(limit, 500))
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT c.id, c.user_id, u.username, c.message, c.created_at "
                "FROM chats c JOIN users u ON u.id=c.user_id "
                "ORDER BY c.created_at DESC, c.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [ChatRecord(**dict(r)) for r in rows][::-1]

    def count_users(self) -> int:
        with self.connection() as conn:
            (cnt,) = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(cnt)
