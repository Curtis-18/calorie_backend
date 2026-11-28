---
name: read-the-codebase
description: How to find your way around the NuStreak backend (calorie_backend) and Flutter app (calorie_app) before changing or explaining anything. Covers the start-of-session checks, which notes to trust, tracing a feature from a screen to the database and back, and finding the code behind a screenshot, error message, log line or status code. Also covers finding out why code is written the way it is, and checking that a note is still true. Use it at the start of every session, before any change, and before answering "how does X work".
---

# Reading the NuStreak codebase

**The rule behind everything here:** read before you write, and **trust the code over the notes.** The notes (`handover.md`, even `NEXT_STEPS.md`) were right when written, but some are now stale.

Example: the handover told agents to "fix" the Gemini scan schema's uppercase types. That had been tested live and works, and following the note would have broken photo scanning (AGENTS.md §9.4).

When a note and the code disagree:
- **the code wins**;
- a newer note beats an older one;
- say which you found.

Before you act on any fact, check it: a file, a test, a live call, or a question to the owner.

All paths below are relative to `/home/curtis/calorie_backend` unless they start with `../calorie_app`.

---

## 1. Start of a session (5 minutes, every time)

```bash
cd /home/curtis/calorie_backend && git status -sb && git log --oneline -5
cd /home/curtis/calorie_app     && git status -sb && git log --oneline -5
```
What to look for:
- `## master...origin/master` and `## main...origin/main` with **no "ahead N"**. "Ahead" means commits that were never pushed: find out why (bottom of `handover.md`) before doing anything else.
- **Modified files you didn't touch.** Someone left work half-done. Read the diff (`git diff <file>`) before working near it. Never discard it without the owner's OK.
- **Known leftovers, harmless:** logo images and `.zip` files in the backend folder (never commit them); `macos/Flutter/GeneratedPluginRegistrant.swift` in the app.

Then read, in this order:
1. `NEXT_STEPS.md`, "Where things stand", which gives the live commits and what's uncommitted.
2. The newest notes at the **bottom** of `handover.md`. Don't read the top first: its §0 table is from 3 Nov.
   ```bash
   grep -n '^## ' handover.md | tail -15     # the newest dated sections
   tail -n 60 handover.md
   ```
3. `REFERENCE.md` only when you need a fact (a setting, a table, an endpoint, a decision, what's unproven).

---

## 2. The picture to keep in your head

One request, from a tap to the database and back:

```
Screen / widget        ../calorie_app/lib/screens/*.dart, lib/widgets/*.dart   (what people see; text via context.tr)
  -> provider          ../calorie_app/lib/providers/*_provider.dart          (state; follows the signed-in user)
  -> service           ../calorie_app/lib/services/*_service.dart            (HTTP; _uri('/path') on ApiConfig.baseUrl)
  -> Vercel /api/...   ../calorie_app/vercel.json                            (forwards to Render; web app only)
  -> app/main.py       middleware: body limit, CORS, error handler that translates; include_router(...)
  -> app/routers/x.py  APIRouter(prefix="/x"); one function per route; login via Depends(get_current_user_id)
  -> app/services/x.py logic, pure where possible (that's where the tests aim)
  -> app/models/x.py   SQLAlchemy table  <-  migrations/YYYY-MM-DD_x.sql (the owner runs it by hand)
  <- app/schemas/x.py  Pydantic shape of the answer  ->  the app model's fromJson (../calorie_app/lib/models/)
Tests: tests/test_x.py (fake DB, no network)  and  ../calorie_app/test/x_test.dart
```

---

## 3. Tracing a feature end to end (worked example: logging a workout, "movement")

Do this for any feature before you change it. It takes 10 minutes, and it is how you find the other side of a change.

```bash
# App: who calls the backend for it?
grep -rn "_uri('/movement" ../calorie_app/lib/services      # -> lib/services/workouts_service.dart
grep -rln "WorkoutsService" ../calorie_app/lib/providers ../calorie_app/lib/screens
                                                            # -> workouts_provider.dart, workouts_screen.dart, coach_screen.dart
grep -n "fromJson" ../calorie_app/lib/services/workouts_service.dart   # -> MoveWeek.fromJson in lib/models/workouts.dart

# Backend: where does the path land?
grep -rn 'prefix="/movement"' app/routers                   # -> app/routers/movement.py
grep -n "^@router\." app/routers/movement.py                # every route in that file
grep -n "^from app" app/routers/movement.py                 # -> models.movement, schemas.movement, services.movement / movement_read / workouts

# Database: which table, made by which migration?
grep -n "__tablename__" app/models/movement.py
grep -ln "movement_logs" migrations/                        # -> 2026-11-26_movement.sql

# Tests on both sides
ls tests | grep -i movement                                 # -> test_movement.py
ls ../calorie_app/test | grep -iE "workout|move"
```

Then **compare the JSON contract field by field.** Take the backend response shape (`app/schemas/movement.py`, or the dict the route builds) and the app's `fromJson`. Note:
- every field the app reads, and whether it has a default when missing;
- every field the backend sends that the app ignores;
- any value the app turns into an enum. An unknown value must become `null` or a default, never a crash.

Most cross-repo bugs live in this comparison: a field renamed on one side, a new enum value, a number sent as a string.

**If you only remember one thing:** a change on one side means reading the other side's code for the same field.

---

## 4. Finding the code behind what the owner shows you

| The owner shows you... | Do this |
|---|---|
| **App text in a screenshot (English)** | The English text *is* the translation key, so it's in the widget: `grep -rn "Couldn't reach the server" ../calorie_app/lib` |
| **App text in another language** | Find the key first: `grep -n "phrase" ../calorie_app/lib/l10n/translations_*.dart` shows `'English key': 'translation'`. Then grep the English key in `lib/`. |
| **An error sentence that came from the server** | English is in the routers: `grep -rn "Couldn't save that" app/`. Translations are in `app/i18n/errors.py`. |
| **A Render log line** | Grep its first word in `app/`: `scan_done`, `gemini_call`, `request refused`, `web push refused`, `coach reply rejected`. Then read the code around it to see what each number means. |
| **A status code** (401, 409, 503...) | Find the route (REFERENCE.md §5), then `grep -n "HTTPException(503" app/routers/<file>.py`. Also check `app/main.py`'s handlers and `app/core/security.py`. Every 401 comes from there, or from FastAPI's `HTTPBearer` when the header is missing. |
| **"The app shows X but should show Y"** | Find the widget by its text, then go up to the provider (the state), then the service (the request), then the route. Find out where the wrong value is *made*, not only where it is shown. |
| **A setting name** | `app/core/config.py` (what it does), and `REFERENCE.md` §1 (where it's set, whether it is). |
| **A table name** | `grep -ln "<table>" migrations/ app/models/` |
| **An endpoint** | `REFERENCE.md` §5, or run `scripts/list_routes.py` (command in REFERENCE.md). |

Screenshots arrive as images or a `.zip`. Extract each into its own new folder and look at **every** image before concluding anything.

---

## 5. Finding out *why* code is the way it is (before "simplifying" it)

This codebase's comments describe the **incident that caused the code**, for example: "Bytes: compare_digest raises on a non-ASCII str, which was a 500". Code that looks odd is usually a fix. Before changing it:

```bash
git log --oneline -- app/routers/snaps.py | head      # the file's history; messages say what changed and why
git log -S "compare_digest" --oneline                 # the commit that added (or removed) a piece of text
git show <sha>                                        # read the whole change and its message
grep -n "compare_digest\|<keyword>" handover.md       # then read the dated section around each hit
grep -n -i "<keyword>" AGENTS.md                      # §9: was it tried and did it fail?
```

If the reason still isn't clear, **leave it alone and ask**. Don't remove a fix you don't understand.

---

## 6. Tests are the best documentation

Test names are plain sentences, so listing them tells you what the code promises:
```bash
grep -nE "^(async )?def test_" tests/test_movement.py
grep -nE "^\s*(test|testWidgets)\(" ../calorie_app/test/workouts_screen_test.dart
```
- Backend tests use **fake databases** (`_Db`, `_Result`, `_Nested`, copied from `tests/test_activity.py`). The fake's scripted answers show the order of the SQL statements a route runs.
- `tests/conftest.py` shows what is always faked: the login, Gemini, Open Food Facts and the usage counter.
- When a test and a note disagree, the test is the truth for *code*. But it may be faking the very thing that breaks in production (real SQL, real storage, real Gemini). See REFERENCE.md §2 for what has never run for real.

---

## 7. Checking a note before you act on it

| A note says... | Check it with |
|---|---|
| "X is built" | `grep` for its route or widget; run its tests. |
| "X is pushed / live" | `git log origin/master --oneline \| grep <sha>`. For the app, the deploy check in AGENTS.md §4.5. For a backend route: `curl -s -o /dev/null -w '%{http_code}\n' https://calorie-app-ug.vercel.app/api/<route>` gives 401 if it exists, 404 if not deployed. |
| "The owner ran migration X" | Only the owner can check: the `to_regclass` query in NEXT_STEPS step 2. |
| "Setting X is set on Render" | Only the owner can see it (REFERENCE.md §1.1). Say "not confirmed" until they do. |
| "Do Y to fix Z" (an old instruction) | Search for later sections about Z (`grep -n "Z" handover.md`; the highest line number is the newest), and read AGENTS.md §9. |

---

## 8. How much to read

- **The files you'll change:** read them whole.
- **Their neighbours** (the caller, the callee, the test): read the relevant functions.
- **`handover.md`:** never whole (2,000+ lines). Use headings and `grep`, then the dated section around the hit.
- **Generated or huge files** (`lib/l10n/translations_*.dart`, `build/`, `main.dart.js`): grep them, never read them whole.
- When a search would sweep many files, narrow it with a path (`app/routers`, `lib/providers`) instead of searching everything.

When you report what you found, give `file:line` references so the owner (or the next agent) can click straight to them.
