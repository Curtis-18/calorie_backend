import base64
import uuid


def test_health_and_root_are_open(client):
    assert client.get("/").json() == {"status": "ok"}


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
