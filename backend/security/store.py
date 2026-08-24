"""SQLite 用户、会话、登录保护与不可变审计日志。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Principal, UserRole
from .settings import SecuritySettings


class AuthenticationError(ValueError):
    """对外统一认证失败，避免账户枚举。"""


class AuthorizationError(PermissionError):
    """主体无权访问当前资源。"""


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _now() -> str:
    return _iso(_now_dt())


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SecurityStore:
    """不保存明文密码或明文会话令牌。"""

    _SCRYPT_N = 2**14
    _SCRYPT_R = 8
    _SCRYPT_P = 5

    def __init__(
        self, db_path: str | Path = ":memory:", settings: SecuritySettings | None = None
    ) -> None:
        self.settings = settings or SecuritySettings.from_env()
        self._lock = threading.RLock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        self._init_schema()
        self._dummy_salt = b"thesis-agent-dummy-salt-32bytes!"[:32]
        self._dummy_hash = self._derive("invalid-password", self._dummy_salt)

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS t_security_tenant (
                tenant_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS t_security_user (
                user_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                username TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(tenant_id, username)
            );
            CREATE TABLE IF NOT EXISTS t_security_session (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS t_security_audit (
                audit_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL DEFAULT '',
                resource_id TEXT NOT NULL DEFAULT '',
                method TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL DEFAULT '',
                status_code INTEGER NOT NULL DEFAULT 0,
                request_id TEXT NOT NULL DEFAULT '',
                ip_hash TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_security_audit_tenant
            ON t_security_audit(tenant_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_security_username
            ON t_security_user(username);
            """
        )
        self._db.commit()

    def bootstrap_owner(
        self, *, tenant_name: str, username: str, password: str, bootstrap_token: str
    ) -> dict[str, str]:
        expected = self.settings.bootstrap_token
        if not expected or not hmac.compare_digest(bootstrap_token, expected):
            raise AuthenticationError("初始化凭据无效")
        with self._lock:
            count = int(self._db.execute("SELECT COUNT(*) FROM t_security_user").fetchone()[0])
            if count:
                raise AuthenticationError("系统已经初始化")
            tenant_id = f"TEN-{uuid.uuid4().hex[:16].upper()}"
            user_id = self._create_user_locked(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                username=username,
                password=password,
                role=UserRole.OWNER,
                create_tenant=True,
            )
            self._db.commit()
        self.audit(
            tenant_id=tenant_id, user_id=user_id, action="security.bootstrap",
            resource_type="tenant", resource_id=tenant_id,
        )
        return {"tenant_id": tenant_id, "user_id": user_id, "username": username}

    def create_user(
        self, *, principal: Principal, username: str, password: str, role: UserRole
    ) -> dict[str, str]:
        if principal.role != UserRole.OWNER:
            raise AuthorizationError("只有租户所有者可以创建用户")
        with self._lock:
            user_id = self._create_user_locked(
                tenant_id=principal.tenant_id,
                tenant_name="",
                username=username,
                password=password,
                role=role,
                create_tenant=False,
            )
            self._db.commit()
        self.audit(
            tenant_id=principal.tenant_id, user_id=principal.user_id,
            action="security.user_create", resource_type="user", resource_id=user_id,
            detail={"role": role.value},
        )
        return {"user_id": user_id, "username": username, "role": role.value}

    def _create_user_locked(
        self, *, tenant_id: str, tenant_name: str, username: str, password: str,
        role: UserRole, create_tenant: bool,
    ) -> str:
        username = username.strip().casefold()
        self._validate_credentials(username, password)
        now = _now()
        if create_tenant:
            if not tenant_name.strip():
                raise AuthenticationError("租户名称不能为空")
            self._db.execute(
                "INSERT INTO t_security_tenant(tenant_id, name, created_at) VALUES(?, ?, ?)",
                (tenant_id, tenant_name.strip(), now),
            )
        salt = secrets.token_bytes(32)
        password_hash = self._derive(password, salt)
        user_id = f"USR-{uuid.uuid4().hex[:16].upper()}"
        self._db.execute(
            "INSERT INTO t_security_user(user_id, tenant_id, username, password_salt, "
            "password_hash, role, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, tenant_id, username, salt.hex(), password_hash.hex(),
                role.value, now, now,
            ),
        )
        return user_id

    def login(self, username: str, password: str, ip_address: str = "") -> tuple[str, Principal]:
        username = username.strip().casefold()[:128]
        now = _now_dt()
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_security_user WHERE username=? ORDER BY created_at LIMIT 1",
                (username,),
            ).fetchone()
            if row is None:
                hmac.compare_digest(self._derive(password[:1024], self._dummy_salt), self._dummy_hash)
                self.audit(action="security.login_failed", ip_address=ip_address)
                raise AuthenticationError("用户名或密码无效")
            if not bool(row["active"]):
                self._record_login_failure_locked(row, now)
                raise AuthenticationError("用户名或密码无效")
            locked_until = str(row["locked_until"])
            if locked_until and _parse(locked_until) > now:
                self.audit(
                    tenant_id=str(row["tenant_id"]), user_id=str(row["user_id"]),
                    action="security.login_failed", ip_address=ip_address,
                )
                raise AuthenticationError("用户名或密码无效")
            actual = self._derive(password[:1024], bytes.fromhex(str(row["password_salt"])))
            valid = hmac.compare_digest(actual.hex(), str(row["password_hash"]))
            if not valid:
                self._record_login_failure_locked(row, now)
                raise AuthenticationError("用户名或密码无效")
            self._db.execute(
                "UPDATE t_security_user SET failed_attempts=0, locked_until='', updated_at=? "
                "WHERE user_id=?",
                (_iso(now), str(row["user_id"])),
            )
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            session_id = f"SES-{uuid.uuid4().hex[:20].upper()}"
            self._db.execute(
                "INSERT INTO t_security_session(session_id, user_id, token_hash, expires_at, "
                "last_seen_at, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    session_id, str(row["user_id"]), token_hash,
                    _iso(now + timedelta(hours=self.settings.session_hours)),
                    _iso(now), _iso(now),
                ),
            )
            self._db.commit()
            principal = Principal(
                user_id=str(row["user_id"]), tenant_id=str(row["tenant_id"]),
                username=str(row["username"]), role=UserRole(str(row["role"])),
                session_id=session_id,
            )
        self.audit(
            tenant_id=principal.tenant_id, user_id=principal.user_id,
            action="security.login", resource_type="session", resource_id=session_id,
            ip_address=ip_address,
        )
        return token, principal

    def authenticate(self, token: str) -> Principal | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = _now_dt()
        with self._lock:
            row = self._db.execute(
                "SELECT s.*, u.tenant_id, u.username, u.role, u.active FROM t_security_session s "
                "JOIN t_security_user u ON u.user_id=s.user_id WHERE s.token_hash=?",
                (token_hash,),
            ).fetchone()
            if row is None or str(row["revoked_at"]) or not bool(row["active"]):
                return None
            if _parse(str(row["expires_at"])) <= now:
                return None
            if _parse(str(row["last_seen_at"])) + timedelta(minutes=self.settings.idle_minutes) <= now:
                return None
            if _parse(str(row["last_seen_at"])) + timedelta(seconds=60) <= now:
                self._db.execute(
                    "UPDATE t_security_session SET last_seen_at=? WHERE session_id=?",
                    (_iso(now), str(row["session_id"])),
                )
                self._db.commit()
            return Principal(
                user_id=str(row["user_id"]), tenant_id=str(row["tenant_id"]),
                username=str(row["username"]), role=UserRole(str(row["role"])),
                session_id=str(row["session_id"]),
            )

    def logout(self, principal: Principal) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE t_security_session SET revoked_at=? WHERE session_id=?",
                (_now(), principal.session_id),
            )
            self._db.commit()
        self.audit(
            tenant_id=principal.tenant_id, user_id=principal.user_id,
            action="security.logout", resource_type="session",
            resource_id=principal.session_id,
        )

    def list_audit(self, principal: Principal, limit: int = 200) -> list[dict[str, Any]]:
        if principal.role != UserRole.OWNER:
            raise AuthorizationError("只有租户所有者可以读取审计日志")
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM t_security_audit WHERE tenant_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (principal.tenant_id, min(max(limit, 1), 1000)),
            ).fetchall()
        return [{**dict(row), "detail": json.loads(str(row["detail"]))} for row in rows]

    def audit(
        self, *, action: str, tenant_id: str = "", user_id: str = "",
        resource_type: str = "", resource_id: str = "", method: str = "",
        path: str = "", status_code: int = 0, request_id: str = "",
        ip_address: str = "", detail: dict[str, Any] | None = None,
    ) -> None:
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest() if ip_address else ""
        with self._lock:
            self._db.execute(
                "INSERT INTO t_security_audit(audit_id, tenant_id, user_id, action, "
                "resource_type, resource_id, method, path, status_code, request_id, ip_hash, "
                "detail, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"AUD-{uuid.uuid4().hex[:20].upper()}", tenant_id, user_id, action,
                    resource_type, resource_id, method, path, status_code, request_id,
                    ip_hash, json.dumps(detail or {}, ensure_ascii=False), _now(),
                ),
            )
            self._db.commit()

    def _record_login_failure_locked(self, row: sqlite3.Row, now: datetime) -> None:
        attempts = int(row["failed_attempts"]) + 1
        locked_until = _iso(now + timedelta(minutes=15)) if attempts >= 5 else ""
        self._db.execute(
            "UPDATE t_security_user SET failed_attempts=?, locked_until=?, updated_at=? "
            "WHERE user_id=?",
            (attempts, locked_until, _iso(now), str(row["user_id"])),
        )
        self._db.commit()
        self.audit(
            tenant_id=str(row["tenant_id"]), user_id=str(row["user_id"]),
            action="security.login_failed",
            detail={"locked": bool(locked_until)},
        )

    @classmethod
    def _derive(cls, password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=cls._SCRYPT_N, r=cls._SCRYPT_R, p=cls._SCRYPT_P,
            dklen=32, maxmem=64 * 1024 * 1024,
        )

    @staticmethod
    def _validate_credentials(username: str, password: str) -> None:
        if len(username) < 3 or len(username) > 128:
            raise AuthenticationError("用户名长度必须在 3..128")
        if len(password) < 12 or len(password) > 1024:
            raise AuthenticationError("密码长度必须在 12..1024")
