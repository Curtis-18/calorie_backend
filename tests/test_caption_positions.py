import uuid
from types import SimpleNamespace

import pytest

from app.models.caption_pos import SnapCaptionPosition, StoryCaptionPosition
from app.services import caption_pos


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Db:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.added, self.executed = rows or [], fail, [], 0

    def begin_nested(self):
        return _Savepoint()

    def add(self, obj):
        if self.fail:
            raise RuntimeError("relation does not exist")
        self.added.append(obj)

    async def flush(self):
        pass

    async def execute(self, stmt):
        self.executed += 1
        if self.fail:
            raise RuntimeError("relation does not exist")
        return SimpleNamespace(all=lambda: self.rows)


def test_a_position_is_a_fraction_of_the_photo_and_only_means_something_with_a_caption():
    assert caption_pos.clean(0.5, "hi") == 0.5
    assert caption_pos.clean(0, "hi") == 0 and caption_pos.clean(1, "hi") == 1
    assert caption_pos.clean(0.123456, "hi") == 0.1235
    assert caption_pos.clean(0.5, None) is None and caption_pos.clean(0.5, "") is None
    assert caption_pos.clean(None, "hi") is None
    assert caption_pos.clean(-0.01, "hi") is None and caption_pos.clean(1.01, "hi") is None
    assert caption_pos.clean(float("nan"), "hi") is None


@pytest.mark.asyncio
async def test_saving_adds_one_row_for_the_right_item():
    db, snap, story = _Db(), uuid.uuid4(), uuid.uuid4()
    await caption_pos.save_snap(db, snap, 0.3, "hi")
    await caption_pos.save_story(db, story, 0.6, "hi")
    a, b = db.added
    assert isinstance(a, SnapCaptionPosition) and (a.snap_id, a.y) == (snap, 0.3)
    assert isinstance(b, StoryCaptionPosition) and (b.story_id, b.y) == (story, 0.6)


@pytest.mark.asyncio
async def test_nothing_is_saved_without_a_usable_position():
    db = _Db()
    await caption_pos.save_snap(db, uuid.uuid4(), None, "hi")
    await caption_pos.save_snap(db, uuid.uuid4(), 0.5, "")
    await caption_pos.save_story(db, uuid.uuid4(), 3, "hi")
    assert db.added == []


@pytest.mark.asyncio
async def test_a_missing_table_never_raises():
    db = _Db(fail=True)
    await caption_pos.save_snap(db, uuid.uuid4(), 0.3, "hi")  # swallowed
    assert await caption_pos.load(db, SnapCaptionPosition, SnapCaptionPosition.snap_id, [uuid.uuid4()]) == {}


@pytest.mark.asyncio
async def test_reading_only_asks_when_something_has_a_caption():
    a, b = uuid.uuid4(), uuid.uuid4()
    db = _Db(rows=[(a, 0.4)])
    plain = [SimpleNamespace(id=a, caption=None), SimpleNamespace(id=b, caption="")]
    assert await caption_pos.for_snaps(db, plain) == {} and db.executed == 0
    both = [SimpleNamespace(id=a, caption="hi"), SimpleNamespace(id=b, caption=None)]
    assert await caption_pos.for_snaps(db, both) == {a: 0.4} and db.executed == 1
    assert await caption_pos.for_stories(db, both) == {a: 0.4}
