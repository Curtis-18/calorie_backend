---
name: what-to-look-out-for
description: The checklist of things that have broken NuStreak before, or that the owner and client insist on. Covers the client's safety rules (no kcal on shared posts, banned words), old-app/new-backend compatibility, migrations, status codes, per-user data, the five translations, web-browser limits, colours, tests, secrets, and how to report. Each item has a search command to run on your diff. Use it before every commit in calorie_backend or calorie_app, when reviewing any change, and when reading existing code for bugs.
---

# What to look out for (run this before every commit)

Each item below either broke something in this project or is a rule the client set. Most items come with a command that checks your **diff**, so you don't rely on memory. The full story of each is in AGENTS.md §9 ("TRIED AND FAILED").

Commands assume you're in the repo you changed. Paths starting with `app/` or `tests/` are the backend; `lib/` and `test/` are the app.

---

## 0. Read your own diff first

```bash
git status -s                       # every file you changed or created; anything unexpected?
git diff --stat                     # a file with hundreds of changed lines you didn't write = a formatter ran. STOP.
git diff                            # read every line. Is each one needed for what the owner asked?
git ls-files --others --exclude-standard   # new files (git diff doesn't show them; check them by hand)
```
- **Did you do only what was asked?** Put extra ideas in your reply as a list; don't build them (AGENTS.md §2.7).
- **Never run `dart format`** (or any formatter) on existing files. If one ran, ask the owner before undoing anything.
- Commit files **by name**, never `git add -A` or `git add .`. The backend folder holds logo images, zips and `handover.md`, which must not be committed. (`AGENTS.md`, `NEXT_STEPS.md`, `REFERENCE.md`, `scripts/list_routes.py` and these skills **are** committed since 28 Nov 2026; the repo is public, so no secrets or emails in them.)

---

## 1. The client's safety rules (these are never negotiable)

**Banned words in anything the app or server says** (copy, prompts, push text, error messages):
```bash
git diff -U0 | grep '^+' | grep -v '^+++' | grep -inE "burn|\bearn|cheat|guilt|punish|make up for|detox|cleanse|reward|\btreat|\bdiet\b|bad food|good food|lazy|miss you"
```
Every hit needs a reason. "Calories burned" on the Workouts card is the agreed wording; "burn it off" is never allowed. Run the same `grep -inE` on new files too.

**No calorie numbers on anything shared** (bites, stories, chat stickers, share cards, recipe cards in chat). Protein grams, meal labels and streak days are fine.
```bash
git diff --name-only | grep -iE "snap|stor(y|ies)|share|sticker|chat|message|bite"      # touched a shared surface?
git diff -U0 -- $(git diff --name-only | grep -iE "snap|stor|share|sticker|chat|message|bite") | grep '^+' | grep -iE "kcal|calorie"
```

**Other safety rules:**
- Never reward eating less, never praise a day below the floor (1200 women / 1500 men).
- An unlogged day is "unknown", not "ate nothing".
- Never size exercise to a meal or call it payback. Never add burned calories to the target unless the person opted in (D11: off by default, at most 50%, at most 500 kcal a day).
- Push text never shames: `tests/test_notifications.py` bans "calorie", "kcal", "weight", "missed", "failed", "lazy", "miss you". Message text never goes into a push.
- Health claims ("helps PCOS", "boosts dopamine") are never allowed. Health content waits for the dietitian (D19).
- No follower counts, like counts or leaderboards. Private by default.

**There is no single banned-word test.** Each feature's test has its own list:
- `test/recipe_goal_test.dart:72` (copy this regex for new app text);
- `test/mood_picks_test.dart`, `test/whats_new_test.dart`, `test/onboarding_test.dart`;
- `tests/test_patterns.py`, `tests/test_week_budget.py`, `tests/test_notifications.py`.

**A feature with new words needs its own banned-word check in its test.**

**The owner's product rules:**
- The **camera is the main action**: big gradient camera button, smaller search button. Never hide it behind "+".
- Usernames are shown **without @**.
- **Text a person typed is never translated** (captions, messages, recipe titles, usernames): `grep -n "tr(.*caption\|tr(.*message\|tr(.*title\|tr(.*username" <changed dart files>`.

---

## 2. Compatibility: old app + new backend, new app + old backend

People keep old tabs open, and the owner runs migrations late. Both sides must survive the other being older.

- **Never remove or rename a JSON field the app reads.** Before deleting a field, check the app: `grep -rn "'field_name'" ../calorie_app/lib`. (`tips: []` stays in `/insights` forever for this reason.)
- **New response fields are optional in the app**: `fromJson` gives a default when the field is missing (`json['x'] as int? ?? 0`). Never make the app need a new backend field (AGENTS.md §3.15).
- **Unknown values parse to `null` or a default**, never `byName()` on server data without a fallback. Exception: `food_logs.source` is parsed with `FoodSource.values.byName`, so **never add a value to it** (§3.13).
- **New data goes in a new table**, read and written inside `async with db.begin_nested():` with an `except` that treats a missing table as empty (`app/services/caption_pos.py`). Check your migration:
  ```bash
  git diff -- migrations | grep -iE "alter table .* add column|not null"   # a new column on an existing table = STOP (AGENTS.md §3.14)
  ```
- Migration file: idempotent (`if not exists`), `enable row level security`, a check query at the end, named after the last file in `migrations/` (`2026-11-29_...`).
- **Push order:** the owner runs the migration, then the backend goes out, then the app. Say this order in your reply.

---

## 3. Backend: what breaks here

| Check | Why | How to look |
|---|---|---|
| **The right status code** | 401 logs people out (the app signs out after two). 401 is only for a bad or expired token. Our own failures are **503**. Someone else's id is **409** (or 404 to hide it). Bad input is **422**. Never answer a value that *means something else* on failure (`username: null` sent people to the picker). | Read every `HTTPException(` and every `except` in your diff. |
| **No tuple returns** | `return {...}, 503` went out as a 200. | `grep -rnE "return \{.*\}, [0-9]{3}" app/` → nothing |
| **Idempotent creates** | The app chooses the id; a repeat by the same person returns the stored row (200); another person's id is 409. A retry must never make a second row. | Read the route: does it look up `data.id` first? |
| **Rollback inside loops over people** | One failed statement aborted the whole transaction for everyone after it. | `except` inside a per-person loop must `await db.rollback()`. |
| **Numbers are bounded** | Infinity was stored and broke every read of that day; 1e300 kg gave a 500. | Every new number field has `ge=`/`le=` and `allow_inf_nan=False`. |
| **Dates and times** | "Today" comes from the device through `resolve_today(date)`. Timestamps are stored as naive UTC (a "...Z" value gave a 500). Dates in text go through `app/i18n/dates.py`, never ISO. | `grep -n "date.today()\|datetime.now()" <your files>`: the server's clock is a different day for many users. |
| **Text comparisons of secrets** | `compare_digest` on non-ASCII text raised a 500. | `grep -rn "compare_digest" app/ \| grep -v encode` → only comments |
| **Keys in headers, never URLs** | Keys ended up in Render's logs. | `grep -rnE "\?key=\|api_key=" app/` → only the two comments |
| **Logs never hold personal values** | Food names, notes, messages, emails, usernames must never be logged. Log field names, statuses and counts. | `git diff -U0 -- app \| grep '^+' \| grep -E "log\.(info\|warning\|error\|exception)\("`, then read each one. |
| **Friendship checked on every social action** | Blocked people could still react and notify. | View/react/send routes check a *current* friendship. |
| **Gemini only through `gemini_client.generate_content`** | Shared daily budget, breaker, fallback model. | `grep -rln "generativelanguage\|gemini_base_url" app/` → only `gemini_client.py`, `config.py` |
| **AI cost** | Insights called Gemini after every logged food and used up the quota. Only 503 is retried. A new AI feature needs a rate limit (`app/core/rate_limit.py`) plus `require_feature` / `record_usage`. Cached AI text is regenerated when its inputs change (`targets.updated_at`). | Read the new call site. |
| **Numbers in prompts and text are rounded** | `43.090999999999994g` reached users. | `round(...)` / format before any f-string that people or Gemini see. |
| **Database connection settings** | `app/core/database.py` must stay safe behind Supabase's transaction pooler: no statement caches, no named statements, NullPool unless `DB_POOL=queue`. Named statements piled up on the pooler's connections in the 28 Nov 2026 load test. | `git diff -- app/core/database.py`: any change there needs the PgBouncer load test again (handover "28 Nov 2026 (third round)") and `tests/test_database_pool.py`. |
| **Wiring** | A router that isn't included is a 404; a model not imported breaks relationships. | `grep -n "include_router" app/main.py`, and the long `from app.models import` line in `app/main.py`. |
| **CORS methods** | `allow_methods` in `app/main.py` allows GET, POST, PUT, PATCH, DELETE (PUT added 28 Nov 2026, `d7cc3a6`). A new method needs adding there with a test (`tests/test_api.py`), or a browser refuses it. | Use POST (the house habit). |
| **New error sentences translated** | `tests/test_error_languages.py` fails otherwise. | Add the sentence to `app/i18n/errors.py` in all five languages; machine codes go in `NOT_FOR_PEOPLE`. |
| **New server text translated** | `tests/test_languages.py` fails otherwise. | The same English key in `app/i18n/{es,fr,de,pt,it}.py`, with identical `{placeholders}`. |
| **New reportable content** | Reporting messages failed in production. | Widen `content_reports_kind_check` in the migration. |
| **New stored photos** | Storage doesn't cascade on account deletion. | Add the path to `app/services/account_service.py` and its test. |

---

## 4. App: what breaks here

| Check | Why | How to look |
|---|---|---|
| **One backend address** | Some networks can't resolve onrender.com (26 Nov outage). | `grep -rln "onrender.com" lib/` → only `lib/config/api_config.dart` |
| **Per-user state** | User B saw user A's Insights; cache keys without the user id leaked data on shared devices. | A new provider follows `UserCache.currentUserId` / `userIdChanges`, clears on sign-out, uses a `_generation` counter. Cache keys contain the uid (`food_log:<uid>:<date>`). Copy `lib/providers/activity_provider.dart`. |
| **Saves one at a time** | `Future.wait` over saves showed one error for the whole meal while some items had saved, and the retry duplicated them. | `grep -rn "Future.wait" lib/providers lib/services`: today only **reads** use it (`house_recipes_provider`, `budget_provider`, `food_search_service`); a save inside it is a bug. |
| **Retries** | Only on timeout or 5xx, never on 4xx; the server treats a repeated id as already saved. | Read the new retry code. |
| **"Today"** | After midnight the app counted yesterday's food under the new date. Past days are read-only. | No `DateTime.now()` stored in a field at screen creation; use the provider's day. |
| **Server words never shown raw** | Map status codes to the app's own translated messages. | `jsonDecode(utf8.decode(r.bodyBytes))` (accents break otherwise); `languageClient()` when the answer has words. |
| **Browser limits (it's a web app)** | Safari only asks for a permission *inside* the tap (not after an `await`). The camera can't open by itself. Web Share must run inside the tap, so render the image first. The push worker lives in `web/push/`, not the site root. | Read any new tap handler. |
| **No new packages unless used and agreed** | Unused packages added store permission requirements. | `git diff pubspec.yaml` |
| **Design system** | Cupertino and our widgets (`AppButton`, `AppCard`, `AppDialog`, `AppField`, `PageHeader`...), no Material widgets. Our icons (`lib/widgets/move_icons.dart`), no emoji. | Read new widgets. |
| **Colours** | Lime/aqua text on white is unreadable: use `TrackerColors.ink(...)`. On gradients use `onAccent`. Fire uses `flameStart`/`flameEnd`. Colours are getters, never `const`. Custom painters repaint on theme change. | Read new colour uses; `test/theme_mode_test.dart` checks contrast. |
| **Characters and widths** | "−" (U+2212) shows as a box: use "–". German labels overflow: let text shrink or wrap. Respect reduce-motion. | `grep -rln $'−' lib app` → nothing. Check new labels in German. |
| **A new model field survives every copy** | `ActivityItem.snapId` was dropped by `asSeen()` (28 Nov 2026), so it disappeared as soon as the list was marked seen. | After adding a field to class `X`: `grep -n "X(" lib/models/x.dart` and pass the field in every constructor call (`copyWith`, `asSeen`, `_withY`). Test the field after the copy, not only after `fromJson`. |
| **Supabase providers in widgets** | `userProfileProvider`, `friendsProvider`, `budgetProvider` call Supabase when created and throw in tests that don't override them. | A widget that newly reads one: override it in every test that builds the widget, or read through a small provider with a safe fallback (`ownRecipeGoalProvider`). |
| **Every new text in all five languages** | `test/language_test.dart` only checks text that goes through `tr()`. "calories burned" stayed English because it was never wrapped. | Look for bare strings: `git diff -U0 -- lib \| grep '^+' \| grep -E "Text\(\s*'\|label: *'\|title: *'\|message: *'" \| grep -v "tr("` |

---

## 5. Tests

- **Run both suites before any commit,** and only after your last edit: a full `flutter test` that was running while you edited can show `Compilation failed` in an unrelated file (AGENTS.md §9.7).
- **The suites:** backend `.venv/bin/python -m pytest -q`; app `flutter analyze` (must say "No issues found!") and `flutter test` (about 2 minutes, so run it in the background).
- **New tests cover:**
  - the happy path;
  - a **missing table** (optional-table pattern);
  - **someone else's id** (409/404);
  - **no login** (401);
  - **banned words** in new text;
  - for the app, the old-backend case (a missing field).
- Names are plain sentences: `test_a_missing_table_is_an_empty_list_not_an_error`.
- **No test may depend on today's date** (one broke two days after it was written):
  ```bash
  git diff -U0 -- tests test | grep '^+' | grep -E "date\.today\(\)|datetime\.now\(|DateTime\.now\(\)"   # pass now=/today= in instead
  ```
- **App widget tests:**
  - use `variant: TargetPlatformVariant.only(TargetPlatform.iOS)`;
  - pump in 100 ms steps;
  - set the size with `tester.view.physicalSize`;
  - never set `debugDefaultTargetPlatformOverride` directly (`grep -rln "debugDefaultTargetPlatformOverride =" test` → nothing).

---

## 6. Secrets and files

```bash
git diff -U0 | grep '^+' | grep -nE "AIza[0-9A-Za-z_-]{20}|eyJ[A-Za-z0-9_-]{20,}|sk_(live|test)_|service_role|-----BEGIN|password *[:=]"
git status -s | grep -iE "\.env|\.jks|\.keystore|\.p12|\.zip|\.png|\.jpe?g"     # must not be staged
```
If the owner pastes a secret into the chat, tell them to rotate it, and never write it into a file.

---

## 7. Reporting (the owner reads this; plain words)

- For each claim, say "tested", "seen live" or "not verified". Never say a deploy is live without checking (AGENTS.md §4.5).
- Say what the owner must do (a migration to run, a setting to set, a phone test), with exact clicks.
- Commit message: `fix:` / `feat:` / `test:` / `docs:` plus one plain sentence about what changed for people and why, including any migration and what happens without it.
- Then add a dated section at the bottom of `handover.md`, and tick or add steps in `NEXT_STEPS.md`.

---

## 8. Reading existing code for bugs: patterns that were bugs here before

When asked to "check" or "review" code, search for these first. The expected clean result as of 26 Nov 2026 is shown, so anything new stands out.

```bash
grep -rnE "return \{.*\}, [0-9]{3}" app/                         # nothing
grep -rnE "\?key=|api_key=" app/                                  # two comments only
grep -rn "compare_digest" app/ | grep -v encode                    # two comments only
grep -rln "generativelanguage\|gemini_base_url" app/               # gemini_client.py, config.py
grep -rln "onrender.com" ../calorie_app/lib                        # api_config.dart only
grep -rn "Future.wait" ../calorie_app/lib/providers ../calorie_app/lib/services   # three reads, no saves
grep -rln $'−' ../calorie_app/lib app                         # nothing
grep -rln "debugDefaultTargetPlatformOverride =" ../calorie_app/test   # nothing
```

Some bugs no `grep` finds. Read for them:
- an `except` that returns a value meaning "nothing there" when the truth is "we couldn't check";
- a provider without a user check;
- a loop over people with no rollback;
- a new number field with no bounds;
- a new piece of text with no translation;
- a shared surface showing kcal.
