"""R8.3: friends-visible recipes, a friend's Highlights, who has my recipe,
recipe photos (cover and slides), editing ingredients, reporting a recipe."""

import base64
import io
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PIL import Image

from app.models.food_log import FoodLog
from app.models.recipe import Recipe, RecipeIngredient
from app.models.story import ContentReport
from app.services import storage_service
from test_recipe_sharing import BEA, ME, R1, R2, SAM, Db, db, friends, recipe  # noqa: F401  (db is a fixture)

PIN = "FROM recipes JOIN recipe_pins"


def friendly(rid=R1, owner=SAM, **kw):
    return recipe(rid, owner=owner, **kw) if False else _with(recipe(rid, owner=owner, **kw), visibility="friends")


def _with(obj, **kw):
    for k, v in kw.items():
        setattr(obj, k, v)
    return obj


def jpeg(size=(200, 100), exif=False) -> bytes:
    buf = io.BytesIO()
    im = Image.new("RGB", size, (200, 120, 40))
    if exif:
        tags = Image.Exif()
        tags[0x010F] = "SecretCameraMaker"
        im.save(buf, "JPEG", exif=tags)
    else:
        im.save(buf, "JPEG")
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---- who can open a recipe -----------------------------------------------------

def test_a_friend_can_open_a_friends_visible_recipe_without_a_share(client, db):
    db.put(Recipe, R1, friendly())
    friends(db, SAM)
    db.answer("FROM profiles", ["sam"])
    r = client.get(f"/recipes/{R1}")
    assert r.status_code == 200 and r.json()["mine"] is False and r.json()["visibility"] == "friends"


def test_a_stranger_cannot_open_it(client, db):
    db.put(Recipe, R1, friendly())
    assert client.get(f"/recipes/{R1}").status_code == 404


def test_unfriending_or_blocking_ends_access_at_once(client, db):
    # Blocking deletes the friendship, so "no longer friends" covers both.
    db.put(Recipe, R1, friendly())
    friends(db, BEA)
    assert client.get(f"/recipes/{R1}").status_code == 404
    assert client.post(f"/recipes/{R1}/save").status_code == 404
    assert client.get(f"/recipes/{R1}/media").status_code == 404


def test_a_deleted_friends_visible_recipe_is_gone(client, db):
    db.put(Recipe, R1, friendly(deleted=datetime.now(timezone.utc)))
    friends(db, SAM)
    assert client.get(f"/recipes/{R1}").status_code == 404


def test_a_private_recipe_stays_private_to_friends(client, db):
    db.put(Recipe, R1, recipe(owner=SAM))
    friends(db, SAM)
    assert client.get(f"/recipes/{R1}").status_code == 404


def test_a_friend_can_log_a_friends_visible_recipe(client, db):
    db.put(Recipe, R1, friendly())
    friends(db, SAM)
    payload = {"id": "e1", "servings": 1, "meal_type": "lunch", "log_date": "2026-11-21", "timestamp": "2026-11-21T12:00:00"}
    assert client.post(f"/recipes/{R1}/log", json=payload).status_code == 201
    assert next(o for o in db.added if isinstance(o, FoodLog)).user_id == ME


def test_the_owner_switches_visibility_and_nothing_else_is_allowed(client, db):
    r = recipe()
    db.put(Recipe, R1, r)
    assert client.patch(f"/recipes/{R1}", json={"visibility": "friends"}).status_code == 200
    assert r.visibility == "friends"
    assert client.patch(f"/recipes/{R1}", json={"visibility": "private"}).status_code == 200
    assert r.visibility == "private"
    assert client.patch(f"/recipes/{R1}", json={"visibility": "public"}).status_code == 422
    db.put(Recipe, R2, friendly(R2))
    assert client.patch(f"/recipes/{R2}", json={"visibility": "private"}).status_code == 404


def test_collections_show_friends_visible_recipes_without_a_share(client, db):
    theirs = friendly(R2)
    db.answer("FROM collections", [SimpleNamespace(id=uuid.uuid4(), name="Saved", is_default=True)])
    db.answer("FROM collection_items", [(db_c := uuid.uuid4(), theirs.id, datetime.now(timezone.utc))])
    db.answer("FROM recipes", [theirs])
    friends(db, SAM)
    out = client.get("/collections").json()
    assert out and out[0]["name"] == "Saved"


# ---- a friend's Highlights -----------------------------------------------------

def test_a_friends_highlights_only_include_what_i_may_open(client, db):
    visible, hidden, shared = friendly(R1), recipe(R2, owner=SAM, title="Private"), recipe(uuid.uuid4(), owner=SAM, title="Shared with me")
    friends(db, SAM)
    db.answer(PIN, [visible, hidden, shared])
    db.answer("FROM recipe_shares", [(shared.id,)])
    r = client.get(f"/users/{SAM}/highlights")
    assert r.status_code == 200
    assert [i["title"] for i in r.json()] == ["Chicken rice", "Shared with me"]


def test_only_friends_can_see_highlights_and_anyone_else_gets_not_found(client, db):
    friends(db, BEA)
    db.answer(PIN, [friendly()])
    assert client.get(f"/users/{SAM}/highlights").status_code == 404


def test_my_own_highlights_work_on_the_same_route(client, db):
    db.answer(PIN, [recipe()])
    r = client.get(f"/users/{ME}/highlights")
    assert r.status_code == 200 and len(r.json()) == 1


def test_missing_tables_mean_no_highlights(client, db):
    friends(db, SAM)
    db.answer(PIN, RuntimeError("no such table"))
    r = client.get(f"/users/{SAM}/highlights")
    assert r.status_code == 200 and r.json() == []


# ---- who has this recipe -------------------------------------------------------

def test_the_owner_sees_who_has_the_recipe(client, db):
    db.put(Recipe, R1, recipe())
    db.answer("FROM recipe_shares", [(SAM, "sam", datetime(2026, 11, 20, tzinfo=timezone.utc))])
    r = client.get(f"/recipes/{R1}/shares")
    assert r.status_code == 200
    assert r.json()[0]["username"] == "sam" and r.json()[0]["friend_id"] == str(SAM)


def test_only_the_owner_can_list_shares(client, db):
    db.put(Recipe, R1, friendly())
    friends(db, SAM)
    assert client.get(f"/recipes/{R1}/shares").status_code == 404


# ---- editing ingredients -------------------------------------------------------

OIL = {"name": "Olive oil", "grams": 20, "per_100g": {"calories": 880, "fat_g": 100}}
RICE = {"name": "Rice", "grams": 200, "per_100g": {"calories": 130, "carbs_g": 28, "protein_g": 2.7}}


def test_new_ingredients_replace_the_old_and_are_priced_again(client, db):
    r = recipe()
    r.servings = 2
    db.put(Recipe, R1, r)
    out = client.patch(f"/recipes/{R1}", json={"ingredients": [OIL, RICE]})
    assert out.status_code == 200, out.text
    # (20 g x 8.8) + (200 g x 1.3) = 176 + 260 = 436 kcal, over 2 servings
    assert r.calories_per_serving == 218
    assert db.deleted_from("recipe_ingredients")
    rows = [o for o in db.added if isinstance(o, RecipeIngredient)]
    assert [(x.position, x.name) for x in rows] == [(0, "Olive oil"), (1, "Rice")]
    assert r.basis == "manual"  # typed values are shown as estimated


def test_an_ingredient_that_cannot_be_priced_is_refused_and_nothing_changes(client, db, monkeypatch):
    from app.services import usda_service

    async def none(_name):
        return None

    monkeypatch.setattr(usda_service, "get_best_match", none)
    r = recipe()
    db.put(Recipe, R1, r)
    out = client.patch(f"/recipes/{R1}", json={"ingredients": [{"name": "Mystery", "grams": 50}]})
    assert out.status_code == 422 and "Mystery" in out.json()["detail"]
    assert not db.deleted_from("recipe_ingredients") and db.commits == 0


def test_an_empty_ingredient_list_is_refused(client, db):
    db.put(Recipe, R1, recipe())
    assert client.patch(f"/recipes/{R1}", json={"ingredients": []}).status_code == 422


def test_a_new_serving_count_alongside_new_ingredients_uses_the_new_count(client, db):
    r = recipe()
    db.put(Recipe, R1, r)
    assert client.patch(f"/recipes/{R1}", json={"ingredients": [RICE], "servings": 4}).status_code == 200
    assert r.calories_per_serving == 65 and float(r.servings) == 4


# ---- photos --------------------------------------------------------------------

@pytest.fixture
def storage(monkeypatch):
    calls = {"upload": [], "delete": [], "fail_upload": False}

    async def upload(path, data, mime):
        if calls["fail_upload"]:
            raise storage_service.StorageUnavailable("down")
        calls["upload"].append((path, data, mime))

    async def delete(paths):
        calls["delete"].append(list(paths))

    async def sign(paths, expires_in=3600):
        return {p: f"https://signed.example/{p}" for p in paths}

    monkeypatch.setattr(storage_service, "configured", lambda: True)
    monkeypatch.setattr(storage_service, "upload", upload)
    monkeypatch.setattr(storage_service, "delete", delete)
    monkeypatch.setattr(storage_service, "sign", sign)
    return calls


def put(client, position=0, image=None, **extra):
    return client.put(f"/recipes/{R1}/media/{position}", json={"image": b64(image or jpeg()), **extra})


def test_a_cover_is_saved_as_a_clean_jpeg_in_the_owners_folder(client, db, storage):
    db.put(Recipe, R1, recipe())
    r = put(client, 0, jpeg((3200, 2000), exif=True), caption="  Finished dish ")
    assert r.status_code == 200, r.text
    path, data, mime = storage["upload"][0]
    assert path.startswith(f"{ME}/recipe-{R1}-0-") and path.endswith(".jpg") and mime == "image/jpeg"
    saved = Image.open(io.BytesIO(data))
    assert max(saved.size) <= 1600           # shrunk
    assert len(saved.getexif()) == 0          # camera and location details gone
    assert r.json()["caption"] == "Finished dish" and r.json()["url"].endswith(path)
    assert db.wrote("recipe_media")


def test_a_png_is_converted(client, db, storage):
    db.put(Recipe, R1, recipe())
    buf = io.BytesIO()
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(buf, "PNG")
    assert put(client, 2, buf.getvalue()).status_code == 200
    assert storage["upload"][0][0].endswith(".jpg")


def test_a_broken_or_fake_image_is_refused_before_storage(client, db, storage):
    db.put(Recipe, R1, recipe())
    assert put(client, 0, b"\xff\xd8\xff not really a photo").status_code == 415
    assert put(client, 0, b"hello").status_code == 415
    assert not storage["upload"] and not db.wrote("recipe_media")


def test_only_positions_zero_to_five_exist(client, db, storage):
    db.put(Recipe, R1, recipe())
    assert put(client, 5).status_code == 200
    assert put(client, 6).status_code == 422
    assert client.put(f"/recipes/{R1}/media/-1", json={"image": b64(jpeg())}).status_code == 422


def test_only_the_owner_can_add_photos(client, db, storage):
    db.put(Recipe, R1, friendly())
    friends(db, SAM)
    assert put(client).status_code == 404
    assert not storage["upload"]


def test_photos_are_unavailable_without_storage(client, db, monkeypatch):
    monkeypatch.setattr(storage_service, "configured", lambda: False)
    db.put(Recipe, R1, recipe())
    assert put(client).status_code == 503


def test_replacing_a_photo_removes_the_old_file(client, db, storage):
    db.put(Recipe, R1, recipe())
    db.answer("FROM recipe_media", ["old/path.jpg"])
    assert put(client, 1).status_code == 200
    assert storage["delete"] == [["old/path.jpg"]]


def test_a_failed_upload_saves_nothing(client, db, storage):
    db.put(Recipe, R1, recipe())
    storage["fail_upload"] = True
    assert put(client).status_code == 502
    assert not db.wrote("recipe_media")


def test_if_the_database_write_fails_the_new_file_is_removed(client, db, storage):
    db.put(Recipe, R1, recipe())
    db.answer("INSERT INTO recipe_media", RuntimeError("boom"))
    assert put(client).status_code == 500 and db.rolled_back
    assert storage["delete"] == [[storage["upload"][0][0]]]


def test_without_the_migration_photos_answer_not_available(client, db, storage):
    db.put(Recipe, R1, recipe())
    db.answer("FROM recipe_media", RuntimeError("no such table"))
    assert put(client).status_code == 503 and not storage["upload"]


def test_removing_a_photo_deletes_the_row_and_the_file(client, db, storage):
    db.put(Recipe, R1, recipe())
    db.answer("FROM recipe_media", ["p/cover.jpg"])
    assert client.delete(f"/recipes/{R1}/media/0").status_code == 204
    assert db.deleted_from("recipe_media") and storage["delete"] == [["p/cover.jpg"]]


def test_removing_a_photo_that_is_not_there_is_harmless(client, db, storage):
    db.put(Recipe, R1, recipe())
    assert client.delete(f"/recipes/{R1}/media/3").status_code == 204
    assert not storage["delete"] and not db.deleted_from("recipe_media")


def test_deleting_a_recipe_removes_its_photos(client, db, storage):
    db.put(Recipe, R1, recipe())
    db.answer("FROM recipe_media", [(R1, 0, "p/cover.jpg", None), (R1, 1, "p/s1.jpg", "Step")])
    assert client.delete(f"/recipes/{R1}").status_code == 204
    assert storage["delete"] == [["p/cover.jpg", "p/s1.jpg"]] and db.deleted_from("recipe_media")


def test_a_recipe_comes_with_its_cover_and_slides(client, db, storage):
    db.put(Recipe, R1, recipe())
    db.answer("FROM recipe_media", [(R1, 0, "p/cover.jpg", None), (R1, 1, "p/s1.jpg", "Step one")])
    out = client.get(f"/recipes/{R1}").json()
    assert out["cover_url"] == "https://signed.example/p/cover.jpg"
    assert out["media"] == [{"position": 1, "caption": "Step one", "url": "https://signed.example/p/s1.jpg"}]


def test_the_recipe_list_carries_covers(client, db, storage):
    db.answer("FROM recipes", [recipe()])
    db.answer("FROM recipe_media", [(R1, 0, "p/cover.jpg", None)])
    assert client.get("/recipes").json()[0]["cover_url"] == "https://signed.example/p/cover.jpg"


def test_a_friend_sees_photos_of_a_friends_visible_recipe_and_a_stranger_does_not(client, db, storage):
    db.put(Recipe, R1, friendly())
    db.answer("FROM recipe_media", [(R1, 0, "p/cover.jpg", None)])
    assert client.get(f"/recipes/{R1}/media").status_code == 404
    friends(db, SAM)
    assert client.get(f"/recipes/{R1}/media").json()[0]["position"] == 0


def test_photo_problems_never_break_opening_a_recipe(client, db, storage):
    db.put(Recipe, R1, recipe())
    db.answer("FROM recipe_media", RuntimeError("no such table"))
    out = client.get(f"/recipes/{R1}")
    assert out.status_code == 200 and out.json()["cover_url"] is None and out.json()["media"] == []


# ---- reporting -----------------------------------------------------------------

def test_a_friend_can_report_a_recipe(client, db):
    db.put(Recipe, R1, friendly())
    friends(db, SAM)
    assert client.post(f"/recipes/{R1}/report", json={"reason": "spam"}).status_code == 204
    report = next(o for o in db.added if isinstance(o, ContentReport))
    assert (report.kind, report.reported_user_id, report.subject_id, report.reporter_id) == ("recipe", SAM, R1, ME)
    assert "spam" in report.reason


def test_you_cannot_report_your_own_or_one_you_cannot_see(client, db):
    db.put(Recipe, R1, recipe())
    assert client.post(f"/recipes/{R1}/report", json={}).status_code == 422
    db.put(Recipe, R2, recipe(R2, owner=SAM))
    assert client.post(f"/recipes/{R2}/report", json={}).status_code == 404


# ---- account deletion ----------------------------------------------------------

def test_deleting_an_account_removes_recipe_photos(client, monkeypatch):
    from app.core.database import get_db
    from app.main import app
    from app.services import account_service

    deleted = []

    async def delete(paths):
        deleted.append(list(paths))

    async def gone(_uid):
        return None

    class Res:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return self.rows

    class FakeDb:
        def __init__(self):
            self.sql = []

        def begin_nested(self):
            from test_recipe_sharing import _Nested
            return _Nested()

        async def execute(self, stmt):
            sql = " ".join(str(stmt).split())
            self.sql.append(sql)
            return Res([f"{ME}/recipe-a.jpg"] if "FROM recipe_media" in sql else [])

        async def commit(self):
            pass

        async def rollback(self):
            pass

    fake = FakeDb()

    async def fake_db():
        yield fake

    app.dependency_overrides[get_db] = fake_db
    monkeypatch.setattr(storage_service, "configured", lambda: True)
    monkeypatch.setattr(storage_service, "delete", delete)
    monkeypatch.setattr(account_service.settings, "supabase_service_role_key", "k", raising=False)
    monkeypatch.setattr(account_service, "_delete_auth_user_via_api", gone)
    assert client.delete("/me").status_code == 204
    assert deleted == [[f"{ME}/recipe-a.jpg"]]
