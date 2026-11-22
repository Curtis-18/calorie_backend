"""Profile pictures, stories, and friends ordered by streak."""

import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")
BEA = uuid.UUID("00000000-0000-0000-0000-000000000003")
CAM = uuid.UUID("00000000-0000-0000-0000-000000000004")
NOW = datetime.now(timezone.utc)
JPEG = base64.b64encode(b"\xff\xd8\xff" + b"x" * 100).decode()


class _Result:
    def __init__(self, value=None, rows=None):
        self.value, self.rows = value, rows or []

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)

    def all(self):
        return self.rows


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Db:
    """Answers each statement by the table it touches, so a test only says
    what is in the database. A table given as a list answers in order; a
    table that isn't listed doesn't exist (as before the migration is run)."""

    def __init__(self, commit_error=None, **tables):
        self.tables, self.commit_error = tables, commit_error
        self.statements, self.added = [], []
        self.committed = self.rolled_back = False

    async def execute(self, stmt):
        sql = " ".join(str(stmt).split())
        self.statements.append(sql)
        table = re.search(r"(?:FROM|INTO|UPDATE) (?:public\.)?(\w+)", sql).group(1)
        if table not in self.tables:
            raise RuntimeError(f'relation "{table}" does not exist')
        answer = self.tables[table]
        if isinstance(answer, list):
            answer = answer.pop(0)
        return answer

    def ran(self, start: str) -> bool:
        return any(s.startswith(start) for s in self.statements)

    def begin_nested(self):
        return _Savepoint()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        if self.commit_error:
            raise self.commit_error
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    return db


@pytest.fixture
def storage(monkeypatch):
    from app.core.config import settings
    from app.services import avatars, storage_service

    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
    avatars.forget_links()
    calls = {"uploads": [], "deleted": [], "signed": []}

    async def upload(path, data, mime):
        calls["uploads"].append((path, mime))

    async def delete(paths):
        calls["deleted"].extend(paths)

    async def sign(paths, expires_in=3600):
        calls["signed"].append((list(paths), expires_in))
        return {p: f"https://signed/{p}" for p in paths}

    monkeypatch.setattr(storage_service, "upload", upload)
    monkeypatch.setattr(storage_service, "delete", delete)
    monkeypatch.setattr(storage_service, "sign", sign)
    yield calls
    avatars.forget_links()


def _friendship(a, b, status="accepted"):
    return SimpleNamespace(id=uuid.uuid4(), requester_id=a, addressee_id=b, status=status,
                           created_at=NOW, responded_at=NOW if status == "accepted" else None)


def _story(owner, minutes_ago=5, caption=None):
    sid = uuid.uuid4()
    made = NOW - timedelta(minutes=minutes_ago)
    return SimpleNamespace(id=sid, user_id=owner, storage_path=f"{owner}/story-{sid}.jpg", caption=caption,
                           created_at=made, expires_at=made + timedelta(hours=24))


def _view(story, viewer, reaction=None, minutes_ago=1):
    return SimpleNamespace(story_id=story.id, viewer_id=viewer, reaction=reaction,
                           viewed_at=NOW - timedelta(minutes=minutes_ago))


# --- profile pictures --------------------------------------------------------

def test_setting_a_picture_uploads_it_and_returns_a_link(client, storage):
    db = _with_db(_Db(profile_avatars=_Result(None)))
    r = client.post("/me/avatar", json={"image": JPEG})
    assert r.status_code == 200
    path, mime = storage["uploads"][0]
    assert path.startswith(f"{ME}/avatar-") and path.endswith(".jpg") and mime == "image/jpeg"
    assert r.json() == {"avatar_url": f"https://signed/{path}"}
    assert db.committed and db.ran("INSERT INTO profile_avatars") and storage["deleted"] == []


def test_replacing_a_picture_removes_the_old_file(client, storage):
    _with_db(_Db(profile_avatars=_Result(f"{ME}/avatar-old.jpg")))
    assert client.post("/me/avatar", json={"image": JPEG}).status_code == 200
    assert storage["deleted"] == [f"{ME}/avatar-old.jpg"]


def test_a_picture_that_cannot_be_saved_is_not_left_in_storage(client, storage):
    db = _with_db(_Db(profile_avatars=_Result(None), commit_error=RuntimeError("db down")))
    assert client.post("/me/avatar", json={"image": JPEG}).status_code == 500
    assert storage["deleted"] == [storage["uploads"][0][0]] and db.rolled_back


def test_bad_pictures_are_refused(client, storage):
    _with_db(_Db(profile_avatars=_Result(None)))
    not_an_image = base64.b64encode(b"hello there").decode()
    assert client.post("/me/avatar", json={"image": not_an_image}).status_code == 415
    assert client.post("/me/avatar", json={"image": "%%%"}).status_code == 400
    huge = base64.b64encode(b"\xff\xd8\xff" + b"x" * (1024 * 1024 + 10)).decode()
    assert client.post("/me/avatar", json={"image": huge}).status_code == 413
    assert storage["uploads"] == []


def test_pictures_wait_for_storage_and_for_the_migration(client, storage, monkeypatch):
    from app.core.config import settings

    _with_db(_Db())  # no profile_avatars table yet
    assert client.post("/me/avatar", json={"image": JPEG}).status_code == 503
    assert storage["uploads"] == []
    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    assert client.post("/me/avatar", json={"image": JPEG}).status_code == 503


def test_removing_a_picture(client, storage):
    path = f"{ME}/avatar-old.jpg"
    db = _with_db(_Db(profile_avatars=[_Result(path), _Result()]))
    assert client.delete("/me/avatar").status_code == 204
    assert db.ran("DELETE FROM profile_avatars") and storage["deleted"] == [path]
    # Nothing to remove is fine too.
    db = _with_db(_Db(profile_avatars=_Result(None)))
    assert client.delete("/me/avatar").status_code == 204 and not db.ran("DELETE")


def test_me_carries_the_picture(client, storage):
    path = f"{ME}/avatar-a.jpg"
    _with_db(_Db(profiles=_Result("sam"), profile_avatars=_Result(rows=[(ME, path)])))
    assert client.get("/me").json() == {"user_id": str(ME), "username": "sam", "avatar_url": f"https://signed/{path}"}


def test_me_still_answers_before_the_migration(client, storage):
    _with_db(_Db(profiles=_Result("sam")))
    assert client.get("/me").json() == {"user_id": str(ME), "username": "sam", "avatar_url": None}


def test_picture_links_are_reused_so_phones_can_cache_them(client, storage):
    path = f"{ME}/avatar-a.jpg"
    for _ in range(3):
        _with_db(_Db(profiles=_Result("sam"), profile_avatars=_Result(rows=[(ME, path)])))
        assert client.get("/me").json()["avatar_url"] == f"https://signed/{path}"
    assert storage["signed"] == [([path], 24 * 3600)]


def test_avatar_routes_need_a_login(anon_client):
    assert anon_client.post("/me/avatar", json={"image": JPEG}).status_code in (401, 403)
    assert anon_client.delete("/me/avatar").status_code in (401, 403)
    assert anon_client.get("/stories").status_code in (401, 403)
    assert anon_client.post("/stories", json={"id": str(uuid.uuid4()), "image": JPEG}).status_code in (401, 403)


# --- friends list ------------------------------------------------------------

def _days(*pairs_and_counts):
    """snap_days rows: for each (friend, n), both of us sent on each of the last n days."""
    from app.core.dates import resolve_today

    today = resolve_today(None)
    rows = []
    for friend, n in pairs_and_counts:
        for i in range(n):
            rows += [(ME, friend, today - timedelta(days=i)), (friend, ME, today - timedelta(days=i))]
    return today, rows


def test_friends_with_the_longest_streaks_come_first(client, storage):
    today, days = _days((BEA, 5), (CAM, 2))
    _with_db(_Db(
        friendships=_Result(rows=[_friendship(ME, SAM), _friendship(BEA, ME), _friendship(ME, CAM)]),
        profiles=_Result(rows=[(SAM, "aaron"), (BEA, "zoe"), (CAM, "mia")]),
        snap_days=_Result(rows=days),
        profile_avatars=_Result(rows=[(BEA, f"{BEA}/avatar-b.jpg")]),
    ))
    friends = client.get("/friends", params={"date": today.isoformat()}).json()["friends"]
    assert [(f["username"], f["streak"]) for f in friends] == [("zoe", 5), ("mia", 2), ("aaron", 0)]
    assert friends[0]["avatar_url"] == f"https://signed/{BEA}/avatar-b.jpg"
    assert friends[1]["avatar_url"] is None


def test_equal_streaks_fall_back_to_the_name(client, storage):
    today, days = _days((BEA, 3), (CAM, 3))
    _with_db(_Db(
        friendships=_Result(rows=[_friendship(ME, SAM), _friendship(BEA, ME), _friendship(ME, CAM)]),
        profiles=_Result(rows=[(SAM, "aaron"), (BEA, "zoe"), (CAM, "Mia")]),
        snap_days=_Result(rows=days),
    ))
    friends = client.get("/friends", params={"date": today.isoformat()}).json()["friends"]
    assert [f["username"] for f in friends] == ["Mia", "zoe", "aaron"]


def test_requests_show_pictures_too(client, storage):
    _with_db(_Db(
        friendships=_Result(rows=[_friendship(SAM, ME, "pending")]),
        profiles=_Result(rows=[(SAM, "sam")]),
        profile_avatars=_Result(rows=[(SAM, f"{SAM}/avatar-s.jpg")]),
    ))
    body = client.get("/friends").json()
    assert body["incoming"][0]["avatar_url"] == f"https://signed/{SAM}/avatar-s.jpg"


def test_reporting_a_profile_picture(client, storage):
    link = _friendship(ME, SAM)
    db = _with_db(_Db(friendships=_Result(link), profile_avatars=_Result(f"{SAM}/avatar-s.jpg")))
    assert client.post(f"/friends/{link.id}/report-photo", json={"reason": " rude "}).status_code == 204
    report = db.added[0]
    assert (report.reporter_id, report.reported_user_id, report.kind) == (ME, SAM, "avatar")
    assert report.reason == f"rude | photo: {SAM}/avatar-s.jpg" and db.committed
    # Not someone on your list: nothing to report.
    db = _with_db(_Db(friendships=_Result(None)))
    assert client.post(f"/friends/{uuid.uuid4()}/report-photo", json={}).status_code == 404 and not db.added


# --- stories -----------------------------------------------------------------

def _post(client, **kw):
    return client.post("/stories", json={"id": str(uuid.uuid4()), "image": JPEG, **kw})


def test_posting_a_story_uploads_and_saves_it(client, storage):
    db = _with_db(_Db(stories=[_Result(None), _Result(0)]))
    r = _post(client, caption=" lunch ")
    assert r.status_code == 200
    story = db.added[0]
    assert story.user_id == ME and story.caption == "lunch" and db.committed
    assert storage["uploads"] == [(f"{ME}/story-{story.id}.jpg", "image/jpeg")]
    lifetime = datetime.fromisoformat(r.json()["expires_at"]) - datetime.now(timezone.utc)
    assert timedelta(hours=23, minutes=59) < lifetime <= timedelta(hours=24)


def test_a_caption_position_is_saved_with_the_story(client, storage):
    from app.models.caption_pos import StoryCaptionPosition

    db = _with_db(_Db(stories=[_Result(None), _Result(0)]))
    assert _post(client, caption="lunch", caption_y=0.3).status_code == 200
    story, spot = db.added
    assert isinstance(spot, StoryCaptionPosition) and spot.story_id == story.id and spot.y == 0.3 and db.committed


def test_a_position_without_a_caption_or_off_the_photo_is_not_kept(client, storage):
    db = _with_db(_Db(stories=[_Result(None), _Result(0)]))
    assert _post(client, caption_y=0.4).status_code == 200  # nothing to place
    assert len(db.added) == 1
    assert _post(client, caption="x", caption_y=1.5).status_code == 422
    assert _post(client, caption="x", caption_y=-0.1).status_code == 422


def test_a_story_still_posts_if_the_position_cannot_be_saved(client, storage):
    class Broken(_Db):
        def begin_nested(self):
            raise RuntimeError('relation "story_caption_positions" does not exist')

    db = _with_db(Broken(stories=[_Result(None), _Result(0)]))
    r = _post(client, caption="lunch", caption_y=0.3)
    assert r.status_code == 200 and db.committed and len(db.added) == 1


def test_the_feed_carries_where_each_caption_sits(client, storage):
    mine = _story(ME, minutes_ago=30, caption="breakfast")
    sam_plain, sam_caption = _story(SAM, minutes_ago=50), _story(SAM, minutes_ago=10, caption="lunch")
    _with_db(_Db(
        friendships=_Result(rows=[(ME, SAM)]),
        stories=_Result(rows=[sam_plain, mine, sam_caption]),
        story_views=_Result(rows=[]),
        profiles=_Result(rows=[(SAM, "sam")]),
        profile_avatars=_Result(rows=[]),
        story_caption_positions=_Result(rows=[(mine.id, 0.2), (sam_caption.id, 0.75)]),
    ))
    body = client.get("/stories").json()
    assert body["mine"][0]["caption_y"] == 0.2
    assert [s["caption_y"] for s in body["friends"][0]["stories"]] == [None, 0.75]


def test_the_feed_does_not_ask_for_positions_when_nothing_has_a_caption(client, storage):
    plain = _story(SAM, minutes_ago=5)
    db = _with_db(_Db(
        friendships=_Result(rows=[(ME, SAM)]),
        stories=_Result(rows=[plain]),
        story_views=_Result(rows=[]),
        profiles=_Result(rows=[(SAM, "sam")]),
        profile_avatars=_Result(rows=[]),
    ))
    assert client.get("/stories").json()["friends"][0]["stories"][0]["caption_y"] is None
    assert not db.ran("SELECT story_caption_positions")


def test_reposting_the_same_id_is_a_no_op(client, storage):
    mine = _story(ME)
    db = _with_db(_Db(stories=_Result(mine)))
    r = client.post("/stories", json={"id": str(mine.id), "image": JPEG})
    assert r.status_code == 200 and r.json()["story_id"] == str(mine.id)
    assert storage["uploads"] == [] and not db.added
    # Someone else's id is refused rather than revealed.
    _with_db(_Db(stories=_Result(_story(SAM))))
    assert _post(client).status_code == 409


def test_a_story_has_a_limit_and_checks_the_photo(client, storage):
    _with_db(_Db(stories=[_Result(None), _Result(20)]))
    assert _post(client).status_code == 429
    _with_db(_Db(stories=[_Result(None)]))
    assert _post(client, image=base64.b64encode(b"not a photo").decode()).status_code == 415
    assert _post(client, caption="x" * 121).status_code == 422
    assert storage["uploads"] == []


def test_a_story_that_cannot_be_saved_is_not_left_in_storage(client, storage):
    db = _with_db(_Db(stories=[_Result(None), _Result(0)], commit_error=RuntimeError("db down")))
    assert _post(client).status_code == 500
    assert storage["deleted"] == [storage["uploads"][0][0]] and db.rolled_back


def test_stories_wait_for_storage_and_for_the_migration(client, storage, monkeypatch):
    from app.core.config import settings

    _with_db(_Db())  # no stories table yet
    assert _post(client).status_code == 503 and storage["uploads"] == []
    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    assert _post(client).status_code == 503
    assert client.get("/stories").status_code == 503


def test_the_feed_is_a_clean_503_before_the_migration(client, storage):
    _with_db(_Db(friendships=_Result(rows=[(ME, SAM)])))
    assert client.get("/stories").status_code == 503


def test_the_feed_groups_friends_and_shows_who_saw_mine(client, storage):
    mine = _story(ME, minutes_ago=30, caption="breakfast")
    sam_old, sam_new = _story(SAM, minutes_ago=50), _story(SAM, minutes_ago=10, caption="lunch")
    _with_db(_Db(
        friendships=_Result(rows=[(ME, SAM), (BEA, ME)]),
        stories=_Result(rows=[sam_old, mine, sam_new]),
        story_views=_Result(rows=[_view(sam_old, ME, "🔥"), _view(mine, BEA, "😋"), _view(mine, SAM, minutes_ago=9)]),
        profiles=_Result(rows=[(SAM, "sam"), (BEA, "bea")]),
        profile_avatars=_Result(rows=[(SAM, f"{SAM}/avatar-s.jpg")]),
    ))
    body = client.get("/stories").json()

    [own] = body["mine"]
    assert own["caption"] == "breakfast" and own["image_url"] == f"https://signed/{mine.storage_path}"
    # Newest viewer first.
    assert [(v["username"], v["reaction"]) for v in own["viewers"]] == [("bea", "😋"), ("sam", None)]
    assert own["viewers"][1]["avatar_url"] == f"https://signed/{SAM}/avatar-s.jpg"

    [group] = body["friends"]
    assert (group["username"], group["all_seen"]) == ("sam", False)
    assert group["avatar_url"] == f"https://signed/{SAM}/avatar-s.jpg"
    # Oldest first: the order they play in.
    assert [(s["caption"], s["viewed"], s["reaction"]) for s in group["stories"]] == [
        (None, True, "🔥"), ("lunch", False, None)]


def test_the_feed_puts_unseen_first_then_the_longest_streak(client, storage):
    today, days = _days((BEA, 4), (CAM, 9))
    sam, bea, cam = _story(SAM, 5), _story(BEA, 40), _story(CAM, 20)
    _with_db(_Db(
        friendships=_Result(rows=[(ME, SAM), (ME, BEA), (ME, CAM)]),
        stories=_Result(rows=[bea, cam, sam]),
        story_views=_Result(rows=[_view(cam, ME)]),
        profiles=_Result(rows=[(SAM, "sam"), (BEA, "bea"), (CAM, "cam")]),
        snap_days=_Result(rows=days),
        profile_avatars=_Result(rows=[]),
    ))
    groups = client.get("/stories", params={"date": today.isoformat()}).json()["friends"]
    # Cam has the longest streak but is already seen, so comes last.
    assert [(g["username"], g["streak"], g["all_seen"]) for g in groups] == [
        ("bea", 4, False), ("sam", 0, False), ("cam", 9, True)]


def test_someone_removed_no_longer_counts_as_a_viewer(client, storage):
    mine = _story(ME)
    _with_db(_Db(
        friendships=_Result(rows=[(ME, SAM)]),
        stories=_Result(rows=[mine]),
        story_views=_Result(rows=[_view(mine, SAM), _view(mine, BEA)]),  # Bea was a friend when she looked
        profiles=_Result(rows=[(SAM, "sam")]),
        profile_avatars=_Result(rows=[]),
    ))
    assert [v["username"] for v in client.get("/stories").json()["mine"][0]["viewers"]] == ["sam"]


def test_an_empty_feed(client, storage):
    _with_db(_Db(friendships=_Result(rows=[]), stories=_Result(rows=[])))
    assert client.get("/stories").json() == {"mine": [], "friends": []}


def test_viewing_and_reacting_to_a_friends_story(client, storage):
    story_id = uuid.uuid4()
    db = _with_db(_Db(stories=_Result(SAM), friendships=_Result(uuid.uuid4()), story_views=_Result()))
    assert client.post(f"/stories/{story_id}/view").status_code == 204
    assert db.ran("INSERT INTO story_views") and db.committed

    db = _with_db(_Db(stories=_Result(SAM), friendships=_Result(uuid.uuid4()), story_views=_Result(),
                      profiles=_Result(rows=[(ME, "me")])))
    assert client.post(f"/stories/{story_id}/react", json={"emoji": "🔥"}).status_code == 204
    assert any("ON CONFLICT" in s and "DO UPDATE" in s for s in db.statements)
    assert client.post(f"/stories/{story_id}/react", json={"emoji": "💩"}).status_code == 422


@pytest.mark.parametrize("owner, link", [(None, None), (SAM, None), (ME, uuid.uuid4())])
def test_only_a_friends_live_story_can_be_viewed(client, storage, owner, link):
    """Gone or expired, not a friend any more, or your own."""
    story_id = uuid.uuid4()
    for action, body in (("view", None), ("react", {"emoji": "🔥"}), ("report", {})):
        db = _with_db(_Db(stories=_Result(owner), friendships=_Result(link)))
        assert client.post(f"/stories/{story_id}/{action}", json=body).status_code == 404
        assert not db.committed and not db.added


def test_reporting_a_story(client, storage):
    story_id = uuid.uuid4()
    db = _with_db(_Db(stories=_Result(SAM), friendships=_Result(uuid.uuid4())))
    assert client.post(f"/stories/{story_id}/report", json={"reason": "not food"}).status_code == 204
    report = db.added[0]
    assert (report.reported_user_id, report.kind, report.subject_id, report.reason) == (SAM, "story", story_id, "not food")


def test_deleting_my_story_removes_the_photo(client, storage):
    path = f"{ME}/story-x.jpg"
    db = _with_db(_Db(stories=[_Result(path), _Result()]))
    assert client.delete(f"/stories/{uuid.uuid4()}").status_code == 204
    assert storage["deleted"] == [path] and db.ran("DELETE FROM stories") and db.committed
    # Not mine, or already gone.
    db = _with_db(_Db(stories=_Result(None)))
    assert client.delete(f"/stories/{uuid.uuid4()}").status_code == 404 and not db.ran("DELETE")


def test_deleting_an_account_removes_story_and_profile_photos(client, storage, monkeypatch):
    from app.services import account_service

    async def fake_auth_delete(user_id):
        pass

    monkeypatch.setattr(account_service, "_delete_auth_user_via_api", fake_auth_delete)
    _with_db(_Db(
        snaps=_Result(rows=[f"{ME}/a.jpg"]),
        stories=_Result(rows=[f"{ME}/story-b.jpg"]),
        profile_avatars=_Result(rows=[f"{ME}/avatar-c.jpg"]),
        profiles=_Result(),
    ))
    assert client.delete("/me").status_code == 204
    assert storage["deleted"] == [f"{ME}/a.jpg", f"{ME}/story-b.jpg", f"{ME}/avatar-c.jpg"]


def test_deleting_an_account_works_before_the_migration(client, storage, monkeypatch):
    from app.services import account_service

    async def fake_auth_delete(user_id):
        pass

    monkeypatch.setattr(account_service, "_delete_auth_user_via_api", fake_auth_delete)
    _with_db(_Db(snaps=_Result(rows=[f"{ME}/a.jpg"]), profiles=_Result()))
    assert client.delete("/me").status_code == 204
    assert storage["deleted"] == [f"{ME}/a.jpg"]


def test_reacting_to_a_story_adds_a_line_for_its_owner(client, storage, monkeypatch):
    calls = []

    async def fake(user_id, kind, actor_id, *, emoji=None, dedupe_key=None):
        calls.append((user_id, kind, actor_id, emoji))
        return True

    monkeypatch.setattr("app.routers.stories.record_activity", fake)
    story_id = uuid.uuid4()
    _with_db(_Db(stories=_Result(SAM), friendships=_Result(uuid.uuid4()), story_views=_Result(), profiles=_Result(rows=[(ME, "me")])))
    assert client.post(f"/stories/{story_id}/react", json={"emoji": "🔥"}).status_code == 204
    assert calls == [(SAM, "reaction", ME, "🔥")]
    # Only viewing a story adds nothing.
    calls.clear()
    _with_db(_Db(stories=_Result(SAM), friendships=_Result(uuid.uuid4()), story_views=_Result()))
    client.post(f"/stories/{story_id}/view")
    assert calls == []
