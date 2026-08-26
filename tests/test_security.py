"""认证、租户隔离、角色授权、会话撤销与审计测试。"""

from __future__ import annotations

from application.main import build_app
from application.service.uc_main_orchestration import MainOrchestration
from fastapi.testclient import TestClient

from security import (
    AuthenticationError,
    Principal,
    SecuritySettings,
    SecurityStore,
    UserRole,
)


def _settings(db_path=":memory:") -> SecuritySettings:
    return SecuritySettings(
        enabled=True,
        db_path=str(db_path),
        bootstrap_token="bootstrap-token-that-is-at-least-32-characters",
        cookie_name="test_thesis_session",
        cookie_secure=False,
        session_hours=8,
        idle_minutes=30,
    )


def test_passwords_and_tokens_are_not_stored_in_plaintext():
    store = SecurityStore(settings=_settings())
    owner = store.bootstrap_owner(
        tenant_name="Research Lab",
        username="owner@example.com",
        password="correct horse battery staple",
        bootstrap_token=store.settings.bootstrap_token,
    )
    token, principal = store.login(
        "owner@example.com", "correct horse battery staple", "127.0.0.1"
    )
    assert principal.tenant_id == owner["tenant_id"]
    assert store.authenticate(token) == principal
    user_row = store._db.execute(  # noqa: SLF001 - storage invariant
        "SELECT password_hash FROM t_security_user WHERE user_id=?", (owner["user_id"],)
    ).fetchone()
    session_row = store._db.execute(  # noqa: SLF001
        "SELECT token_hash FROM t_security_session WHERE session_id=?", (principal.session_id,)
    ).fetchone()
    assert "correct horse" not in str(user_row[0])
    assert token not in str(session_row[0])
    store.logout(principal)
    assert store.authenticate(token) is None


def test_login_failures_use_generic_error_and_lock_account():
    store = SecurityStore(settings=_settings())
    store.bootstrap_owner(
        tenant_name="Lab", username="owner", password="long-enough-password",
        bootstrap_token=store.settings.bootstrap_token,
    )
    messages = []
    for _ in range(5):
        try:
            store.login("owner", "wrong-password-value")
        except AuthenticationError as exc:
            messages.append(str(exc))
    assert set(messages) == {"用户名或密码无效"}
    row = store._db.execute(  # noqa: SLF001
        "SELECT failed_attempts, locked_until FROM t_security_user WHERE username='owner'"
    ).fetchone()
    assert int(row[0]) == 5
    assert str(row[1])
    try:
        store.login("owner", "long-enough-password")
    except AuthenticationError as exc:
        assert str(exc) == "用户名或密码无效"
    else:
        raise AssertionError("锁定期内不得登录")


def test_security_middleware_enforces_tenant_and_roles(monkeypatch):
    monkeypatch.setenv("THESIS_CORS_ORIGINS", "http://testserver")
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    store = SecurityStore(settings=_settings())
    app = build_app(
        orchestration=MainOrchestration(),
        security_store=store,
    )
    owner_client = TestClient(app)
    boot = owner_client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": store.settings.bootstrap_token},
        json={
            "tenant_name": "Tenant A",
            "username": "owner-a",
            "password": "owner-a-strong-password",
        },
    ).json()
    assert boot["code"] == 0
    login = owner_client.post(
        "/api/v1/auth/login",
        json={"username": "owner-a", "password": "owner-a-strong-password"},
    )
    assert login.json()["code"] == 0
    assert "HttpOnly" in login.headers["set-cookie"]

    created = owner_client.post(
        "/api/v1/console/tasks",
        json={
            "title": "Tenant A Paper", "degree": "MASTER",
            "subject_field": "AI", "tenant_id": "attacker-controlled",
        },
    ).json()
    task_id = created["data"]["task_id"]
    record = app.state.orchestration._store.get(task_id)  # noqa: SLF001
    assert record.tenant_id == boot["data"]["tenant_id"]
    assert record.owner_user_id == boot["data"]["user_id"]

    native_created = owner_client.post(
        "/api/v1/tasks",
        json={
            "title": "Native Shared Task",
            "degree": "BACHELOR",
            "discipline": "AI",
        },
    )
    assert native_created.status_code == 200
    native_task_id = native_created.json()["data"]["task_id"]
    assert app.state.orchestration._store.get(native_task_id).tenant_id == boot["data"]["tenant_id"]  # noqa: SLF001

    reviewer = owner_client.post(
        "/api/v1/auth/users",
        json={
            "username": "reviewer-a", "password": "reviewer-strong-password",
            "role": "REVIEWER",
        },
    ).json()
    assert reviewer["code"] == 0
    reviewer_client = TestClient(app)
    assert reviewer_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer-a", "password": "reviewer-strong-password"},
    ).json()["code"] == 0
    denied = reviewer_client.post(
        "/api/v1/console/tasks",
        json={"title": "Denied", "degree": "MASTER", "subject_field": "AI"},
    )
    assert denied.status_code == 403
    assert reviewer_client.get(
        f"/api/v1/console/tasks/{task_id}/progress"
    ).status_code == 200
    assert reviewer_client.delete(
        f"/api/v1/console/tasks/{task_id}"
    ).status_code == 403

    # 精确构造第二租户，验证同 ID 资源不能跨租户读取。
    with store._lock:  # noqa: SLF001
        tenant_b = "TEN-B"
        user_b = store._create_user_locked(  # noqa: SLF001
            tenant_id=tenant_b, tenant_name="Tenant B", username="owner-b",
            password="owner-b-strong-password", role=UserRole.OWNER,
            create_tenant=True,
        )
        store._db.commit()  # noqa: SLF001
    assert user_b
    tenant_b_client = TestClient(app)
    assert tenant_b_client.post(
        "/api/v1/auth/login",
        json={"username": "owner-b", "password": "owner-b-strong-password"},
    ).json()["code"] == 0
    assert tenant_b_client.get(
        f"/api/v1/console/tasks/{task_id}/progress"
    ).status_code == 403
    assert tenant_b_client.get("/api/v1/console/tasks").json()["data"] == []
    app.state.docx_service._repo.save_output(  # noqa: SLF001
        {
            "file_id": "tenant-a-secret.docx",
            "session_id": record.session_id,
            "file_path": "C:/not-needed-for-authorization-test.docx",
            "filename": "secret.docx",
        }
    )
    assert tenant_b_client.get(
        "/api/v1/docx/files/tenant-a-secret.docx"
    ).status_code == 403

    audit = owner_client.get("/api/v1/auth/audit").json()
    assert audit["code"] == 0
    assert any(item["action"] == "api.mutation" for item in audit["data"])


def test_unauthenticated_requests_and_insecure_cors_are_rejected(monkeypatch):
    monkeypatch.setenv("THESIS_CORS_ORIGINS", "http://testserver")
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    store = SecurityStore(settings=_settings())
    app = build_app(orchestration=MainOrchestration(), security_store=store)
    response = TestClient(app).get("/api/v1/console/tasks")
    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"

    monkeypatch.setenv("THESIS_CORS_ORIGINS", "*")
    try:
        build_app(orchestration=MainOrchestration(), security_store=store)
    except RuntimeError as exc:
        assert "CORS" in str(exc)
    else:
        raise AssertionError("认证模式不得允许通配 CORS")

    monkeypatch.setenv("THESIS_CORS_ORIGINS", "*,http://localhost:8787")
    try:
        build_app(orchestration=MainOrchestration(), security_store=store)
    except RuntimeError as exc:
        assert "CORS" in str(exc)
    else:
        raise AssertionError("认证模式不得在混合来源列表中允许通配 CORS")


def test_default_local_cors_supports_credentialed_ui(monkeypatch):
    monkeypatch.delenv("THESIS_CORS_ORIGINS", raising=False)
    monkeypatch.setenv("THESIS_AUTH_ENABLED", "false")
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    app = build_app(orchestration=MainOrchestration())
    client = TestClient(app)

    for origin in ("http://127.0.0.1:8787", "http://localhost:8787"):
        response = client.options(
            "/api/v1/console/tasks",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"

    response = client.options(
        "/api/v1/console/tasks",
        headers={
            "Origin": "https://unlisted.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers
