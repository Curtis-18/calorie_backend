# NuStreak: how we work in these repos (read this before touching anything)

Written 26 Nov 2026 for any coding agent (or person) that takes over. It sums up how the owner wants work done, how the code is written, what to check, and what has already been tried and failed. Follow it exactly unless the owner tells you otherwise in the chat.

**Reading order for a new session:**
1. This file (rules and habits). **Section 9 is the list of things already tried that failed: check it before building or "fixing" anything.**
2. `NEXT_STEPS.md` (what to do next, step by step, with code).
3. `REFERENCE.md` (facts you can't see from the code: every setting and dashboard, scheduled jobs, what has **never been seen working live**, the client decisions D1-D20, every table and endpoint). Look things up there; no need to read it all.
4. **The three skills in `.claude/skills/`** (how to work, step by step). Claude Code loads them automatically when the situation matches. With any other tool, open the file yourself at the moment it applies:
   - `read-the-codebase/SKILL.md`: at the start of a session, and before changing or explaining anything (how to trace a feature, how to find the code behind a screenshot or log line, how to check a note is still true).
   - `what-to-look-out-for/SKILL.md`: **before every commit**, and when reviewing code (the checklist, with a search command for each item).
   - `investigate-a-problem/SKILL.md`: whenever something is reported broken (evidence first, hypotheses, a failing test, verify live, report).
5. `handover.md` (the full history; 2,000+ lines). Do not read it all. Use its headings (`grep -n '^#' handover.md`) and read the section you need. Its newest facts are at the **bottom**; the status table near the top (§0) is old.

These files live in `/home/curtis/calorie_backend/`. **`handover.md` is gitignored**: it exists only on this laptop and must **never** be committed (both GitHub repos are **public**, and it names internal plans). **Since 28 Nov 2026 `AGENTS.md`, `NEXT_STEPS.md`, `REFERENCE.md`, `scripts/list_routes.py` and the three `.claude/skills/*/SKILL.md` files are committed to the backend repo** (the owner's choice: "GitHub, without handover"). When you change one of them, commit it by name with a `docs:` message, like code. A push to `master` makes Render redeploy the same code; that is harmless. Never put a secret, an email address or a user's data in them: anyone can read them. Never delete them.

---

## 1. The project in a few lines

- **Product:** NuStreak, "Snapchat for nutrition". People log meals (mainly by **photo**; AI identifies the food), keep streaks, send food photos ("bites") and stories to friends, chat, save recipes, get an AI coach, and use a Workouts tab. Six languages: English, Spanish, French, German, Portuguese, Italian.
- **Backend:** `/home/curtis/calorie_backend` (GitHub `Curtis-18/calorie_backend`, branch **`master`**). Python 3.13 on Render (FastAPI, SQLAlchemy async, asyncpg). **A push to `master` deploys to production on Render automatically.**
- **App:** `/home/curtis/calorie_app` (GitHub `Curtis-18/calorie_app`, branch **`main`**). Flutter (Dart). Published as a **web app** on Vercel by a GitHub Action (`.github/workflows/deploy.yml`). **A push to `main` deploys to production.** There is no phone build yet (iOS first is planned).
- **Database and logins:** Supabase project `pbancnuceteomuyybrlb` (Postgres + Auth + Storage). Schema changes are SQL files in `calorie_backend/migrations/` that **the owner runs by hand** in the Supabase SQL editor.
- **AI:** Google Gemini (free tier; quota is shared by all users). **Food data:** USDA FoodData Central (its key was disabled on 18 Nov; see the open list) and Open Food Facts for barcodes. **Recipes Browse tab:** TheMealDB (test key).
- **Addresses:** app `https://calorie-app-ug.vercel.app`; backend `https://calorie-backend-odc3.onrender.com`. **Since 26 Nov 2026 the web app calls the backend through `https://calorie-app-ug.vercel.app/api/...`** (Vercel forwards it to Render), because some networks cannot resolve `*.onrender.com` (see §10).
- Render free tier: the server **sleeps after about 15 idle minutes and takes 30 to 60 s to wake**. The owner knows this; do not offer it as an explanation for a bug unless you have proven it is the cause.

---

## 2. Who you work for and how they like things done

The **owner** (Curtis, GitHub `Curtis-18`) builds the app for a **client**. The owner talks to you; client decisions arrive through the owner. Decisions waiting for an answer are numbered D1-D20; the up-to-date list, in plain words, is `REFERENCE.md` §3. When you ask the owner, describe the decision in words, not just its number.

What the owner expects, learned over many sessions:

1. **Commit straight to `master` (backend) and `main` (app). Never create branches.** (Owner, 2 Nov: "we'll push straight to main/master okay dont create branches".)
2. **Run the tests before every commit. Ask before every push.** Pushes go to production. A "push" from the owner covers only what exists at that moment; later changes need a new "push it".
3. **The camera is the main action.** Photo logging must always look primary; manual search is the smaller, quieter button. Never hide the camera behind a "+" or a chooser. (Owner, 14 Nov, after I merged them: "the main purpose of the app is photos, why have you hidden it".)
4. **When something is broken for users, fix it now.** Diagnose from evidence (logs, screenshots, DNS lookups, the code), not guesses. Do not lecture about known limits (e.g. "the server sleeps"). Say what the cause was, what you changed, and what is still unproven.
5. **Plain language** in everything the owner reads and everything users read. No jargon in the app ("Mostly sitting", not "sedentary").
6. **Be honest about what was verified.** Say "tested", "seen live", or "not verified" for each thing. Never claim a deploy is live unless you checked it.
7. **Do what was asked, no more.** If you see something else worth doing, list it at the end and let the owner choose. If the owner says "don't build it yet" (e.g. smarter recommendations, R9.5), don't.
8. **Things the owner asked for that are now rules:**
   - Usernames are shown **without the @** everywhere (typing @ in search still works).
   - **Anything a person types (captions, chat messages, recipe titles, usernames) is never translated.** Only the app's own words are.
   - Every new piece of app text is translated into **all five** other languages in the same change.
   - The in-app **Notifications screen** = bites and reactions from friends (plus "What's new"). **Push notifications** are a separate thing (reminders and alerts sent to a device).
   - Captions are typed by the user, Snapchat-style (a "T" button, a white strip they can drag).
   - Rewards and streaks are **fun and positive**; nothing shames or punishes.
9. **Keep the handover current.** At the end of each piece of work, add a dated section at the **bottom** of `handover.md` (what was built, commit ids, migrations, tests, what is not verified, what is left) and update `NEXT_STEPS.md`.

---

## 3. Hard rules (never break these without the owner's explicit say-so)

**Safety and product (decided by the client; see handover "R2. Rules that override the notes"):**
1. **No calorie numbers on anything shared** (bites, stories, chat stickers, share cards). Protein grams, meal labels and streak lengths are allowed. Never kcal, weight, or a ring that implies kcal.
2. **Never reward eating less.** No day below the calorie floor (1200 women / 1500 men, `app/services/target_calculator.py`). Unlogged days are "unknown", not "ate nothing".
3. **No exercise as punishment.** Never "burn it off", never size a workout to a meal, never add burned calories to the target silently. (The opt-in "add movement to my plan" exists: off by default, max 50%, max 500 kcal a day.)
4. **Banned words** in anything the app or server says: burn (as in burn off), earn, cheat, guilt/guilty, punish, "make up for", detox, cleanse, reward/treat (as food), bad/good food, diet. Tests scan for these; add your new text to those tests.
5. **Adults only (18+).** Date of birth is checked in onboarding for every account, Google included.
6. **Core social features stay free forever** (stories, bites, messages, friends, photo logging, streaks, barcode, manual logging).
7. **No public vanity numbers:** no follower counts, no like counts.
8. **Private by default:** a food log is never shared unless the person shares it.
9. **Health content** (conditions, PCOS, cycle, "feel-good foods", recipe goal thresholds, the eat-back card) needs a dietitian's review before a store release (decision D19). Don't present it as medical advice.

**Engineering:**
10. **Never commit secrets.** No keys, tokens, `.env`, keystores. If the owner pastes a secret in chat, tell them to rotate it.
11. **Add files to git by name.** Never `git add -A` or `git add .`: the backend folder has untracked logo images, zips and `handover.md`, which must not be committed.
12. **Never run `dart format` (or any formatter) on existing files** in the app repo. It rewrites hundreds of lines and buries the real change.
13. **Never rename or reuse a database value an old app reads.** Example: `food_logs.source` only allows `manual|photo`; the app parses it with `FoodSource.values.byName`, so a new value (like `recipe`) would break every installed copy. Put new facts in a **new small table** instead.
14. **Never add a column to an existing table if the code would fail without it.** The owner runs migrations by hand and may be late. New data goes in its **own table**, read and written inside a savepoint so a missing table changes nothing (pattern in §5.3).
15. **Never make the app depend on a new backend field.** The app must work with an older backend, and the backend with an older app (people keep old web tabs open).
16. **Push order:** migration (owner runs it) → backend → app.
17. **Don't touch the Gemini prompts' safety rules** (`app/services/coach_prompt.py`, scan prompt) without tests.

---

## 4. The workflow, step by step

### 4.1 Start of a session
```bash
cd /home/curtis/calorie_backend && git status -sb && git log --oneline -5
cd /home/curtis/calorie_app && git status -sb && git log --oneline -5
```
- Both should say `## master...origin/master` / `## main...origin/main` with nothing "ahead". If something is ahead, it was committed but not pushed: find out why in the handover before doing anything.
- Known harmless leftovers: untracked logo images in the backend folder (never commit them); `macos/Flutter/GeneratedPluginRegistrant.swift` modified in the app (generated by Flutter; safe to commit on its own, see NEXT_STEPS).
- Read `NEXT_STEPS.md`, then the bottom of `handover.md`.

### 4.2 Making a change
1. Read the code you will change and its tests first. Find an existing example of the same kind of thing and copy its pattern (§5, §6).
2. Backend first if both sides change.
3. Write or update tests in the same change (every feature here has tests).
4. New user-facing text: translate in all languages (§5.5, §6.4).
5. Keep comments explaining **why** (this codebase's style: comments describe the incident that caused the code).

### 4.3 Testing (must be green before any commit)
Backend:
```bash
cd /home/curtis/calorie_backend
.venv/bin/python -m pytest -q          # about 1,100 tests, no database needed
```
If `.venv` is missing: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r tests/requirements.txt`.

App:
```bash
cd /home/curtis/calorie_app
flutter analyze                        # must say "No issues found!"
flutter test                           # about 1,000 tests, ~2 minutes
flutter build web --release            # only for config/build changes; takes ~2 minutes
```
Long commands: run them in the background or with a long timeout; tools with a 2-minute limit will cut them off.

### 4.4 Committing
- Message style (look at `git log`): a prefix (`feat:`, `fix:`, `test:`, `docs:`) and then **one plain sentence saying what changed for people and why**, including any migration and what happens without it. Example from the log:
  `fix: USDA amounts below zero are read as zero; log which field and rule a refused request failed on (names only, never values)`
- Existing commits end with a `Co-Authored-By:` line for the AI that wrote them; follow your own tool's attribution rule.
- One logical change per commit.

### 4.5 Pushing (only after the owner says "push")
```bash
git log origin/main..main --oneline     # (or origin/master..master) see exactly what will go
git push origin main                    # or master
```
Then **verify**:
- App deploy (no `gh` CLI here):
  ```bash
  curl -s "https://api.github.com/repos/Curtis-18/calorie_app/actions/runs?per_page=1" | python3 -c 'import sys,json;r=json.load(sys.stdin)["workflow_runs"][0];print(r["head_sha"][:7],r["status"],r["conclusion"])'
  ```
  Repeat until it shows your commit with `completed success` (takes ~4 minutes).
- Backend deploy: Render has no public status. A **new route** answers `401` (not `404`) once live:
  `curl -s -o /dev/null -w '%{http_code}\n' https://calorie-app-ug.vercel.app/api/<new-route>`.
  An existing route cannot tell old code from new; ask the owner to look at the Render dashboard ("Live" next to the commit).
- Then tell the owner what is live, what you checked, and what is still unproven.

### 4.6 End of a session
1. Add a dated section at the bottom of `handover.md`: what was done, commit ids, pushed or not, migrations (run or not), test counts, not verified, still open.
2. Update `NEXT_STEPS.md` (tick finished steps, add new ones).
3. Tell the owner, in plain words, what they must do (migrations to run, env vars to set, things to test on a phone).

---

## 5. Backend: how code is written here

### 5.1 Layout
- `app/main.py`: app setup, CORS, error handlers, `/`, `/health`, `/me`. **Register every new router here** (`app.include_router(...)`) and **import every new model** in the long `from app.models import ...` line.
- `app/routers/*.py`: HTTP routes, one file per area. `app/services/*.py`: logic (pure functions where possible, so they are easy to test). `app/models/*.py`: SQLAlchemy tables. `app/schemas/*.py`: Pydantic request/response shapes.
- `app/core/`: config (`config.py`, env vars), database (`database.py`), auth (`security.py`), dates (`dates.py`: `resolve_today`), language (`language.py`), rate limits (`rate_limit.py`), features (`features.py`: `require_feature`, `record_usage` for the future Pro tier).
- `app/i18n/`: server text in five languages (`es.py`, `fr.py`, `de.py`, `pt.py`, `it.py`, `errors.py`).
- `migrations/`: hand-run SQL, named `YYYY-MM-DD_what.sql`. **The date in the name is a sequence number, not the real date** (they run ahead of the calendar). Use the next one after the last file.

### 5.2 A route (copy this shape; real example `app/routers/movement.py`)
```python
@router.post("", response_model=MovementOut)
async def log_movement(
    data: MovementIn,
    user_id: uuid.UUID = Depends(get_current_user_id),   # every route except / and /health needs a login
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),                    # when the answer has words in it
):
    """Docstring in plain words: what it does, and that repeating it is harmless."""
    # Idempotent: the APP chooses the id, so a retry after a lost answer never doubles anything.
    existing = (await db.execute(select(MovementLog).where(MovementLog.id == data.id))).scalar_one_or_none()
    if existing is not None:
        if existing.user_id != user_id:
            raise HTTPException(409, "That id is already used.")
        return _out(existing, lang)
    ...
    try:
        await db.execute(pg_insert(MovementLog).values(row).on_conflict_do_nothing())
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("saving movement failed")            # log what failed, never personal values
        raise HTTPException(500, "Couldn't save that. Please try again.")
```
Rules:
- "Today" always comes from the device: accept `date` and pass it through `resolve_today(date)` (accepts ±1 day of the server's UTC date).
- Settings/choices are `POST`, not `PATCH`/`PUT`, by habit (CORS used to allow only GET/POST/DELETE; `PATCH` and, on 28 Nov 2026, `PUT` were added later).
- Error messages are short plain sentences. **Every new message must be added to `app/i18n/errors.py`** with five translations, or `tests/test_error_languages.py` fails. Machine codes for the app (like `ai_quota`) go in `NOT_FOR_PEOPLE` in that test instead.
- Never log personal values (food names, notes, messages, emails). Log field names, statuses, counts.
- Costly things (Gemini, USDA) get a rate limit in `app/core/rate_limit.py` and `require_feature(...)` / `record_usage(...)`.

### 5.3 A new table (the "optional table" pattern)
1. Migration file, idempotent, RLS on, with a check query at the end (copy `migrations/2026-11-28_caption_positions.sql`):
   ```sql
   -- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
   -- Safe to re-run: every statement is idempotent.
   -- What this is for, and what happens before it is run (nothing breaks).
   create table if not exists public.my_things (
     id uuid primary key,                                        -- chosen by the app
     user_id uuid not null references public.profiles(id) on delete cascade,   -- deleted with the account
     created_at timestamptz not null default now()
   );
   create index if not exists my_things_user_idx on public.my_things (user_id);
   alter table public.my_things enable row level security;      -- ALWAYS: closes the public REST API
   select relname, relrowsecurity as rls_enabled from pg_class
   where relnamespace = 'public'::regnamespace and relname = 'my_things';
   ```
   RLS with no policies is correct here: the backend connects as `postgres` and bypasses it; nobody else can read the table.
2. Model in `app/models/`, imported in `app/main.py`.
3. Reads and writes in a **savepoint** so a missing table never breaks the request (real example `app/services/caption_pos.py`):
   ```python
   try:
       async with db.begin_nested():
           rows = (await db.execute(select(...))).all()
   except Exception:  # noqa: BLE001 - table missing (migration not run): treat as empty
       log.warning("my_things: could not read", exc_info=True)
       rows = []
   ```
4. Account deletion: `on delete cascade` from `profiles` covers rows. **Files in Storage do not cascade**: add them to `app/services/account_service.py` and its test.
5. Tell the owner to run the migration, and write in the handover whether it was run.

### 5.4 Tests (no real database, no real network)
- `tests/conftest.py` gives `client` (logged in as user `...0001`) and `anon_client` (no login). It also blocks Gemini, Open Food Facts and the usage counter by default.
- Database calls are faked with small classes that return canned results and record SQL text. Copy `_Db`, `_Result`, `_Nested` from `tests/test_activity.py`. To use a fake database in a route test:
  ```python
  def _with_db(db):
      from app.core.database import get_db
      from app.main import app
      async def fake_db():
          yield db
      app.dependency_overrides[get_db] = fake_db
  ```
- Test names are plain sentences: `test_a_missing_table_is_an_empty_list_not_an_error`.
- Always test: the happy path, a missing table, someone else's id (409/404), no login (401), and the banned-word check for new text.
- **Never write a test that depends on today's date** (one broke on 22 Nov). Pass `now=`/`today=` in.

### 5.5 Server text in other languages
- `t(lang, "English text", **params)` from `app.i18n`. English is the key. Add the exact same English key to **all five** tables `app/i18n/{es,fr,de,pt,it}.py`. `tests/test_languages.py` fails on a missing or misspelled key and on mismatched `{placeholders}`.
- Push notification text lives in `_COPY` in `app/services/notification_rules.py` (English) and is translated through the same tables.

### 5.6 Gemini
- All calls go through `app/services/gemini_client.generate_content`, which checks the shared daily budget (`gemini_budget.py`) and the per-model breaker. Never call the Gemini API directly.
- Settings (Render env): `GEMINI_DAILY_BUDGET`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `SCANS_PER_USER_PER_DAY`, `GEMINI_INSIGHTS`.
- Nothing personal goes to Gemini beyond what the feature needs: the coach gets no email, username, friends or avatar (a test checks this).

---

## 6. App: how code is written here

### 6.1 Layout
- `lib/config/api_config.dart`: the backend address. **Use `ApiConfig.baseUrl` for every backend call; never write the onrender.com address anywhere else.**
- `lib/services/*_service.dart`: one class per backend area. `lib/providers/*_provider.dart`: Riverpod `StateNotifier`s. `lib/models/`: data classes and pure logic. `lib/screens/`, `lib/widgets/`: UI. `lib/theme/`: colours, spacing, motion. `lib/l10n/`: translations.
- UI is **Cupertino** (iOS style) with our own design system: reuse `AppButton`, `AppCard`, `AppDialog`, `AppField`, `FrostedGlass`, `PageHeader`, `SettingsList`, `TrackerColors`, `AppSpacing`, `AppMotion`. Don't add Material widgets or new UI packages.

### 6.2 A service (copy `lib/services/activity_service.dart`)
```dart
class ActivityService {
  ActivityService({this._client, this._tokenProvider});   // injectable for tests
  final http.Client? _client;
  final String? Function()? _tokenProvider;

  Future<http.Response> _send(Future<http.Response> Function(http.Client, Map<String, String>) call) async {
    final token = (_tokenProvider ?? _supabaseToken)();
    if (token == null) throw StateError('signed out');
    final client = _client ?? http.Client();      // newer services use languageClient() so the server answers in the app's language
    try {
      return await call(client, {'Authorization': 'Bearer $token'}).timeout(const Duration(seconds: 30));
    } finally {
      if (_client == null) client.close();
    }
  }

  Uri _uri(String path) => Uri.parse('${ApiConfig.baseUrl}$path');
}
```
- Use `languageClient()` (from `language_client.dart`) when the server's answer contains words.
- Read bodies with `jsonDecode(utf8.decode(r.bodyBytes))` (accents break otherwise).
- Never show the server's English error text to people; map status codes to the app's own translated messages.

### 6.3 Models and providers
- **Parse tolerantly**: unknown values become `null` or a default, never a crash (`ActivityItem.fromJson` returns null for a kind it doesn't know). A newer server must never break an older app.
- Providers **follow the signed-in user** (`UserCache.currentUserId`, `userIdChanges`): clear on sign-out, reload on a new user, and use a `_generation` counter so a late answer for the previous user is dropped. Copy `lib/providers/activity_provider.dart`.
- Device cache keys include the user id (`food_log:<uid>:<date>`).
- Saves use an **id chosen by the app** and retry only on timeout/5xx, never on 4xx; the server treats a repeated id as already saved.

### 6.4 Text and languages
- In widgets: `context.tr('English text', {'name': value})`. Elsewhere (services, models): the global `tr('English text')`. Never inside a `const` or `static final` (it must be evaluated each time).
- Add the English text as a key with its translation to **all five** files `lib/l10n/translations_{es,fr,de,pt,it}.dart`. `test/language_test.dart` fails on any missing phrase or placeholder mismatch.
- **Never pass user-typed text through `tr()`.**
- Translations are written by the AI, not native speakers; the owner knows a native review is needed before a store release.

### 6.5 Colours and look
- Colours are **getters** (`TrackerColors.surface`), so they can't be in `const` expressions.
- Text or icons in the brand colours: wrap with `TrackerColors.ink(...)` (lime on white is unreadable). Anything drawn on a gradient: `TrackerColors.onAccent`. Fire/streak things use `flameStart`/`flameEnd`, never the lime/aqua accents.
- Custom painters must repaint on theme change (`_paletteEpoch` in `shouldRepaint`).
- Use our own icons (`lib/widgets/move_icons.dart`) rather than emoji in the UI.
- Use "–" (en dash), not "−" (U+2212), which shows as a box in some fonts.
- Respect reduce-motion settings for animations.

### 6.6 App tests
- Widget tests: use `variant: TargetPlatformVariant.only(TargetPlatform.iOS)` when text uses `AppType` (otherwise it tries to download Google Fonts and fails). Don't assign `debugDefaultTargetPlatformOverride` directly.
- Pump in 100 ms steps (`for (var i = 0; i < 8; i++) await tester.pump(const Duration(milliseconds: 100));`); one long pump doesn't finish animations or route changes.
- Set screen size with `tester.view.physicalSize`. Locale-dependent defaults need `tester.platformDispatcher.localeTestValue`.
- Inject services and clocks (constructors take them). Never hit the network.
- **To look at a screen without a phone** (golden trick): write a throwaway `test/zz_preview_test.dart` that loads a system font with `FontLoader` under the names `NunitoSans_regular`/`_500`/`_600`/`_700`/`_800` plus `packages/cupertino_icons/CupertinoIcons`, renders the widget with `matchesGoldenFile` (**not** with the iOS variant: text becomes blocks there), run `flutter test test/zz_preview_test.dart --update-goldens`, view the PNG (a google_fonts error after it is written is harmless), then **delete the test and the PNGs**. Details in handover "Harness tip (worked this time)".

---

## 7. What only the owner can do (ask; you can't do these)

- Run SQL migrations in Supabase (SQL Editor). Give them the exact file name and say what happens before it is run.
- Set environment variables in Render (Dashboard → the service → Environment) and GitHub secrets for the app build (repo → Settings → Secrets and variables → Actions).
- Look at Render and Vercel dashboards, logs and usage.
- Google Cloud, Apple Developer, Firebase, App Store accounts; buying a domain; paying for Gemini/TheMealDB.
- Test on a real phone.
- Ask the client for decisions (D-numbers).

When you need one of these, write the exact clicks and values (never the secret itself) and wait.

---

## 8. Checking the live system

- **Backend health through the app's address** (works on every network): `curl -s https://calorie-app-ug.vercel.app/api/health` → `{"status":"ok","database":"ok"}`. A first call after idle can take 30-60 s (waking up).
- **Directly** (blocked on the owner's home network's DNS): `curl -s https://calorie-backend-odc3.onrender.com/health`. If DNS fails, add `--resolve calorie-backend-odc3.onrender.com:443:216.24.57.16` (the IP may change; get it with `dig @8.8.8.8 calorie-backend-odc3.onrender.com +short`).
- **"Users can't reach the server"**: check DNS first: `dig <host>` vs `dig @8.8.8.8 <host>`. Then `/api/health`. Then CORS (a refused origin shows as a network error in the browser). Only then the server.
- Render's access log shows only status codes. Refused requests (422) also log `request refused <method> <path>: <field>:<rule>` (no values).
- The app's "Our server naps..." / "Couldn't reach the server" screen appears for **any** failure to get an answer within 100 s, not only a sleeping server.

### 8.1 When the owner says "the app is down": checklist (go in this order)

Work from evidence; write down what each step showed. The owner wants the cause found and fixed now (§2.4), not explained away.

1. **Look at what the user sees** (ask for a screenshot). "Our server naps" / "Couldn't reach the server" = no answer within 100 s, whatever the reason. A blank white page = the web app itself failed to load. A login error = Supabase Auth or our 401s.
2. **Is the web app up?** `curl -s -o /dev/null -w '%{http_code}\n' https://calorie-app-ug.vercel.app` → `200`. If not: check the last deploy (§4.5 command) and https://www.vercel-status.com.
3. **Is the backend up through the app's address?** `curl -s -m 90 https://calorie-app-ug.vercel.app/api/health`. Give it up to 60 s (waking); try twice.
   - `{"status":"ok","database":"ok"}`: the backend is fine; go to step 5.
   - `"database"` not ok, or 503: Supabase. Ask the owner to open the Supabase dashboard (is the project **paused** or unhealthy?) and check https://status.supabase.com.
   - 502/504, or nothing after 90 s: Render. Ask the owner for Render → the service → **Logs** and **Events** (crash on start? failed deploy?). A failed deploy keeps the old version running; a crash loop does not.
4. **Is it the network, not us?** If only some users are affected: `dig calorie-app-ug.vercel.app` vs `dig @8.8.8.8 calorie-app-ug.vercel.app` (and the same for any other address in the error). If a network blocks `vercel.app` too, only a domain of our own fixes it (NEXT_STEPS step 10).
5. **Did a push just happen?** `git log -3 --format='%h %ci %s'` in both repos; compare with when the trouble started. If a push caused it, **roll back first, then fix calmly**:
   - **App (Vercel):** the owner opens the project → Production Deployment → **Instant Rollback** → Continue → Confirm. The Hobby plan can only go back to the **one previous** deployment. **After a rollback, Vercel stops making new deploys live automatically**: once the fix is pushed, the owner must click **Manage** → pick the new deployment → **Confirm** (that "promotes" it and turns automatic going-live back on). Or: `git revert <sha>` + push (with the owner's OK), about 4 minutes.
   - **Backend (Render):** the owner opens the service → **Deploys** → a recent successful deploy → **Rollback** → **Rollback to this deploy**. **A dashboard rollback switches off auto-deploy**: after the fix, the owner must turn it back on in the service's **Settings**, or the push will not deploy. (Whether the free plan keeps old builds to roll back to is not documented; if the button isn't there, `git revert <sha>` + push.)
   - **Migrations can't be rolled back** and don't need to be: they only add tables, and older code ignores them. **Never drop a table** to "undo" one.
   - These rollback steps come from Vercel's and Render's docs (read 26 Nov 2026). They have never been tried on this project.
6. **Only some features broken?** These are not outages; say so plainly and fix them:
   - Scans fail but logging works: the Gemini quota (Render log `gemini error 429` / budget lines), or a bad Gemini setting.
   - Food search and barcodes fail: the USDA key (disabled since 18 Nov).
   - Bites, stories and avatars fail with 503: `SUPABASE_SERVICE_ROLE_KEY`.
   - Everyone keeps getting logged out: something answering 401 for our own fault (§9.3).
   - Database errors that started right after the owner set `DB_POOL=queue` on Render (Render log: `prepared statement ... does not exist` / `already exists`, `InterfaceError`, `connection is closed`, many 500s): the owner deletes `DB_POOL` in Render → Environment → Save. That switches back to a new connection per request (how it ran until 28 Nov 2026) on the next deploy, which Render starts by itself. Then tell the owner what the log said; don't try to "fix" the pool settings without re-running the load test (handover "28 Nov 2026 (third round)").
7. **Afterwards:** tell the owner the cause, what you changed, what you checked live and what is still unproven. Add a dated section at the bottom of `handover.md`. If a rollback was done, make sure automatic deploys were switched back on (step 5).

---

## 9. TRIED AND FAILED: do not try these again

Every item below was tried (or seriously proposed), and it broke something, was undone, or was refused by the owner or the client. **Before you build, change or "fix" anything, search this section for it** (search a key word: "camera", "bell", "CORS", "Gemini", "retry", "tour"...). If you believe one of these should be tried again, ask the owner first and say what is different this time.

Each line: **Don't** (what was tried) → *why it failed* → **Instead** (what works now).

### 9.1 The owner or client said no, or asked for it to be undone

- **Don't hide the camera behind one "+" button or a chooser.** Tried 14 Nov in the UI tidy-up (app `7e907f8`). Owner: "the main purpose of the app is photos, why have you hidden it". Undone in `d533761`. **Instead:** a big gradient camera button plus a smaller, quieter search button on Today and on every meal card.
- **Don't remove the bell from the Today header.** The 14 Nov tidy-up removed it (and deleted its test). On 20 Nov it had to come back: once "What's new" was read there was no way to reach Notifications from the home screen. **Instead:** the bell is always shown; the dot appears only when something is unread.
- **Don't offer a fixed list of "mood chips" for bites and stories** (19d: "Cooking at home", "Takeaway"...). The owner dropped it on 22 Nov. **Instead:** people type their own caption, Snapchat style.
- **Don't build your own idea of an interaction the owner described.** The first caption version (`4d7d93a`: tap the photo, dark strip) wasn't what was asked. The owner then spelled it out: "there should be a T, when they tap on it a white strip comes up and they type in it, it should be draggable" (`3f38c1a`). **Instead:** build exactly what is described; if unclear, ask.
- **Don't build a full-screen slideshow when a "tour" is asked for.** The Workouts tour was first built as a slideshow by mistake and deleted. **Instead:** the spotlight tour (`lib/widgets/app_tour.dart`: dims the screen and points at the real parts), `b8fd7f4`.
- **Don't reuse another tour's "seen" key.** The new Workouts tour reused the slideshow's key, so everyone who had seen the slideshow never got the tour (fixed in `e13a9c2`). **Instead:** each tour has its own key in `TourService`.
- **Don't put messages or friend requests in the in-app Notifications list.** A "For you" card listing them was built and removed the same day (22 Nov). **Instead:** the list = bites and reactions from friends, plus "What's new". Messages have their own screen; requests are on Friends.
- **Don't describe push notifications as what fills the in-app list.** Push = alerts sent to a device; the in-app list is separate.
- **Don't make orange the main colour.** The client found orange "not fun to look at" (5 Nov); lime → aqua was chosen. Orange/red/yellow are only for fire (streaks) and warnings. Friend avatars once got orange by chance and were changed to cool gradients (`a890c06`).
- **Don't show clinical BMI words** ("Overweight", "Obese"). **Instead:** "Below range / In range / Above range / Well above range" (`b1a589d`).
- **Don't use jargon or dropdowns in onboarding** ("sedentary", "maintain", ALL-CAPS lists). **Instead:** plain words and choice cards from `lib/models/profile_copy.dart`.
- **Don't show the @ before usernames** in the app (owner, 22 Nov). Typing @ in search still works.
- **Don't translate anything a person typed** (captions, messages, recipe titles, usernames).
- **Don't go back to "exact username only" friend search.** Search as you type was added at the owner's request on 14 Nov (it reversed the 4 Nov decision).
- **Don't put an "Add" button next to the friend search field.** It could send a request to a mistyped name. **Instead:** a search icon; adding happens only from a found person's row.
- **Don't put the big profile-link Copy/Share buttons back on Friends.** **Instead:** a small copy chip on the Profile tab (`adcccb9`).
- **Don't bring back Tips on Insights, or make Insights a tab again** (22 Nov: Workouts took the tab). **Don't remove `tips: []` from the server response**: old open copies of the app would crash without it.
- **Don't build "smarter recommendations" / AI embeddings** (R9.5). The owner said "don't build it yet".

### 9.2 Ideas already refused (safety rules: don't propose them again)

- Calories, kcal stickers or a "macro ring" on anything shared (R2.1).
- Burned calories raising the calorie or protein target automatically (R2.3). The only allowed form is the opt-in movement share: off by default, at most 50%, at most 500 kcal a day (D11).
- A calorie-guessing game on friends' meals, and "log to unlock" friends' posts (R8.19). Only "guess the dish" would fit the rules (decision D16).
- A permanent food-photo grid on profiles.
- Follower counts, like counts, leaderboards of calories or workout volume.
- "Drink some water" as a quick reply (health-policing from a friend).
- The words "Treating myself", "Too lazy to cook", treat, reward, earn, cheat, guilt, detox, cleanse, "burn it off", "make up for", punish, diet.
- Saying a food "boosts dopamine" or helps with a medical condition (R8.15, R8.16).
- Changing the pair-streak rule (a missed day resets it, no grace) without the client (D17).
- Saving or sending the "How are you feeling?" choice anywhere (R8.20). It stays on the screen only.
- Message text inside a push notification (it shows on lock screens). **Instead:** "{name} sent you a message", at most once per sender per hour.
- **Inventing numbers:** the restaurant-portion factor (1.25 is an unsourced placeholder), the one-tap extras' USDA ids, and the scan timings stay marked unverified until real data or a real citation exists. Never fake a citation or a measurement.

### 9.3 Backend approaches that broke

- **Don't answer with a value that means something else when a read fails.** `GET /me` answered `username: null` on a database error, so people with a username were sent to the picker and saw their own name as "taken". **Instead:** 503.
- **Don't answer 401 for a problem on our side.** A hiccup reading Supabase's keys returned 401; the app signs out after two 401s, so people were logged out. **Instead:** 503. 401 only for a really bad or expired token.
- **Don't return a tuple from a route** (`return {...}, 503`). FastAPI sent it as a 200, so Render never restarted on a dead database. **Instead:** `JSONResponse(status_code=503, content=...)`.
- **Don't change the start command** (`gunicorn ... --worker-class uvicorn.workers.UvicornWorker`). Without the Uvicorn worker every request crashed.
- **Don't pass a dict into a Pydantic model whose field names differ** (`**nutrients` into `FoodSearchResult`). Every food search 500'd and the search proxy had never worked. **Instead:** map fields by name, and check new code against one real response.
- **Don't turn every database error into one status.** `POST /logs` once answered 409 for everything. **Instead:** same person's repeated id = 200 with the stored row; someone else's id = 409; anything else = logged 500.
- **Don't let a retry create a second row.** **Instead:** the app chooses the id; the server treats a repeat as "already saved". Every create is idempotent.
- **Don't add a column to an existing table, or a new switch that needs one.** Every request touching it fails until the owner runs the migration. Example: a separate "messages" notification switch would need `notification_prefs.messages`, so messages and friend requests follow the existing `friend_snaps` switch. **Instead:** a new table, read and written in a savepoint.
- **Don't add a new value to `food_logs.source`** (e.g. `recipe`). Every installed app parses it with `FoodSource.values.byName` and would break. **Instead:** recipe logs are `manual`, plus a quiet event row.
- **Don't keep going after a failed statement in a loop over many people.** The transaction stays aborted and everyone after the failure failed too (reminder job). **Instead:** `await db.rollback()` inside the per-person `except`.
- **Don't call `secrets.compare_digest` on text that may be non-ASCII.** It raised, giving a 500. **Instead:** compare bytes (`.encode()`).
- **Don't accept unbounded numbers.** An Infinity calorie value was stored and then broke every read of that day; a weight of 1e300 kg gave a 500. **Instead:** bounds and `allow_inf_nan=False` on every number.
- **Don't store a timestamp with a time zone in a `TIMESTAMP WITHOUT TIME ZONE` column** ("...Z" gave a 500). **Instead:** convert to naive UTC.
- **Don't use names or "/" in ids.** Old photo entries had the food name in their id; a "/" made them impossible to edit or delete. **Instead:** random UUIDs; routes take `{log_id:path}` for old ids.
- **Don't put API keys in URLs** (`?key=`, `?api_key=`). They ended up in Render's logs through error messages. **Instead:** headers (`x-goog-api-key`, `X-Api-Key`).
- **Don't read request bodies without a size limit.** Anyone could post hundreds of MB before the login check. **Instead:** `BodyLimitMiddleware`.
- **Don't let removed or blocked people keep interacting.** They could still react to bites and notify the person who blocked them. **Instead:** every view/react checks for a current friendship.
- **Don't regenerate AI text on every change.** Insights called Gemini after every logged food and used up the quota. **Instead:** at most every 3 hours, or when the person pulls to refresh.
- **Don't cache AI text without checking what it depends on.** Insights kept talking about old targets all day. **Instead:** regenerate when `targets.updated_at` is newer.
- **Don't put raw floats or ISO dates into prompts or user-facing text** (`43.090999999999994g`, `2026-11-18`). **Instead:** round, and format dates with `app/i18n/dates.py`.
- **Don't use `create_tables.py` on a database.** It makes tables without row-level security. **Instead:** migrations.
- **Don't hard-code CORS origins.** One origin blocked every deployed frontend; a pasted trailing slash matched nothing. **Instead:** `CORS_ORIGINS` (wildcards allowed, slashes stripped). `PUT` was added on 28 Nov 2026.
- **Don't add a new kind of reportable content without widening `content_reports_kind_check`.** Reporting a message failed in production until the messages migration widened it.
- **Don't re-sign photo links on every refresh.** Phones re-downloaded every picture. **Instead:** avatar links are reused for 12 hours.
- **Don't add `prepared_statement_name_func` to the database settings** (SQLAlchemy's tip for PgBouncer), and don't turn either statement cache back on. In a load test through PgBouncer in transaction mode (28 Nov 2026), named statements were left behind on the database's connections (about 160 each after 600 requests, and growing). **Instead:** `statement_cache_size=0` and `prepared_statement_cache_size=0` (unnamed statements, nothing outlives a transaction), as in `engine_options` in `app/core/database.py`. **Don't make `DB_POOL=queue` the default in code either**: the owner switches it on in Render, so switching it off again needs no deploy of new code.

### 9.4 Gemini, USDA and outside data

- **Don't retry Gemini on 429, 500, 502 or 504.** Retrying a 429 burned more of the spent quota. **Instead:** only 503 is retried.
- **Don't make two Gemini calls per scan.** **Instead:** one call returns the foods and per-100 g estimates; a second call only for items whose estimate failed.
- **Don't remove the thinking limit or its fail-safe.** Without it, a photo-to-list job paid for "thinking". The limit is set by model name, and if Gemini refuses it, the call repeats without it.
- **Don't "fix" the uppercase types in the scan schema** (`"ARRAY"`, `"OBJECT"`, handover B14). They were tested live on 14 Nov and work. Older lines in the handover that say to change them are out of date.
- **Don't add `mediaResolution`** to Gemini calls. The parameter was never verified, and the daily request count, not tokens, is the limit.
- **Don't build the "lightweight preview" scan call** before a week of `scan_done` timings has been read (R8.1 1a). It doubles the calls per scan.
- **Don't call Gemini directly.** **Instead:** `gemini_client.generate_content` (shared daily budget, breaker, fallback model).
- **USDA traps that already bit:**
  - Foundation foods that list energy only under "Atwater" names were dropped. They're read now.
  - Junk Branded rows (olive oil at 0 kcal). Filtered by `is_plausible`.
  - Negative "carbohydrate by difference" (lean meat) made a save fail with 422. Read as 0 (`_not_negative`).
  - Branded liquids are per 100 ml, not 100 g. Still open: NEXT_STEPS step 5.
  - Barcodes are stored zero-padded to 14 digits. Several forms are tried.
  - `DEMO_KEY` rate-limits after 2-3 calls. The key in the local `.env` is disabled (403 `API_KEY_DISABLED`).
- **Don't put any API key in the app.** The old USDA key is in the app's git history because it once was.
- **Recipe data:**
  - Don't use non-commercial datasets (CC BY-NC sets on Kaggle and Hugging Face).
  - Don't trust the Kaggle "CC0" recipe set until its source is checked.
  - Don't cache or copy Edamam results.
  - Never scrape recipe sites.
  - TheMealDB's free test key isn't allowed in a public app: buy the supporter key or remove Browse.
- **TheMealDB has no nutrition numbers.** Don't show goals, tags or calories for Browse recipes; don't estimate them silently.
- **Mood picks found real problems:** sweet pies counted as "comforting"; "eggs" matched about 100 recipes by accident; the same dozen always came first. Sweets are excluded, eggs aren't a keyword, and ties are shuffled by day. Don't loosen these.

### 9.5 App approaches that broke

- **Don't add a field to an app model without updating every method that copies it.** On 28 Nov 2026 `ActivityItem` got `snapId`, but `asSeen()` (which builds a copy when the list is marked seen) didn't pass it on, so the field vanished the moment the Notifications screen opened and every tap went to Friends. The unit test of `fromJson` passed; only a widget test caught it. **Instead:** after adding a field, `grep -n "ClassName(" lib/` and fix every constructor call inside the class (`copyWith`, `asSeen`, `toJson`, `_withX`), and test the field *after* the copy (`test/activity_test.dart` does `fromJson(...).asSeen().snapId`).
- **Don't read a Supabase-backed provider from a widget that other tests build without overriding it.** `userProfileProvider`, `friendsProvider`, `budgetProvider` and similar call Supabase when created, which throws in tests. Adding `ref.read(userProfileProvider)` to the recipes tab would have crashed five unrelated test files. **Instead:** either add the override to every test that builds the widget, or read through a small provider that falls back safely (`ownRecipeGoalProvider` in `lib/screens/my_recipes_view.dart`: `try { ... } catch (_) { return null; }`, so the tab starts on "All"). Tests that need a value override the small provider (`ownRecipeGoalProvider.overrideWithValue(...)`).
- **Don't save several items with `Future.wait`.** One refused item showed "Couldn't save your meal" while the others saved, and a retry duplicated them. **Instead:** save each item on its own and name only the ones that failed (`lib/services/save_entries.dart`).
- **Don't show Sign up to a logged-out person.** Returning users made duplicate accounts. **Instead:** Login, with a link to Sign up.
- **Don't capture a login token once and reuse it.** "Retry" after "Could not reach the server" did nothing (old error kept on screen, expired token reused). **Instead:** `ServerHandshake` gets a fresh token on every attempt.
- **Don't make one long request at start-up.** A single 60 s request failed on cold starts. **Instead:** retries for up to 100 s with the waking screen.
- **Don't write a provider that loads once for whoever is signed in.** User B saw user A's Insights after switching accounts. Cache keys without the user id leaked data on shared devices. **Instead:** providers follow the signed-in user, and every cache key includes the user id.
- **Don't store "today" once when a screen is created.** After midnight the app counted yesterday's food and cached it under the new date, and the add buttons vanished. **Instead:** the day rollover in `FoodLogNotifier`.
- **Don't let actions on a past day touch today.** "+" and swipe-to-delete on a past day acted on today's log. Past days are read-only.
- **Don't drop the generation counters.** A reload during a save dropped the new entry or brought back a deleted one.
- **Don't use a tour or onboarding package.** `tutorial_coach_mark` looked broken: text over cards, no Next button, "Skip" on a tab icon. **Instead:** our `AppTour`.
- **Don't take bite photos at `ResolutionPreset.high` and enlarge them.** Bites looked soft. **Instead:** `veryHigh` with a size cap.
- **Don't capture translucent gradients or backdrop blur into an image** (the share card). A muddy ring appeared and blur didn't capture. **Instead:** an opaque base and no blur.
- **Don't render a share image inside the tap.** Web Share must run inside the person's tap, so render the PNG first.
- **Don't ask for a browser permission after an `await` in the tap handler.** Safari only asks inside the tap. **Instead:** fetch what's needed (the push key) when the screen opens.
- **Don't put a service worker at the site root.** It would clash with Flutter's own. **Instead:** the push worker lives in `web/push/` (scope `/push/`).
- **Don't open the camera automatically in a browser.** Browsers block it without a tap ("open the camera at launch" is for phone builds only).
- **Colour traps:**
  - Lime/aqua as text or icon colour is unreadable on white: use `TrackerColors.ink(...)`.
  - `textPrimary` on a gradient turns black in light mode: use `onAccent`.
  - Theme colours are getters, so they can't be `const`.
  - The celebration card was dark on dark in light mode.
  - Fire uses `flameStart`/`flameEnd`, never the accents.
- **Don't use "−" (U+2212).** It shows as a box. Use "–".
- **Don't assume English widths.** German "Kohlenhydrate", the "Bite back" label and "New bite" beside a friend's name all overflowed. Let labels shrink or wrap, and check German.
- **Don't rely on the language test to catch untranslated text.** It only checks text passed to `tr()`; "calories burned" stayed English because it was never wrapped. Read your diff for bare strings.
- **Don't use emoji as UI icons.** **Instead:** our icon set (`lib/widgets/move_icons.dart`).
- **Don't add packages you don't use.** `permission_handler` and `path_provider` were unused and added store permission requirements. Removed.
- **Don't commit archives or images** (a stray `lib.zip` was committed once).

### 9.6 Deploy, hosting and network

- **Don't call `*.onrender.com` straight from the web app.** On 26 Nov, users whose DNS blocks onrender.com couldn't use the app at all. **Instead:** the web app uses `/api` on its own address (`vercel.json` + `ApiConfig.resolveBaseUrl`); don't switch it back. Phone builds will need our own domain (NEXT_STEPS step 10).
- **Don't just write down a fault that can hit real users.** The DNS fault was seen and noted on 20-21 Nov; five days later real users were locked out. Fix it, or tell the owner plainly that users are at risk.
- **Don't blame Render or CORS for "can't reach the server" before checking DNS** (`dig <host>` vs `dig @8.8.8.8 <host>`).
- **Don't remove the step that copies `vercel.json` into `build/web`** in `deploy.yml`. Without it, `/u/<name>` (and now `/api`) were 404 on Vercel.
- **Don't assume a local `flutter build web` proves CI will pass.** CI used to install the newest stable Flutter. On 14 Nov a newer Dart broke `camera_web` and a deploy failed. The version is now pinned in `deploy.yml` (`flutter-version: '3.50.1'`; pin added 26 Nov, pushed 28 Nov in `d782e01`). Don't remove the pin; upgrade it on purpose (NEXT_STEPS step 4). Check the workflow result after every push either way.
- **Don't remove the "SUPABASE_ANON_KEY is missing" check** in `deploy.yml`. Without the key, the build ships an app that only shows "Supabase not configured".
- **Don't assume Render follows `render.yaml`.** It says Frankfurt; DNS points at Oregon. Check the dashboard.
- **Don't "confirm" a backend deploy with an existing route.** It can't tell old code from new. Use a new route (401 vs 404) or the Render dashboard.
- **Don't make a scheduled (cron) route do its work before it answers.** cron-job.org gives up after **30 seconds** ("Failed (timeout)") and **switches the job off by itself after about 25 failures in a row**. Render's free server alone takes 30-60 s to wake up. The reminder job did all its work first, and the owner found it "failed to work" (28 Nov). **Instead:** answer `202` at once and do the work in a `BackgroundTasks` task that opens its **own** session (`async_session_maker()`; the request's `db` is closed by then), as `/notifications/cron/streak-reminders` does since backend `a269582`. Schedule it **every 10 minutes**, so the server never falls asleep and the call never waits for it to wake. Protect the work with a once-per-hour guard (`_hour_done`). A `202` from a cron route is success, not an error.
- **Don't send an announcement push without the preview first.** The first preview reached 0 people (nobody had turned on browser notifications). A dry run would use up the once-only key, so a real send is refused unless web push is on.
- **Don't expect push on phones.** There is no Apple/Firebase sender and no app plugin; only browser push works.

### 9.7 Tools, tests and assets

- **Don't run `dart format` on existing files.**
- **Don't write tests that depend on today's date** (one broke two days after it was written).
- **Widget tests:** assigning `debugDefaultTargetPlatformOverride` directly trips Flutter's check. Use `variant: TargetPlatformVariant.only(TargetPlatform.iOS)`; without it, text using `AppType` tries to download Google Fonts and fails.
- **Screenshot renders (golden trick) are the opposite:** don't use the iOS variant there (text turns into blocks). Load a system font with `FontLoader` under the names `NunitoSans_regular`, `_500`, `_600`, `_700`, `_800`, plus `packages/cupertino_icons/CupertinoIcons`. google_fonts then fails the test after the PNG is written; the PNG is still fine. Delete the throwaway test and PNGs afterwards.
- **Don't pump once for a long time** (`pump(1s)`): animations and route changes don't finish. Pump in 100 ms steps. Timers created inside `runAsync` aren't driven by `pump`.
- **Don't wrap `CupertinoApp` in a `MediaQuery`** to set the size. Use `tester.view.physicalSize`. Don't put `SectionHeader` inside a `Row` (it expands); use its `trailing:` slot.
- **Don't keep a Python venv in a temporary or scratch folder.** It disappears. Use the repo's `.venv`.
- **Don't name a Pydantic field `date` next to the `date` type.** It shadows it; import `date as date_type`.
- **Don't ask an image generator for "layered logo asset sheets".** The ChatGPT/Gemini ones were unusable: fake checkerboard transparency, grey smears, misaligned layers. The WhatsApp copy of the logo was too small. **Instead:** crop from the client's high-resolution `Gemini_Generated_Image_*.jpeg` (in the backend folder, never committed).
- **Don't use these colours from the client's first colour spec:** `#9CA3AF` for inactive tabs, cyan or yellow text on white, `#FF6B00` text on white. They fail the contrast tests in `test/theme_mode_test.dart`.
- **Long commands:** `flutter build web` and `flutter test` take about 2 minutes and hit 2-minute tool timeouts; run them in the background. Some agent tools block a plain `sleep`; loop on a check instead.
- **Don't keep editing files while a full `flutter test` runs in the background.** It compiles each test file only when it reaches it, so a half-finished edit shows up as `Compilation failed` in some unrelated test (28 Nov 2026: `language_test.dart` "failed" because `settings_screen.dart` was mid-edit). That isn't a real failure. **Instead:** finish all edits, then run the full suite, and read the error before believing a red result. Before a commit, the last full run must have started *after* the last edit.

---

## 10. Environment gotchas (this laptop)

- The **owner's home network's DNS cannot resolve `*.onrender.com`** (router `192.168.100.1`). Use the `/api` address or `--resolve` (§8).
- `gh` (GitHub CLI) is not installed. Use the GitHub REST API with `curl` (public repos).
- Local Python is 3.14; Render runs 3.13.5. Use the repo's `.venv`.
- Local Flutter is 3.47.7; the deploy builds with 3.50.1 (pinned in `deploy.yml`). The deploy only builds (it runs no tests); the tests have only run here on 3.47.7. To match the deploy exactly, run `flutter upgrade` (not done; it could change `flutter analyze` results, so run analyze and the tests after).
- `flutter doctor` crashes (stale Android Studio path; handover M1). Web builds and tests work.
- No Mac: iOS can only be built in the cloud (Codemagic or a GitHub macOS runner).
- `flutter build web --release` takes about 2 minutes; `flutter test` about 2 minutes.
- USDA's public `DEMO_KEY` allows only a few calls before rate limiting.

---

## 11. Where things are (quick map)

Backend: `app/routers/` (routes), `app/services/` (logic), `app/models/` (tables), `app/schemas/` (shapes), `app/i18n/` (languages), `migrations/` (SQL for the owner), `tests/`, `render.yaml` + `Procfile` (deploy), `scripts/` (`generate_vapid_keys.py`; `list_routes.py` prints every endpoint, see REFERENCE.md §5). Settings, tables and endpoints: `REFERENCE.md`.

App: `lib/main.dart`, `lib/screens/auth_gate.dart` (sign-in routing), `lib/services/server_handshake.dart` (start-up check, waking screen), `lib/screens/main_shell.dart` (tabs: Today, Workouts, Friends, Recipes, Profile), `lib/screens/dashboard_screen.dart` (Today), `lib/providers/food_log_provider.dart` (saving food), `lib/l10n/` (translations), `lib/theme/`, `web/` (index.html, manifest, privacy/terms pages, push worker), `vercel.json` (rewrites, including `/api`), `.github/workflows/deploy.yml`.

Full file maps: handover §5 (older) and the dated sections at the bottom.
