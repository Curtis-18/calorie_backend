"""DELETE /me: deleting an account and everything in it."""

import uuid

import httpx
import pytest

from app.services import account_service, storage_service

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _Result:
    def __init__(self, values=()):
        self.values = list(values)

    def scalars(self):
        return self

    def all(self):
        return self.values


class _Db:
    """Records the statements run; the first SELECT returns the snap paths."""

    def __init__(self, paths=(), fail_on=None):
        self.paths, self.fail_on = list(paths), fail_on
        self.statements: list[str] = []
        self.committed = self.rolled_back = False

    async def execute(self, stmt):
        sql = " ".join(str(stmt).split())
        self.statements.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("db down")
        return _Result(self.paths if sql.startswith("SELECT") else ())

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    def deleted_from(self, table: str) -> bool:
        return any(s.startswith(f"DELETE FROM {table}") for s in self.statements)


def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


@pytest.fixture
def service_key(monkeypatch):
    """A deployment with the service role key: storage and the admin API are used."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
    calls = {"storage": [], "auth": []}

    async def fake_storage_delete(paths):
        calls["storage"].append(list(paths))

    async def fake_auth_delete(user_id):
        calls["auth"].append(user_id)

    monkeypatch.setattr(storage_service, "delete", fake_storage_delete)
    monkeypatch.setattr(account_service, "_delete_auth_user_via_api", fake_auth_delete)
    return calls


def test_deleting_removes_photos_then_the_login_then_the_profile(client, service_key):
    db = _Db(paths=[f"{ME}/a.jpg", f"{ME}/b.jpg"])
    _with_db(db)
    r = client.delete("/me")
    assert r.status_code == 204 and r.content == b""
    assert service_key["storage"] == [[f"{ME}/a.jpg", f"{ME}/b.jpg"]]
    assert service_key["auth"] == [ME]
    assert db.deleted_from("profiles") and db.committed


def test_no_photos_means_no_storage_call(client, service_key):
    _with_db(_Db())
    assert client.delete("/me").status_code == 204
    assert service_key["storage"] == [] and service_key["auth"] == [ME]


def test_a_storage_failure_stops_before_anything_is_deleted(client, service_key, monkeypatch):
    """Otherwise the rows would go and the photos would be left with nothing
    pointing at them."""

    async def boom(_paths):
        raise storage_service.StorageUnavailable("down")

    monkeypatch.setattr(storage_service, "delete", boom)
    db = _Db(paths=[f"{ME}/a.jpg"])
    _with_db(db)
    r = client.delete("/me")
    assert r.status_code == 502 and "try again" in r.json()["detail"]
    assert service_key["auth"] == [] and not db.deleted_from("profiles") and not db.committed


def test_an_auth_failure_leaves_the_profile_alone(client, service_key, monkeypatch):
    async def boom(_user_id):
        raise account_service.AccountDeletionFailed("auth down")

    monkeypatch.setattr(account_service, "_delete_auth_user_via_api", boom)
    db = _Db()
    _with_db(db)
    assert client.delete("/me").status_code == 502
    assert not db.deleted_from("profiles") and not db.committed


def test_without_the_service_key_the_login_row_is_deleted_directly(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    db = _Db()
    _with_db(db)
    assert client.delete("/me").status_code == 204
    # no storage lookup (bites can't exist without the key), then auth.users, then profiles
    assert [s.split(" WHERE")[0] for s in db.statements] == ["DELETE FROM auth.users", "DELETE FROM profiles"]
    assert db.committed


def test_a_database_failure_is_a_clean_502(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    db = _Db(fail_on="auth.users")
    _with_db(db)
    assert client.delete("/me").status_code == 502
    assert db.rolled_back and not db.committed


def _admin_api(monkeypatch, status):
    from app.core.config import settings

    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["url"] = request.method, str(request.url)
        seen["auth"], seen["apikey"] = request.headers["authorization"], request.headers["apikey"]
        return httpx.Response(status, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        account_service.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    return seen


async def test_the_admin_api_call_is_the_documented_one(monkeypatch):
    seen = _admin_api(monkeypatch, 200)
    await account_service._delete_auth_user_via_api(ME)
    assert seen == {
        "method": "DELETE",
        "url": f"https://test.supabase.co/auth/v1/admin/users/{ME}",
        "auth": "Bearer service-key",
        "apikey": "service-key",
    }


async def test_an_already_deleted_login_counts_as_done(monkeypatch):
    """A retry after a lost response must not fail."""
    _admin_api(monkeypatch, 404)
    await account_service._delete_auth_user_via_api(ME)


async def test_an_admin_api_error_is_reported(monkeypatch):
    _admin_api(monkeypatch, 500)
    with pytest.raises(account_service.AccountDeletionFailed):
        await account_service._delete_auth_user_via_api(ME)
