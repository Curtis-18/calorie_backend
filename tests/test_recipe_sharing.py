"""Roadmap P3.4/P3.5: collections, Highlights, sharing a recipe with a friend."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.message import Message
from app.models.recipe import Collection, Recipe, RecipeEvent, RecipePin
from app.models.food_log import FoodLog

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")
BEA = uuid.UUID("00000000-0000-0000-0000-000000000003")
R1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
R2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
C1 = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
MSG = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


def recipe(rid=R1, owner=ME, title="Chicken rice", deleted=None, basis="ingredients"):
    return SimpleNamespace(
        id=rid, owner_id=owner, title=title, deleted_at=deleted, basis=basis, calories_per_serving=520,
        description=None, servings=2, visibility="private", region=None, tags=[], steps=[],
        protein_g=30.0, carbs_g=50.0, fat_g=10.0, nutrients=None,
    )


class R:
    """A query result that answers every way the routes read it."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.rows[0]

    def scalars(self):
        return self


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Db:
    """Answers a query by the table it reads from or writes to (the first
    registered match), so tests don't depend on the order of queries."""

    def __init__(self):
        self.store = {}            # (model, key) -> object
        self.answers = []          # (substring, rows or Exception)
        self.sql = []
        self.added = []
        self.deleted = []
        self.rolled_back = False
        self.commits = 0

    def answer(self, needle, rows=()):
        self.answers.append((needle, rows))
        return self

    def put(self, model, key, obj):
        self.store[(model, key)] = obj

    async def get(self, model, key):
        return self.store.get((model, key))

    async def execute(self, stmt):
        text = str(stmt)
        self.sql.append(text)
        for needle, rows in self.answers:
            if needle in text:
                if isinstance(rows, Exception):
                    raise rows
                return R(rows)
        return R([])

    def add(self, obj):
        self.added.append(obj)

    def add_all(self, objs):
        self.added.extend(objs)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rolled_back = True

    def begin_nested(self):
        return _Nested()

    def wrote(self, table):
        return [s for s in self.sql if s.startswith("INSERT INTO " + table)]

    def deleted_from(self, table):
        return [s for s in self.sql if s.startswith("DELETE FROM " + table)]


@pytest.fixture
def db(monkeypatch):
    from app.core.database import get_db
    from app.core.rate_limit import messages_sent
    from app.main import app

    messages_sent.reset()
    mem = Db()

    async def fake():
        yield mem

    app.dependency_overrides[get_db] = fake
    return mem


def friends(db, *others):
    """ME is friends with each of these people."""
    db.answer("FROM friendships", [(ME, o) for o in others])
    return db


SHARE = {"id": str(MSG)}


# ---- sharing ------------------------------------------------------------------

def test_sharing_sends_a_card_and_grants_that_one_friend_access(client, db):
    db.put(Recipe, R1, recipe())
    friends(db, SAM)
    r = client.post(f"/recipes/{R1}/share/{SAM}", json=SHARE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["attachment"] == {"kind": "recipe", "id": str(R1), "title": "Chicken rice", "calories": 520}
    assert "Chicken rice" in body["body"] and body["mine"] is True
    msg = next(o for o in db.added if isinstance(o, Message))
    assert (msg.sender_id, msg.recipient_id) == (ME, SAM)
    assert db.wrote("recipe_shares") and db.wrote("message_attachments")
    assert [e.kind for e in db.added if isinstance(e, RecipeEvent)] == ["share"]


def test_only_friends_can_be_sent_a_recipe(client, db):
    db.put(Recipe, R1, recipe())
    r = client.post(f"/recipes/{R1}/share/{BEA}", json=SHARE)
    assert r.status_code == 403
    assert not db.wrote("recipe_shares")


def test_you_cannot_share_someone_elses_recipe(client, db):
    db.put(Recipe, R1, recipe(owner=SAM))
    friends(db, SAM)
    assert client.post(f"/recipes/{R1}/share/{SAM}", json=SHARE).status_code == 404


def test_sharing_twice_with_the_same_id_sends_one_message(client, db):
    db.put(Recipe, R1, recipe())
    db.put(Message, MSG, SimpleNamespace(id=MSG, sender_id=ME, recipient_id=SAM, body="Sent you a recipe", created_at=datetime.now(timezone.utc), read_at=None))
    r = client.post(f"/recipes/{R1}/share/{SAM}", json=SHARE)
    assert r.status_code == 200 and not db.added


def test_a_message_id_used_by_someone_else_is_a_conflict(client, db):
    db.put(Recipe, R1, recipe())
    db.put(Message, MSG, SimpleNamespace(id=MSG, sender_id=SAM, recipient_id=BEA, body="x", created_at=datetime.now(timezone.utc), read_at=None))
    assert client.post(f"/recipes/{R1}/share/{SAM}", json=SHARE).status_code == 409


def test_missing_tables_mean_nothing_is_sent(client, db):
    db.put(Recipe, R1, recipe())
    friends(db, SAM)
    db.answer("INSERT INTO recipe_shares", RuntimeError("no such table"))
    r = client.post(f"/recipes/{R1}/share/{SAM}", json=SHARE)
    assert r.status_code == 503 and db.rolled_back


def test_unsharing_takes_the_access_back(client, db):
    db.put(Recipe, R1, recipe())
    assert client.delete(f"/recipes/{R1}/share/{SAM}").status_code == 204
    assert db.deleted_from("recipe_shares")
    db.put(Recipe, R2, recipe(R2, owner=SAM))
    assert client.delete(f"/recipes/{R2}/share/{SAM}").status_code == 404


# ---- a friend opening, saving and logging a shared recipe ----------------------

def test_a_friend_can_open_a_shared_recipe(client, db):
    db.put(Recipe, R1, recipe(owner=SAM))
    db.answer("FROM recipe_shares", [R1])
    friends(db, SAM)
    db.answer("FROM profiles", ["sam"])
    r = client.get(f"/recipes/{R1}")
    assert r.status_code == 200
    assert r.json()["mine"] is False and r.json()["owner_name"] == "sam"


def test_without_a_share_it_does_not_exist_for_them(client, db):
    db.put(Recipe, R1, recipe(owner=SAM))
    friends(db, SAM)
    assert client.get(f"/recipes/{R1}").status_code == 404


def test_a_share_stops_working_when_you_are_no_longer_friends(client, db):
    db.put(Recipe, R1, recipe(owner=SAM))
    db.answer("FROM recipe_shares", [R1])
    assert client.get(f"/recipes/{R1}").status_code == 404


def test_a_deleted_recipe_cannot_be_opened_even_by_its_owner(client, db):
    db.put(Recipe, R1, recipe(deleted=datetime.now(timezone.utc)))
    assert client.get(f"/recipes/{R1}").status_code == 404


def test_a_friend_can_log_a_shared_recipe_and_it_counts_as_their_log(client, db):
    db.put(Recipe, R1, recipe(owner=SAM))
    db.answer("FROM recipe_shares", [R1])
    friends(db, SAM)
    payload = {"id": "entry-1", "servings": 1, "meal_type": "dinner", "log_date": "2026-11-19", "timestamp": "2026-11-19T19:00:00"}
    r = client.post(f"/recipes/{R1}/log", json=payload)
    assert r.status_code == 201, r.text
    entry = next(o for o in db.added if isinstance(o, FoodLog))
    assert entry.user_id == ME and entry.calories == 520
    event = next(o for o in db.added if isinstance(o, RecipeEvent))
    assert (event.kind, event.actor_id, event.recipe_id) == ("log", ME, R1)


def test_saving_makes_the_saved_collection_the_first_time(client, db):
    db.put(Recipe, R1, recipe())
    assert client.post(f"/recipes/{R1}/save").status_code == 204
    saved = next(o for o in db.added if isinstance(o, Collection))
    assert (saved.name, saved.is_default, saved.owner_id) == ("Saved", True, ME)
    assert db.wrote("collection_items")
    assert [e.kind for e in db.added if isinstance(e, RecipeEvent)] == ["save"]


def test_saving_again_reuses_the_saved_collection(client, db):
    db.put(Recipe, R1, recipe())
    db.answer("FROM collections", [SimpleNamespace(id=C1, owner_id=ME, name="Saved", is_default=True)])
    assert client.post(f"/recipes/{R1}/save").status_code == 204
    assert not [o for o in db.added if isinstance(o, Collection)]


# ---- collections ---------------------------------------------------------------

def test_collections_list_shows_what_the_person_may_still_open(client, db):
    mine, theirs, gone, unshared = recipe(R1), recipe(R2, owner=SAM, title="Sam's stew"), recipe(uuid.uuid4(), deleted=None), recipe(uuid.uuid4(), owner=BEA, title="Not shared")
    when = datetime.now(timezone.utc)
    db.answer("FROM collections", [SimpleNamespace(id=C1, name="Saved", is_default=True)])
    db.answer("FROM collection_items", [(C1, mine.id, when), (C1, theirs.id, when), (C1, unshared.id, when), (C1, uuid.uuid4(), when)])
    db.answer("FROM recipes", [mine, theirs, unshared])
    db.answer("FROM recipe_shares", [(theirs.id,)])
    friends(db, SAM, BEA)
    out = client.get("/collections").json()
    assert [c["name"] for c in out] == ["Saved"]
    assert [i["title"] for i in out[0]["items"]] == ["Chicken rice", "Sam's stew"]
    assert [i["mine"] for i in out[0]["items"]] == [True, False]


def test_no_collections_yet_is_an_empty_list_and_missing_tables_too(client, db):
    assert client.get("/collections").json() == []
    db.answer("FROM collections", RuntimeError("no such table"))
    r = client.get("/collections")
    assert r.status_code == 200 and r.json() == []


def test_create_a_collection(client, db):
    db.answer("count(", [3])
    r = client.post("/collections", json={"id": str(C1), "name": "  Meal prep "})
    assert r.status_code == 201 and r.json()["name"] == "Meal prep"
    assert next(o for o in db.added if isinstance(o, Collection)).is_default is False


def test_a_retried_create_is_not_a_copy(client, db):
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=ME, name="Meal prep", is_default=False))
    r = client.post("/collections", json={"id": str(C1), "name": "Meal prep"})
    assert r.status_code == 200 and not db.added
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=SAM, name="x", is_default=False))
    assert client.post("/collections", json={"id": str(C1), "name": "Meal prep"}).status_code == 409


def test_collection_limits(client, db):
    db.answer("count(", [20])
    assert client.post("/collections", json={"id": str(C1), "name": "One more"}).status_code == 422
    assert client.post("/collections", json={"id": str(C1), "name": "   "}).status_code == 422
    assert client.post("/collections", json={"id": str(C1), "name": "x" * 41}).status_code == 422


def test_delete_a_collection(client, db):
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=ME, name="Meal prep", is_default=False))
    assert client.delete(f"/collections/{C1}").status_code == 204
    assert len(db.deleted) == 1
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=ME, name="Saved", is_default=True))
    assert client.delete(f"/collections/{C1}").status_code == 422
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=SAM, name="x", is_default=False))
    assert client.delete(f"/collections/{C1}").status_code == 404


def test_add_and_remove_a_recipe(client, db):
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=ME, name="Meal prep", is_default=False))
    db.put(Recipe, R1, recipe())
    assert client.post(f"/collections/{C1}/items", json={"recipe_id": str(R1)}).status_code == 204
    assert db.wrote("collection_items")
    assert client.delete(f"/collections/{C1}/items/{R1}").status_code == 204
    assert db.deleted_from("collection_items")


def test_you_cannot_add_a_recipe_you_cannot_open(client, db):
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=ME, name="Meal prep", is_default=False))
    db.put(Recipe, R2, recipe(R2, owner=SAM))
    assert client.post(f"/collections/{C1}/items", json={"recipe_id": str(R2)}).status_code == 404
    db.put(Collection, C1, SimpleNamespace(id=C1, owner_id=SAM, name="x", is_default=False))
    assert client.post(f"/collections/{C1}/items", json={"recipe_id": str(R1)}).status_code == 404


# ---- Highlights ----------------------------------------------------------------

def test_pin_up_to_six_of_your_own_recipes_in_order(client, db):
    db.answer("FROM recipes", [R2, R1])
    r = client.put("/highlights", json={"recipe_ids": [str(R1), str(R2)]})
    assert r.status_code == 200 and r.json()["recipe_ids"] == [str(R1), str(R2)]
    pins = [(o.recipe_id, o.position) for o in db.added if isinstance(o, RecipePin)]
    assert pins == [(R1, 0), (R2, 1)]
    assert db.deleted_from("recipe_pins")


def test_highlights_rules(client, db):
    ids = [str(uuid.uuid4()) for _ in range(7)]
    assert client.put("/highlights", json={"recipe_ids": ids}).status_code == 422
    assert client.put("/highlights", json={"recipe_ids": [str(R1), str(R1)]}).status_code == 422
    db.answer("FROM recipes", [R1])  # R2 is not mine, or is deleted
    assert client.put("/highlights", json={"recipe_ids": [str(R1), str(R2)]}).status_code == 422
    # clearing them all is allowed
    db2 = client.put("/highlights", json={"recipe_ids": []})
    assert db2.status_code == 200


def test_get_highlights_in_order_and_missing_tables_are_empty(client, db):
    db.answer("FROM recipes", [recipe(R1), recipe(R2, title="Stew")])
    assert [h["title"] for h in client.get("/highlights").json()] == ["Chicken rice", "Stew"]
    db.answers.clear()
    db.answer("FROM recipes", RuntimeError("no such table"))
    assert client.get("/highlights").json() == []


# ---- chat cards ------------------------------------------------------------------

async def test_attachments_are_read_for_a_thread_and_a_missing_table_is_harmless():
    from app.routers import messages

    db = Db().answer("FROM message_attachments", [(MSG, {"kind": "recipe", "id": str(R1), "title": "T", "calories": 1})])
    got = await messages.load_attachments(db, [MSG, uuid.uuid4()])
    assert got == {MSG: {"kind": "recipe", "id": str(R1), "title": "T", "calories": 1}}
    broken = Db().answer("FROM message_attachments", RuntimeError("no such table"))
    assert await messages.load_attachments(broken, [MSG]) == {}
    assert await messages.load_attachments(Db(), []) == {}


def test_a_message_carries_its_card_but_an_older_app_can_ignore_it():
    from app.routers.messages import _out

    m = SimpleNamespace(id=MSG, sender_id=ME, recipient_id=SAM, body="Sent you a recipe: T", created_at=datetime.now(timezone.utc), read_at=None)
    assert _out(m, ME, {"kind": "recipe"}).attachment == {"kind": "recipe"}
    assert _out(m, ME).attachment is None


def test_every_route_needs_a_login(anon_client):
    for method, path in [("get", "/collections"), ("post", "/collections"), ("get", "/highlights"), ("put", "/highlights"),
                         ("post", f"/recipes/{R1}/save"), ("post", f"/recipes/{R1}/share/{SAM}"), ("delete", f"/recipes/{R1}/share/{SAM}")]:
        assert getattr(anon_client, method)(path).status_code in (401, 403), path
