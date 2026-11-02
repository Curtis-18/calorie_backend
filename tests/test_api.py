import base64
import uuid


def test_health_and_root_are_open(client):
    assert client.get("/").json() == {"status": "ok"}


def _preflight(cors_origins: str, origin: str):
    """A real OPTIONS round-trip through the middleware the app installs.

    This is the request the browser makes before every authenticated call, and
    the one that was answering "400 Disallowed CORS origin" in the Render log.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import cors_kwargs

    cors = Settings(
        _env_file=None,
        usda_api_key="x",
        gemini_api_key="x",
        supabase_url="https://x.supabase.co",
        database_url="postgresql+asyncpg://u:p@h/db",
        cors_origins=cors_origins,
    )
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **cors_kwargs(cors))

    @app.get("/targets")
    async def targets():
        return {"targets": []}

    with TestClient(app) as client:
        return client.options(
            "/targets",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )


def test_exact_origin_passes_preflight():
    r = _preflight("https://app.example.com", "https://app.example.com")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://app.example.com"


def test_vercel_preview_origin_passes_preflight():
    """Every preview deploy gets a new subdomain, so one wildcard has to cover them."""
    r = _preflight(
        "https://app.example.com,https://calorie-app-*.vercel.app",
        "https://calorie-app-a1b2c3-curtis.vercel.app",
    )
    assert r.status_code == 200
    assert (
        r.headers["access-control-allow-origin"]
        == "https://calorie-app-a1b2c3-curtis.vercel.app"
    )


def test_unlisted_origin_is_refused_with_400():
    """This is the response the client saw and reported as a network failure."""
    r = _preflight("http://localhost:3000", "https://calorie-app.vercel.app")
    assert r.status_code == 400
    assert "Disallowed CORS origin" in r.text


def test_spoofed_origin_under_an_allowed_wildcard_is_refused():
    r = _preflight(
        "https://calorie-app-*.vercel.app",
        "https://calorie-app-x.vercel.app.evil.test",
    )
    assert r.status_code == 400


def test_origin_pasted_with_a_trailing_slash_still_works():
    """The dashboard is full of copyable URLs, and every one of them has a slash."""
    r = _preflight("https://calorie-app-ug.vercel.app/", "https://calorie-app-ug.vercel.app")
    assert r.status_code == 200


def test_every_data_route_requires_auth(anon_client):
    client = anon_client
    """A missing bearer token must never reach business logic."""
    for method, path in [
        ("get", "/me"),
        ("get", "/targets"),
        ("get", "/insights"),
        ("get", "/foods/search?query=apple"),
        ("get", "/logs/today?date=2026-01-01"),
        ("delete", "/logs/some-id"),
        ("post", "/logs"),
        ("post", "/estimate-photo"),
        ("post", "/logs/analyze-photo"),
    ]:
        fn = getattr(client, method)
        r = fn(path, json={}) if method == "post" else fn(path)
        assert r.status_code == 401, f"{method.upper()} {path} returned {r.status_code}"


def test_estimate_photo_rejects_bad_base64(client):
    r = client.post("/estimate-photo", json={"image": "!!!not base64!!!"})
    assert r.status_code == 400
    assert "base64" in r.json()["detail"]


def test_estimate_photo_rejects_empty_image(client):
    r = client.post("/estimate-photo", json={"image": ""})
    assert r.status_code == 400


def test_estimate_photo_rejects_oversized_payload(client):
    """Unbounded base64 could pin a few hundred MB on a free instance."""
    r = client.post("/estimate-photo", json={"image": base64.b64encode(b"x" * 20_000_000).decode()})
    assert r.status_code == 413


def test_estimate_photo_requires_the_field(client):
    assert client.post("/estimate-photo", json={}).status_code == 422


def test_analyze_photo_upstream_failure_returns_502(client, monkeypatch):
    """A Gemini outage must be a clean 502, not an unhandled 500 that the
    browser reports as 'Failed to fetch' because it lacks CORS headers."""
    from app.routers import logs

    async def boom(*args, **kwargs):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(logs, "identify_foods", boom)
    r = client.post(
        "/logs/analyze-photo",
        files={"photo": ("meal.jpg", b"fake-bytes", "image/jpeg")},
    )
    assert r.status_code == 502


def test_food_search_empty_query_returns_empty_list(client):
    r = client.get("/foods/search?query=")
    assert r.status_code == 200
    assert r.json() == {"query": "", "results": []}


def test_openapi_does_not_leak_internals(client):
    """response models must not echo exception text back to callers."""
    schema = client.get("/openapi.json").text
    assert "gemini_api_key" not in schema
    assert "usda_api_key" not in schema


async def test_delete_log_compares_uuid_to_uuid(monkeypatch):
    """Regression: str(entry.user_id) != user_id was always True, so every delete 404'd."""
    from app.routers import logs

    owner = uuid.UUID("11111111-1111-1111-1111-111111111111")
    other = uuid.UUID("22222222-2222-2222-2222-222222222222")

    class Entry:
        user_id = owner

    class FakeDb:
        def __init__(self):
            self.deleted = False

        async def get(self, model, pk):
            return Entry()

        async def delete(self, obj):
            self.deleted = True

        async def commit(self):
            pass

    db = FakeDb()
    assert await logs.delete_log(log_id="abc", user_id=owner, db=db) is None
    assert db.deleted is True

    from fastapi import HTTPException

    try:
        await logs.delete_log(log_id="abc", user_id=other, db=FakeDb())
        raise AssertionError("expected 404 for a different owner")
    except HTTPException as exc:
        assert exc.status_code == 404


def test_food_log_schema_matches_the_client_payload():
    """The Flutter client posts exactly these keys."""
    from app.schemas.food_log import FoodLogIn

    entry = FoodLogIn(
        id="123_Grilled chicken",
        name="Grilled chicken",
        calories=250,
        protein_g=45.0,
        carbs_g=0.0,
        fat_g=6.0,
        meal_type="dinner",
        source="photo",
        timestamp="2026-09-29T18:00:00",
        log_date="2026-09-29",
    )
    assert entry.meal_type == "dinner"
    assert entry.source == "photo"


def test_food_log_rejects_bad_meal_type():
    from pydantic import ValidationError

    from app.schemas.food_log import FoodLogIn

    try:
        FoodLogIn(
            id="1",
            name="x",
            calories=10,
            meal_type="brunch",
            source="manual",
            timestamp="2026-09-29T18:00:00",
            log_date="2026-09-29",
        )
        raise AssertionError("expected validation error")
    except ValidationError:
        pass


def test_food_log_rejects_non_positive_calories():
    from pydantic import ValidationError

    from app.schemas.food_log import FoodLogIn

    try:
        FoodLogIn(
            id="1",
            name="x",
            calories=0,
            meal_type="snack",
            source="manual",
            timestamp="2026-09-29T18:00:00",
            log_date="2026-09-29",
        )
        raise AssertionError("expected validation error")
    except ValidationError:
        pass


class _FakeSession:
    def __init__(self, fail: bool):
        self.fail = fail

    async def execute(self, *_args, **_kwargs):
        if self.fail:
            raise ConnectionRefusedError("db down")


def _health_with_db(client, fail: bool):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield _FakeSession(fail)

    app.dependency_overrides[get_db] = fake_db
    return client.get("/health")


def test_health_reports_ok_when_db_reachable(client):
    r = _health_with_db(client, fail=False)
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_db_unreachable(client):
    # Render only restarts on a non-2xx status. A tuple return used to come
    # back as `200 [{...}, 503]`, hiding a dead pooler from the health check.
    r = _health_with_db(client, fail=True)
    assert r.status_code == 503
    assert r.json() == {
        "status": "degraded",
        "database": "unreachable",
        "detail": "ConnectionRefusedError",
    }


def _log_payload(log_id: str = "entry-1"):
    from app.schemas.food_log import FoodLogIn

    return FoodLogIn(
        id=log_id,
        name="Apple",
        calories=95,
        meal_type="snack",
        source="manual",
        timestamp="2026-11-02T08:00:00",
        log_date="2026-11-02",
    )


class _LogDb:
    """Fake session for create_log: commit raises `commit_error` if set, and
    the follow-up lookup returns `stored`."""

    def __init__(self, commit_error=None, stored=None):
        self.commit_error = commit_error
        self.stored = stored
        self.rolled_back = False

    def add(self, _entry):
        pass

    async def commit(self):
        if self.commit_error:
            raise self.commit_error

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, _entry):
        pass

    async def execute(self, _stmt):
        stored = self.stored

        class _Result:
            def scalar_one_or_none(self):
                return stored

        return _Result()


def _integrity_error():
    from sqlalchemy.exc import IntegrityError

    return IntegrityError("INSERT", {}, Exception("duplicate key"))


def _post_log(client, db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    return client.post("/logs", json=_log_payload().model_dump(mode="json"))


def test_create_log_http_201_on_first_save(client):
    r = _post_log(client, _LogDb())
    assert r.status_code == 201
    assert r.json()["id"] == "entry-1"


def test_create_log_http_200_on_retry_of_own_entry(client):
    # The client accepts 200 or 201, so a retry after a lost response reads
    # as saved instead of "Failed to save entry".
    import uuid
    from datetime import date, datetime

    from app.models.food_log import FoodLog

    # matches the user id the `client` fixture authenticates as
    owner = uuid.UUID("00000000-0000-0000-0000-000000000001")
    stored = FoodLog(
        id="entry-1", user_id=owner, name="Apple", calories=95, protein_g=0,
        carbs_g=0, fat_g=0, meal_type="snack", source="manual",
        timestamp=datetime(2026, 11, 2, 8), log_date=date(2026, 11, 2),
    )
    r = _post_log(client, _LogDb(commit_error=_integrity_error(), stored=stored))
    assert r.status_code == 200
    assert r.json()["id"] == "entry-1"


async def test_create_log_retry_of_own_entry_is_idempotent():
    # A retry after a dropped response must read as saved, not as an error.
    import uuid
    from types import SimpleNamespace

    from fastapi import Response

    from app.routers import logs

    owner = uuid.uuid4()
    stored = SimpleNamespace(id="entry-1", user_id=owner)
    db = _LogDb(commit_error=_integrity_error(), stored=stored)
    response = Response()

    result = await logs.create_log(data=_log_payload(), response=response, user_id=owner, db=db)

    assert result is stored
    assert response.status_code == 200
    assert db.rolled_back


async def test_create_log_id_owned_by_someone_else_is_409():
    import uuid
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException, Response

    from app.routers import logs

    stored = SimpleNamespace(id="entry-1", user_id=uuid.uuid4())
    db = _LogDb(commit_error=_integrity_error(), stored=stored)

    with pytest.raises(HTTPException) as exc:
        await logs.create_log(data=_log_payload(), response=Response(), user_id=uuid.uuid4(), db=db)
    assert exc.value.status_code == 409


async def test_create_log_non_duplicate_integrity_error_is_500_not_409():
    # e.g. a foreign key failure: no row with this id exists, so it must not
    # be reported as "already exists".
    import uuid

    import pytest
    from fastapi import HTTPException, Response

    from app.routers import logs

    db = _LogDb(commit_error=_integrity_error(), stored=None)

    with pytest.raises(HTTPException) as exc:
        await logs.create_log(data=_log_payload(), response=Response(), user_id=uuid.uuid4(), db=db)
    assert exc.value.status_code == 500


async def test_create_log_unexpected_db_error_is_500_not_409():
    import uuid

    import pytest
    from fastapi import HTTPException, Response

    from app.routers import logs

    db = _LogDb(commit_error=ConnectionResetError("pooler dropped"))

    with pytest.raises(HTTPException) as exc:
        await logs.create_log(data=_log_payload(), response=Response(), user_id=uuid.uuid4(), db=db)
    assert exc.value.status_code == 500
    assert db.rolled_back


def test_sniff_image_mime_detects_common_formats():
    from app.routers.photo_estimation import sniff_image_mime

    assert sniff_image_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff_image_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert sniff_image_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_image_mime(b"\x00\x00\x00\x18ftypheic\x00") == "image/heic"
    assert sniff_image_mime(b"\x00\x00\x00\x18ftypmif1\x00") == "image/heif"
    assert sniff_image_mime(b"unknown") == "image/jpeg"


def test_estimate_photo_sends_the_real_mime_type(client, monkeypatch):
    import base64

    from app.routers import photo_estimation

    seen = {}

    async def fake_identify(image_bytes, mime_type):
        seen["mime"] = mime_type
        return [{"name": "Rice", "estimated_grams": 150.0}]

    monkeypatch.setattr(photo_estimation, "identify_foods", fake_identify)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    r = client.post("/estimate-photo", json={"image": base64.b64encode(png).decode()})

    assert r.status_code == 200
    assert r.json() == [{"name": "Rice", "estimated_grams": 150.0}]
    assert seen["mime"] == "image/png"


def _usda_payload():
    return {
        "foods": [
            {
                "fdcId": 171688,
                "description": "Apples, raw, with skin",
                "dataType": "Foundation",
                "foodNutrients": [
                    {"nutrientName": "Energy", "unitName": "KCAL", "value": 52},
                    {"nutrientName": "Protein", "unitName": "G", "value": 0.26},
                    {"nutrientName": "Total lipid (fat)", "unitName": "G", "value": 0.17},
                    {"nutrientName": "Carbohydrate, by difference", "unitName": "G", "value": 13.8},
                ],
            },
            {"fdcId": 2, "description": "", "foodNutrients": []},  # dropped: no description
        ]
    }


def _mock_usda(monkeypatch, handler):
    import httpx

    from app.services import usda_service

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(usda_service.httpx, "AsyncClient", fake_client)


def test_food_search_returns_mapped_results(client, monkeypatch):
    # Regression: results used to fail model validation (nutrient keys didn't
    # match field names), so every non-empty search was a 500.
    import httpx

    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_usda_payload())

    _mock_usda(monkeypatch, handler)
    r = client.get("/foods/search", params={"query": "apple", "page_size": 20})

    assert r.status_code == 200
    assert r.json() == {
        "query": "apple",
        "results": [
            {
                "fdc_id": 171688,
                "description": "Apples, raw, with skin",
                "data_type": "Foundation",
                "calories_per_100g": 52.0,
                "protein_g_per_100g": 0.26,
                "carbs_g_per_100g": 13.8,
                "fat_g_per_100g": 0.17,
            }
        ],
    }
    assert seen["params"]["pageSize"] == "20"
    assert seen["params"]["query"] == "apple"


def test_food_search_usda_failure_is_502_not_500(client, monkeypatch):
    import httpx

    _mock_usda(monkeypatch, lambda request: httpx.Response(503, text="down"))
    r = client.get("/foods/search", params={"query": "apple"})
    assert r.status_code == 502


def test_food_search_rejects_bad_page_size(client):
    assert client.get("/foods/search", params={"query": "a", "page_size": 0}).status_code == 422
    assert client.get("/foods/search", params={"query": "a", "page_size": 51}).status_code == 422
