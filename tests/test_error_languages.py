"""Every error message a person can read is answered in the app's language."""

import ast
import glob

import pytest
from fastapi.testclient import TestClient

from app.i18n import SUPPORTED, TABLES, errors, translate_detail
from app.main import app


def _constants(tree) -> dict[str, str]:
    return {
        n.targets[0].id: n.value.value
        for n in tree.body
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
        and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
    }


def _texts_in_code() -> set[str]:
    """Every fixed message the code raises as an HTTPException, or hands the
    rate limiter, or returns as a username rule."""
    found: set[str] = set()
    for path in glob.glob("app/**/*.py", recursive=True):
        tree = ast.parse(open(path).read())
        names = _constants(tree)

        def add(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
            elif isinstance(node, ast.Name) and node.id in names:
                found.add(names[node.id])
            elif isinstance(node, ast.IfExp):
                add(node.body)
                add(node.orelse)

        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if fn == "HTTPException":
                detail = next((k.value for k in n.keywords if k.arg == "detail"), None)
                if detail is None and len(n.args) > 1:
                    detail = n.args[1]
                if detail is not None:
                    add(detail)
            elif fn == "check" and len(n.args) == 3:  # rate_limit.check(name, user, message)
                add(n.args[2])
    return found


# Machine codes and notes for the developer, not for a person.
NOT_FOR_PEOPLE = {
    "ai_quota",
    "daily_scan_cap",
    "user_not_found",
    "Invalid or expired token",
    "Invalid user ID in token",
    "Invalid base64 image data",
    "No announcement with that id",
    "Web push is not switched on (PUSH_MODE=web with the VAPID keys), so nothing was sent.",
}


def test_every_message_in_the_code_has_all_five_translations():
    missing = sorted(m for m in _texts_in_code() - NOT_FOR_PEOPLE if m not in errors.ERRORS)
    assert not missing, f"add these to app/i18n/errors.py: {missing}"


def test_every_translation_has_five_languages_and_keeps_its_placeholders():
    for english, versions in {**errors.ERRORS, **errors.TEMPLATES}.items():
        assert len(versions) == len(errors.ORDER), english
        for lang, text in zip(errors.ORDER, versions):
            assert text.strip(), (lang, english)
            for mark in ("{date}", "{name}"):
                assert (mark in english) == (mark in text), (lang, english)


def test_friend_limit_and_collection_limit_numbers_match_the_code():
    from app.routers.collections import MAX_COLLECTIONS
    from app.services.friends_service import FRIEND_LIMIT, MESSAGES
    from app.services.username_service import MAX_LENGTH, MIN_LENGTH

    assert f"You can have up to {MAX_COLLECTIONS} collections." in errors.ERRORS
    assert all(m in errors.ERRORS for m in MESSAGES.values()), "a friend message lost its translation"
    assert f"Usernames need at least {MIN_LENGTH} characters." in errors.ERRORS
    assert f"Usernames can be at most {MAX_LENGTH} characters." in errors.ERRORS
    assert str(FRIEND_LIMIT) in " ".join(next(iter(m for m in errors.ERRORS if "limit of" in m)).split())


def test_translate_detail_listed_templated_and_unlisted():
    assert translate_detail("es", "That username is taken.") == "Ese nombre de usuario ya está en uso."
    assert translate_detail("en", "That username is taken.") == "That username is taken."
    assert translate_detail("de", "You can change your username again on 03 Dec 2026.") == (
        "Du kannst deinen Benutzernamen am 03 Dec 2026 wieder ändern."
    )
    assert "«Quinoa X»" in translate_detail("es", "We couldn't find nutrition for “Quinoa X”. Pick it from the search, or type its calories per 100 g.")
    assert translate_detail("fr", "ai_quota") == "ai_quota"
    assert translate_detail("fr", ["a list"]) == ["a list"]
    assert translate_detail("xx", "That username is taken.") == "That username is taken."


@pytest.mark.parametrize("lang", [c for c in SUPPORTED if c != "en"])
def test_tables_hold_the_error_messages(lang):
    assert TABLES[lang]["Not found"]


def test_an_error_answer_follows_accept_language():
    import uuid

    from app.core.database import get_db
    from app.core.security import get_current_user_id

    async def no_db():
        yield None

    app.dependency_overrides[get_current_user_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_db] = no_db
    try:
        client = TestClient(app)
        # A name rule answered as a normal reply...
        r = client.get("/username/check", params={"name": "1sam"}, headers={"Accept-Language": "es-MX,es;q=0.9"})
        assert r.json()["reason"] == "Los nombres de usuario deben empezar por una letra."
        assert client.get("/username/check", params={"name": "1sam"}).json()["reason"] == "Usernames must start with a letter."
        # ...and a raised error: status and shape unchanged, only the words differ.
        r = client.post("/username", json={"username": "1sam"}, headers={"Accept-Language": "de"})
        assert r.status_code == 422
        assert r.json()["detail"] == "Benutzernamen müssen mit einem Buchstaben beginnen."
        r = client.post("/username", json={"username": "1sam"})
        assert r.json()["detail"] == "Usernames must start with a letter."
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(get_db, None)
