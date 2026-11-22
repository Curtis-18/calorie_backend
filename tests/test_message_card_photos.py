"""A recipe card in a chat thread carries the recipe's cover photo."""

import asyncio
import uuid

from app.routers import messages
from app.services import recipe_photos

RID = uuid.uuid4()
MID = uuid.uuid4()
CARD = {"kind": "recipe", "id": str(RID), "title": "Dal", "calories": 420}


def _run(coro):
    return asyncio.run(coro)


def test_a_recipe_card_gets_the_cover_link(monkeypatch):
    async def covers(db, ids):
        assert list(ids) == [RID]
        return {RID: "https://files/cover.jpg?sig=1"}

    monkeypatch.setattr(recipe_photos, "covers", covers)
    out = _run(messages._with_recipe_photos(None, {MID: dict(CARD)}))
    assert out[MID]["photo_url"] == "https://files/cover.jpg?sig=1"
    assert out[MID]["title"] == "Dal"


def test_no_cover_or_a_failure_leaves_the_card_as_it_was(monkeypatch):
    async def none(db, ids):
        return {}

    async def boom(db, ids):
        raise RuntimeError("storage down")

    monkeypatch.setattr(recipe_photos, "covers", none)
    assert _run(messages._with_recipe_photos(None, {MID: dict(CARD)})) == {MID: CARD}
    monkeypatch.setattr(recipe_photos, "covers", boom)
    assert _run(messages._with_recipe_photos(None, {MID: dict(CARD)})) == {MID: CARD}


def test_other_cards_and_bad_ids_are_not_looked_up(monkeypatch):
    async def covers(db, ids):
        raise AssertionError("nothing to look up")

    monkeypatch.setattr(recipe_photos, "covers", covers)
    other = {"kind": "something", "id": str(RID)}
    bad = {"kind": "recipe", "id": "not-a-uuid"}
    found = {MID: other, uuid.uuid4(): bad}
    assert _run(messages._with_recipe_photos(None, found)) == found
