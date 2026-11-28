# NuStreak: what to do next, step by step

Written 26 Nov 2026. Read `AGENTS.md` first (rules and habits); this file assumes it. Facts (settings, dashboards, scheduled jobs, what is unproven, decisions D1-D20, tables, endpoints) are in `REFERENCE.md`. Do the steps **in order** unless the owner picks another. Each step says who does it, what to change (with code), how to test, and when it is done. Code below is a **suggestion written from reading the code**: check names against the files before pasting, and run the tests.

When you finish a step: tick it here (`✅` + date + commit id), add a dated section at the bottom of `handover.md`, and tell the owner.

---

## Where things stand (28 Nov 2026)

- **28 Nov, fourth round: the AI coach (owner: "make sure the ai coach streams answers back char by char ... its answers cut off mid sentence ... add a loading or thinking ... make it more fun and more coach like").** Backend `b887ace`, app `1ae15d6`. **Pushed and seen live 28 Nov:** the new route `/api/coach/messages/stream` went from 404 to 401 about 90 s after the push (backend `b887ace` or later running); app deploy run `46150129723` green, the stream route and the thinking lines (English, German, Spanish checked) are in the live `main.dart.js`, Supabase sign-in answers. A streamed answer itself is **not** seen live (needs a signed-in account). No migration. What changed: the coach no longer stops mid-sentence (2,048 tokens instead of 600, which the model's thinking also used; an answer stopped at the limit ends on its last full sentence); a warmer "upbeat coach" voice (tone and length lines only, safety rules word for word the same, tested); the answer streams in, a checked sentence at a time, and types out letter by letter; a "thinking" bubble with hopping dots and coach lines ("Lacing up my thinking shoes…") while it works. Details: handover "28 Nov 2026 (fourth round)". **After the push, check it live (REFERENCE.md §2, "Coach streaming").**
- **28 Nov, third round (the four items that needed the owner's yes):** backend `2fd303d`, `e9e8819`, `6530e1f` (`master`), app `acecbfc`, `8fb3710` (`main`). **Pushed and seen live:** the backend's public API description (`/api/openapi.json`) listed the new `sets` field about 80 s after the push; app deploy run `46146983959` green, the new phrases and the new push worker are in the live build, and Supabase sign-in answers. What changed: step 7 (the weekly recap push, wording approved by the owner); step 9b ("Last time: 12" and −/+ rep buttons in the workout player; **needs migration `2026-11-29_movement_sets.sql`, step 2f**, and until it is run everything works as before, without "Last time"); reusing database connections, built but **off** until the owner sets `DB_POOL=queue` on Render (step 2g); the notes (`AGENTS.md`, this file, `REFERENCE.md`, `scripts/list_routes.py`, the skills) are now committed to the backend repo (step 4, items 2 and 5). Details: handover "28 Nov 2026 (third round)". **Owner jobs now: 2e (cron-job.org), 2g (optional speed-up)** (2f, the migration, was run by the owner the same day). Next agent work: none that doesn't need the owner; see "Small things" and the decisions list.
- **Tests (28 Nov, third round):** backend 1,184 pass; app 1,063 pass; `flutter analyze` clean.
- **28 Nov, second round (pushed and seen live):** backend `399fc5d` (`master`; the cron route's GET went from 405 to 403 after the push), app `90ceee8` (`main`; deploy run `46143543846` green, new phrases in the live build, Supabase sign-in answering). No migration. What changed: the cron-job.org reminder job answers at once (202) and also deletes expired bites and stories every hour; step 9a (Easier version in the workout player); a bite in Notifications opens that exact bite; the recipe goal chips start on the person's own goal; a Settings switch hides the Home tiles; deleting a food retries by itself. Details: handover "28 Nov 2026 (second round)". **The owner must change the cron-job.org job (step 2e) or reminders still won't run.** Next agent work: step 9b only if the owner wants it; everything else left needs the owner (steps 0, 2, 3, 7, 10, 11).
- **Tests (28 Nov, second round):** backend 1,151 pass; app 1,056 pass; `flutter analyze` clean.
- **28 Nov, first round:** steps 1, 4 (items 1 and 4), 5, 6 and 8 done and pushed: backend `b896109` (`master`), app `1429c21` (`main`). No migration. Details: handover "28 Nov 2026: five NEXT_STEPS done". **Next agent work, in order: step 9a** (steps 0, 2, 3 need the owner; step 7 needs the owner to approve the wording; step 4 items 2 and 5 need the owner's answer).
- **Pushed and live (26 Nov, older):** backend `c0251a0`, app `efee00a`.
- **Tests (28 Nov):** backend 1,134 pass; app 1,035 pass; `flutter analyze` clean.
- **26 Nov outage fix (live):** the web app now calls the backend through `https://calorie-app-ug.vercel.app/api/...` (`vercel.json` rewrite, `ApiConfig.resolveBaseUrl`, test `test/api_config_test.dart`). Checked from a network that cannot look up onrender.com: health, login header, 6 MB upload, POST/PUT/PATCH/DELETE all reach the backend. **Not checked:** a signed-in person using the app, a real scan, an affected user's phone.
- **Uncommitted (on purpose):** Backend: logo images and zips (never commit them) and `handover.md` (gitignored, never commit it). Everything else is committed since 28 Nov 2026 (third round).
- Everything else built so far is listed in `handover.md` (bottom sections and "OPEN LIST").

---

## Step 0. Confirm the outage is over (owner + agent, today)

1. Ask the owner to send an affected user this:
   > We've fixed the connection problem. Close the app or browser tab completely and open it again. If you still see the error, repeat that once more, then send us a screenshot.
2. If it still fails for them, ask them to open `https://calorie-app-ug.vercel.app/api/health` on the same phone.
   - Shows `{"status":"ok"...}` → their phone reaches the server; they probably still have the old app cached (repeat the close/reopen; on an installed Home Screen app, remove and re-add it).
   - Doesn't load → a different problem between the phone and Vercel; get a screenshot of the exact error.
3. Ask the owner to check **Vercel → the project → Usage** after a few days: all backend traffic from the web app now passes through Vercel (each request counts; on the Hobby plan, "Fast Origin Transfer" has a monthly allowance, 10 GB at last check). Also ask them to read Vercel's terms about commercial use on Hobby (not checked).
4. **If the `/api` route ever has to be undone** (owner approves first):
   ```bash
   cd /home/curtis/calorie_app
   git revert efee00a          # makes a new commit that undoes it
   flutter analyze && flutter test
   git push origin main        # only after the owner says push
   ```
   Undoing it locks out users on networks that block onrender.com again, so only do it if `/api` itself is broken.
5. Vercel gives a forwarded request **120 seconds**. A cold start plus a slow Gemini scan could come close; if the Render log shows a request that took longer, or users get `ROUTER_EXTERNAL_TARGET_ERROR`, note it in the handover.

**Done when:** an affected user confirms they can sign in and log a meal.

---

## Step 1. Allow PUT in the backend's CORS list (agent, 15 minutes)

✅ 28 Nov 2026, backend `d7cc3a6`, pushed. Seen live: the PUT preflight through `/api` answered 400 before the deploy and 200 after it.

**Why:** `app/main.py` allows `GET, POST, PATCH, DELETE, OPTIONS` but not `PUT`. The app uses `PUT` twice (`house_recipe_service.dart`: saving Highlights `PUT /highlights`, uploading a recipe photo `PUT /recipes/{id}/media/{position}`). Called straight from the browser, the preflight was refused (`400 Disallowed CORS method`, seen 26 Nov). The `/api` route avoids CORS for the live site, but local web development and any future direct call still break.

**Change** `app/main.py`, in `cors_kwargs`:
```python
"allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
```

**Test**, in `tests/test_api.py` next to `test_cors_allows_patch`:
```python
def test_cors_allows_put():
    """Highlights and recipe photos are saved with PUT; a browser asks first."""
    from app.core.config import settings
    from app.main import cors_kwargs

    assert "PUT" in cors_kwargs(settings)["allow_methods"]


def test_a_put_preflight_from_the_app_passes(anon_client):
    r = anon_client.options(
        "/highlights",
        headers={
            "Origin": "https://app.example.com",  # in CORS_ORIGINS set by tests/conftest.py
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
```
Run `.venv/bin/python -m pytest -q`. Commit:
`fix: CORS allows PUT, so saving Highlights and recipe photos works when the browser calls the backend directly (local development, phone-free tests)`.
Ask the owner before pushing. After the push: `curl -s -X OPTIONS -H 'Origin: https://calorie-app-ug.vercel.app' -H 'Access-Control-Request-Method: PUT' -o /dev/null -w '%{http_code}\n' https://calorie-app-ug.vercel.app/api/highlights` must print `200` (this goes through Vercel to the backend).

---

## Step 2. Jobs only the owner can do (agent: send them this list, one item at a time)

**2a. Change `CRON_SECRET` (it was pasted into a chat).**
1. Make a new value on the laptop: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Don't paste it into any chat.
2. Render → `calorie-backend` → Environment → `CRON_SECRET` → paste → Save (Render redeploys).
3. cron-job.org → the hourly job for `/notifications/cron/streak-reminders` → header `X-Cron-Secret` → paste the same value → Save.
4. Next hour, cron-job.org's history should show `200`. `403` = the two values differ; `404` = Render doesn't have it.

**2b. Check that every migration was run.** Paste this into the Supabase SQL editor; every row must say `true`:
```sql
select t.name, to_regclass('public.' || t.name) is not null as ran
from unnest(array[
  'weight_logs','friendships','blocks','notification_prefs','device_tokens','notification_log',
  'snaps','snap_recipients','snap_days','snap_reports','profile_avatars','stories','story_views',
  'content_reports','messages','food_log_nutrients','ai_usage','budget_prefs','recipes',
  'recipe_ingredients','recipe_events','collections','collection_items','recipe_pins','recipe_shares',
  'message_attachments','user_prefs','food_log_estimates','recipe_media','user_language',
  'coach_messages','message_quotes','activity','movement_logs','movement_prefs',
  'snap_caption_positions','story_caption_positions','movement_sets'
]) as t(name)
order by ran, t.name;

-- and the two username columns (2026-11-04_usernames.sql):
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'profiles'
  and column_name in ('username', 'username_changed_at');
```
For each `false`, run the file from `migrations/` that creates it (search the file names: `grep -l "my_table" migrations/*.sql`). The ones most likely missing: `message_quotes` (2026-11-24), `activity` (2026-11-25), `movement_logs` (2026-11-26), `movement_prefs` (2026-11-27). Write the result in the handover.

**2c. Gemini and USDA (handover R8.0).**
- USDA: get a free key at https://fdc.nal.usda.gov/api-key-signup, set `USDA_API_KEY` in Render. Until then search, barcodes, photo matching and the one-tap extras fail or fall back.
- Gemini: check usage in Google AI Studio; set `GEMINI_DAILY_BUDGET` in Render to the free daily request count shown there.
- After both: run the live checks in handover "R8.0 Unblockers" item 3 and write the results there.

**2d. Vercel usage and plan terms** (see Step 0, item 3).

**2e. Fix the cron-job.org reminder job (owner, 5 minutes; added 28 Nov 2026).** The owner said the job "failed to work". Cause found in the code: the job did all its work before answering, and Render alone takes 30-60 s to wake, while cron-job.org gives up after **30 seconds** and **switches a job off by itself after about 25 failures in a row**. Since backend `a269582` the job answers at once with **202** and works afterwards. Send the owner these clicks:
   1. Log in to cron-job.org → **Cronjobs** → open the NuStreak reminder job (URL ends in `/notifications/cron/streak-reminders`).
   2. **URL:** `https://calorie-backend-odc3.onrender.com/notifications/cron/streak-reminders` (the direct Render address is fine here: cron-job.org's own network can look it up; `https://calorie-app-ug.vercel.app/api/notifications/cron/streak-reminders` also works).
   3. **Schedule:** every **10 minutes** (this also keeps the server awake, so users stop seeing the long "Almost there" wait; the work itself still runs only once an hour).
   4. **Advanced → Request method:** GET or POST (both work now). **Headers:** keep `X-Cron-Secret` with the value set in Render (`CRON_SECRET`; if it was changed in 2a, use the new one).
   5. If the job shows as **disabled**, switch it back on. Save.
   6. After 10-20 minutes open the job's **History**: each run should say **202** (that is success; the body is `{"status":"started"}` or `{"status":"already_running"}`). **403** = the secret doesn't match Render's `CRON_SECRET`. **404** = `CRON_SECRET` isn't set on Render. **Failed (timeout)** = the old code is still running (check Render shows `a269582` or later as Live).
   7. Render → the service → **Logs**: once an hour a line `cron job done checked=… sent=… purged=… secs=…`.
   - **Before choosing every 10 minutes**, the owner should check Render's free instance hours (750 a month per workspace at last check; an always-awake service uses about 744). If they run out, Render stops the service until the month ends. That is the step 3 decision.

**2f. Run the migration for "Last time" (owner, 2 minutes; added 28 Nov 2026, third round).** ✅ The owner said on 28 Nov 2026: "i ran the other movement sets migration". Not checked by an agent (only the owner can run the `to_regclass` query in 2b).
   1. Supabase → the project → **SQL Editor** → **New query**.
   2. Paste the whole of `migrations/2026-11-29_movement_sets.sql` (from the backend repo) → **Run**.
   3. The last line of the result must show `movement_sets | true`. It is safe to run twice.
   - Before it is run: workouts still save and open exactly as before; the player just never shows "Last time", and the reps people record are not kept (the server log says `movement_sets: could not save` once per finished workout; that is expected and harmless).
   - After it is run: from the **next** finished workout on, "Last time: N" shows under each rep move done before. Nothing older is filled in.
   - Write in the handover that it was run.

**2g. Optional: make every request about 1 second faster (owner, 3 minutes; added 28 Nov 2026, third round).** The server opens a new database connection for every request (about 1 s each, measured on the live server). Since backend `6530e1f` it can keep a few open and reuse them, but only when the owner switches it on.
   1. Render → `calorie-backend` → **Environment** → **Add Environment Variable** → Key `DB_POOL`, Value `queue` → **Save Changes** (Render redeploys by itself, a few minutes).
   2. Afterwards: open the app, log a food, open Friends and Workouts. The Render log should show `database connections: queue` once per worker at start-up.
   3. **If anything goes wrong** (errors in the app, Render log lines with `prepared statement`, `InterfaceError` or `connection is closed`, many 500s): Render → Environment → delete `DB_POOL` → Save. That switches back to how it ran until 28 Nov (a new connection per request). No code change needed.
   - It was load-tested only against a local copy of the same kind of pooler (PgBouncer in transaction mode), **never against Supabase's real pooler**. Watch the first hour.
   - Leave `DB_POOL_SIZE` unset (3 kept-open connections per worker, plus up to 10 short-lived extra ones in a burst).

---

## Step 3. Stop the long "Almost there" wait (owner decides; 10 minutes)

**Why:** the users' screenshot shows 81 seconds waiting. Render's free tier sleeps after ~15 idle minutes. The hourly reminder job wakes it once an hour, but not in between.

**Since 28 Nov 2026 Option A needs no new job:** set the existing reminder job to every 10 minutes (step 2e). Older wording, kept for history: **Option A (free):** cron-job.org → new job → `GET https://calorie-backend-odc3.onrender.com/health` every 10 minutes. This keeps the server awake around the clock. **The owner must first check in the Render dashboard how many free instance hours the account gets each month and what happens when they run out** (not checked here; an always-on service uses about 720-744 hours a month).
**Option B (paid):** move the Render service to a paid instance (no sleeping). Owner decision.
**Option C:** do nothing; the app already shows a friendly waiting screen and retries for 100 s.

No code change for A or B. Write the decision in the handover.

---

## Step 4. Housekeeping (agent, 5 minutes)

1. ✅ 28 Nov 2026, app `7e65d44`, pushed. App: commit the generated plugin file (it changed when `wakelock_plus` and `package_info_plus` were added; it only matters for macOS builds):
   ```bash
   cd /home/curtis/calorie_app
   git add macos/Flutter/GeneratedPluginRegistrant.swift
   git commit -m "chore: regenerated macOS plugin list (wakelock_plus, package_info_plus)"
   ```
   It goes out with the next app push; it changes nothing on the web.
2. ✅ 28 Nov 2026 (third round): the owner chose "GitHub, without handover". `AGENTS.md`, `NEXT_STEPS.md`, `REFERENCE.md`, `scripts/list_routes.py` and the three skills are committed to the backend repo; `handover.md` stays only on this laptop (gitignored). Older text: `handover.md`, `AGENTS.md` and `NEXT_STEPS.md` exist only on this laptop. Ask the owner whether to (a) commit `AGENTS.md` and `NEXT_STEPS.md` to the backend repo, or (b) copy all three to their Google Drive. **Check first whether the GitHub repos are public** (`curl -s https://api.github.com/repos/Curtis-18/calorie_backend | grep '"private"'`): the handover names internal plans and decisions, so it shouldn't go into a public repo.
3. Don't commit the logo images in the backend folder.
4. ✅ 28 Nov 2026, app `d782e01`, pushed (3.50.1 was also the newest stable that day). **Pin the Flutter version of the deploy** (prepared 26 Nov, waiting for the owner's OK). `.github/workflows/deploy.yml` now has `flutter-version: '3.50.1'` under the Install Flutter step (3.50.1 is what built every deploy since 20 Nov, including the live one). Why: an unpinned "stable" broke a deploy on 14 Nov (AGENTS.md §9.6). If the owner says yes:
   ```bash
   cd /home/curtis/calorie_app
   git diff .github/workflows/deploy.yml          # only the pin and its comment
   git add .github/workflows/deploy.yml
   git commit -m "fix: the web deploy builds with a fixed Flutter version (3.50.1, what built the live app) instead of whatever is newest, so a new Flutter release can't break a deploy overnight"
   ```
   After the owner says "push": push, then check the workflow run ends `completed success` (AGENTS.md §4.5). If it fails at "Install Flutter", the version string is wrong: compare with https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json.
   **Upgrading Flutter later:** pick the version, run `flutter upgrade` (or install that version) locally, run `flutter analyze`, `flutter test`, `flutter build web --release`, change the pin, push, check the workflow.
5. ✅ 28 Nov 2026 (third round), see item 2. **Back up the notes.** `REFERENCE.md`, `scripts/list_routes.py` and the skills in `.claude/skills/` (`read-the-codebase`, `what-to-look-out-for`, `investigate-a-problem`) are new (26 Nov). If the owner agrees to commit the notes, add them by name (`git add .claude/skills/read-the-codebase/SKILL.md ...`, never `git add .claude`) with `AGENTS.md` and `NEXT_STEPS.md`; `REFERENCE.md` holds no secrets but describes unreleased plans and the client decisions, so the owner decides (the repos are public).

---

## Step 5. Drinks: "per 100 ml" read as grams (handover N6) (agent, half a day)

✅ 28 Nov 2026, backend `abecc2d`, app `ded8a38`, pushed. 5.1 checked live: USDA Branded orange juice says `"servingSizeUnit": "ml"`; Open Food Facts marks products sold by volume with `"product_quantity_unit": "ml"` (a 330 ml cola), so both set `per_unit`. The saved name is "ORANGE JUICE (250ml)" and the edit sheet keeps ml. **Not changed:** photo scans (Gemini estimates grams; a matched drink is still read per gram, about 4% off for juice) and recipe ingredients (grams). **Not verified live:** a signed-in search for a drink (needs a test account and a working USDA key).

**Problem:** USDA "Branded" foods that are liquids give nutrients per **100 ml**, but the app asks for **grams** and calculates as if they were per 100 g. For water-based drinks the error is small; for oil it's about 10%.

**Plan (no density table needed):** tell the app which unit the numbers are per, and let the person type millilitres for those foods. The saved entry only stores calories and macros, so nothing changes in `food_logs` and **no migration is needed**.

**5.1 Check a real response first.** USDA search results for Branded foods should carry `servingSizeUnit` (values like `ml`, `MLT`, `g`, `GRM`). Confirm with the public demo key (a few calls only):
```bash
curl -s "https://api.nal.usda.gov/fdc/v1/foods/search?api_key=DEMO_KEY&query=orange%20juice&dataType=Branded&pageSize=3" \
 | python3 -c 'import sys,json;[print(f["description"],"|",f.get("servingSizeUnit"),f.get("servingSize")) for f in json.load(sys.stdin)["foods"]]'
```
If the field is missing or named differently, stop and write that in the handover.

**5.2 Backend.**
- `app/models/food.py`, in `FoodSearchResult`:
  ```python
  # What the *_per_100g numbers are per: "g" (100 g) or "ml" (100 ml, USDA
  # Branded liquids). The field names keep "100g" so older apps still work.
  per_unit: str = "g"
  ```
- `app/services/usda_service.py`:
  ```python
  _ML_UNITS = {"ml", "mlt", "milliliter", "millilitre"}

  def _per_unit(food: dict) -> str:
      """Branded liquids are labelled per 100 ml; everything else per 100 g."""
      unit = str(food.get("servingSizeUnit") or "").strip().lower()
      return "ml" if food.get("dataType") == "Branded" and unit in _ML_UNITS else "g"
  ```
  and add `per_unit=_per_unit(food),` in `_result_from_food`.
- Open Food Facts barcodes (`app/services/openfoodfacts_service.py`) build the same result: check whether OFF says its numbers are per 100 ml for drinks (its product JSON has a `nutrition_data_per` field) and set `per_unit` the same way, or leave `"g"` and note it.
- Tests in `tests/test_external_services.py`: Branded + `"ml"` → `"ml"`; Branded + `"MLT"` → `"ml"`; Branded + `"g"` → `"g"`; Foundation food → `"g"`; field missing → `"g"`.

**5.3 App.**
- `lib/models/food_item.dart`: add `final String perUnit;` (default `'g'`) and in `fromApiJson`: `perUnit: json['per_unit'] == 'ml' ? 'ml' : 'g',` (anything else, or an old backend, = grams).
- Find the amount dialog: `grep -n "parseGrams" lib/screens/food_search_screen.dart lib/widgets/edit_entry_sheet.dart lib/screens/photo_review_screen.dart`. Where the unit label `g` is shown for a `FoodItem`, show `ml` when `item.perUnit == 'ml'`. The maths stays the same (`value * per100 / 100`), because the numbers really are per 100 ml.
- If the label is translated text, add the new phrase to all five `lib/l10n/translations_*.dart` files.
- Tests: `FoodItem.fromApiJson` reads `per_unit` and defaults to grams; a widget test that a ml food's dialog shows "ml".

**Order:** backend, then app (an old app ignores `per_unit`). **Done when** a branded juice asks for ml and 250 ml gives 2.5 × its per-100 value.

---

## Step 6. Push notifications for a new badge, a new level and a used streak freeze (agent, 1 day)

✅ 28 Nov 2026, backend `b896109` (plus app `41ec22f` for the settings subtitle "When you earn something new", which broke the same rule), pushed. Built as planned with these choices: one shared loader `app/services/progress_read.py` (GET /progress uses it too); `milestone_events` in `notification_rules.py`; the copy line is chosen with `variant=` (BADGE_LINE/LEVEL_LINE), so no new kinds; order: freeze, badges, level; one sent per person per run, a `duplicate` moves on to the next event; nothing is loaded when both switches are off or it is quiet hours; **weigh-in badges (on_the_scale, check_in_champ) are never announced** (push text is never about weight). **Not verified live:** a real browser notification (needs PUSH_MODE=web on Render and a subscribed browser).

**Why:** the text exists (`Kind.MILESTONE`, `Kind.STREAK_FREEZE` in `app/services/notification_rules.py`) but nothing sends it. Badges and levels are **worked out when read** (`compute_progress`), never stored, so the hourly job must compare.

**6.1 Fix the wording first** (it breaks the "no earn" rule). In `_COPY[Kind.MILESTONE]` change `("🏅 New badge: {name}", "You earned it. Come and see.")` to `("🏅 New badge: {name}", "Come and see it in your progress.")`. The English text is the key in the translation tables, so in **each** of `app/i18n/es.py fr.py de.py pt.py it.py` find the line whose key is `"You earned it. Come and see."`, change the key to the new English, and rewrite the translation. `tests/test_languages.py` tells you if one is missed. Add the new text to the banned-word test in `tests/test_notifications.py` if it lists phrases.

**6.2 Load progress once per person in the hourly job.** In `app/routers/notifications.py`, `_logging_state` already loads the person's food logs and calls `compute_progress` without targets. Add a helper that returns the whole result, with targets (copy the queries from `app/routers/progress.py::get_progress`, including weigh-in dates in a savepoint):
```python
async def _progress_for(db: AsyncSession, uid: uuid.UUID, today, lang: str) -> dict:
    rows = [LogRow(*r) for r in (await db.execute(
        select(FoodLog.log_date, FoodLog.meal_type, FoodLog.source, FoodLog.calories, FoodLog.protein_g, FoodLog.timestamp)
        .where(FoodLog.user_id == uid, FoodLog.log_date <= today)
    )).all()]
    target = (await db.execute(select(Target.calorie_target, Target.protein_g).where(Target.user_id == uid))).first()
    # weigh-ins: same savepoint read as get_progress
    ...
    return compute_progress(rows, today=today, calorie_target=target[0] if target else None,
                            protein_target=target[1] if target else None, weigh_in_dates=weigh_ins, lang=lang)
```
Better: move the shared loading out of `routers/progress.py` into a function in `app/services/progress_service.py` (e.g. `async def load_progress(db, user_id, today, lang)`) and call it from both places, so the screen and the notification can never disagree.

**6.3 Decide what is new**, as a pure function in `notification_rules.py` (easy to test):
```python
MILESTONE_WINDOW = (10, 20)   # local hours; quiet hours still apply on top

def milestone_events(today_progress: dict, yesterday_progress: dict, today: date) -> list[tuple[Kind, str, dict]]:
    """(kind, dedupe key, copy values) for what happened today. Positive news only."""
    events = []
    for a in today_progress["achievements"]:
        if a["unlocked"] and a["unlocked_on"] == today:
            events.append((Kind.MILESTONE, f"badge:{a['id']}", {"name": a["title"]}))
    level_now, level_before = today_progress["level"]["level"], yesterday_progress["level"]["level"]
    if level_now > level_before:
        events.append((Kind.MILESTONE, f"level:{level_now}", {"count": level_now}))
    yesterday = today - timedelta(days=1)
    if yesterday in today_progress["streak"]["frozen_days"]:
        events.append((Kind.STREAK_FREEZE, f"freeze:{yesterday.isoformat()}", {"count": today_progress["streak"]["current"]}))
    return events
```
`yesterday_progress` = the same loader with `today - 1 day` (logs after that day are ignored by `compute_progress`).
Copy choice: `copy_for` picks one variant by hash, but the badge line and the level line need different values. Simplest: split `Kind.MILESTONE` copy so the badge and level texts are chosen explicitly (e.g. a `variant` index in the event, or two new kinds `BADGE` and `LEVEL_UP` mapped to the `milestones` switch in `_SWITCH`; **no migration**, because the switch already exists).

**6.4 Send them** in the hourly loop (`streak_reminders`), inside its own `try/except` with `await db.rollback()` like the other blocks, only when `in_window(local.hour, MILESTONE_WINDOW)`, at most one milestone message per person per run (the daily cap still applies):
```python
for kind, key, values in milestone_events(now_p, before_p, local.date())[:1]:
    counted(await notify(db, uid, kind, dedupe_key=key, now=now, **values))
```
Note: `notification_log` rows are deleted after 7 days (`LOG_KEEP`), so a dedupe key only protects for 7 days; that is fine here because events only count on the day they happen.

**6.5 Tests** (`tests/test_notifications.py`): a badge unlocked today → one event; unlocked yesterday → none; level up → event; frozen yesterday → freeze event; the copy has no banned words in any language; the cron sends at most one and respects quiet hours (existing fakes show how).

**Done when** a test user who unlocks a badge gets one browser notification that day and never again for it.

---

## Step 7. A weekly recap notification (agent, half a day; owner approves the wording first)

✅ 28 Nov 2026 (third round), backend `2fd303d`, app `acecbfc`. The owner approved **both** lines, used in turn by week number (`recap_week` in `app/services/notification_rules.py`: odd ISO weeks get line 2). How it works now: `_send_recap` in `app/routers/notifications.py` runs in the reminder job before the badge/level news; if a recap went out in that run, the badge news waits for the next run (so one run sends at most one of them). The tap opens `/?shortcut=insights`: the push data carries `"url"` (`LINKS` in `notification_rules.py`), and `web/push/sw.js` opens it only if it is on the app's own site; an already-open app tab is just brought forward. Never seen live (REFERENCE.md §2). Older text below, kept for history:

**28 Nov 2026: asked; the owner did NOT approve the wording (they answered about cron-job.org instead). Do not build this until they say yes to the exact text below.**

- New kind `WEEKLY_RECAP = "weekly_recap"` in `Kind`, mapped to the existing `milestones` switch in `_SWITCH` (no migration).
- Sent on **Sunday between 17:00 and 19:00 local**, dedupe key `recap:{iso_year}-W{iso_week}`, only when the person logged on **at least 2 days** that week (never tell someone they logged 0 or 1 days).
- Copy (positive only, check with the owner):
  `("📅 Your week: {count} days logged", "Have a look at your week in Insights.")`, `("🔥 {count} days logged this week", "Nice rhythm. Your weekly summary is ready.")`. Add both to the five `app/i18n/*.py` tables.
- The count: distinct `FoodLog.log_date` values from Monday to today for that person (one small query).
- Tests: Sunday 18:00 → sent once; Saturday → not; 1 day logged → not; second run → duplicate; banned words.
- Opening the notification should land on Insights. The web push worker (`web/push/sw.js` in the app) opens the app; deep-linking to a tab would be an app change (`/?shortcut=insights` already exists, see `services/app_shortcut.dart`): send `{"url": "/?shortcut=insights"}` in the push data and use it in `sw.js`'s click handler.

---

## Step 8. A clearer message when the app can't reach the server (agent, half a day)

✅ 28 Nov 2026, app `1429c21`, pushed. Any answered status other than 200/404/401 counts as `serverError` (not only 5xx: a 403 or 429 also isn't the person's connection). An attempt that the 100 s deadline cuts short does not overwrite what the attempt before it saw (found in testing: a slow server answering errors otherwise ended as "check your connection"). The title "Couldn't reach the server" is unchanged; only the sentence under it changes.

**Why:** `ServerUnreachableView` (`lib/widgets/waking_up_view.dart`) says "It may still be starting up, or your connection dropped" for every failure, including a server that answers with an error.

**Change** `lib/services/server_handshake.dart`: remember what the last attempt saw.
```dart
/// What the last attempt saw, for the message on the "couldn't reach" screen.
enum LastProblem { noAnswer, serverError }

LastProblem lastProblem = LastProblem.noAnswer;
...
// after an attempt:
lastProblem = (status != null && status >= 500) ? LastProblem.serverError : LastProblem.noAnswer;
```
In `auth_gate.dart`, pass `handshake.lastProblem` to `ServerUnreachableView(problem: ...)`, which shows:
- `noAnswer`: the current text.
- `serverError`: "Our server is having a problem right now. Please try again in a few minutes." (new phrase → five translation files).
Tests in `test/server_handshake_test.dart`: a 503 run ends with `serverError`, a timeout run with `noAnswer`; a widget test for each message.

---

## Step 9. Workouts: an easier version of a move, then progress on strength moves (agent, 1-2 days)

**9a. "Easier" swap in the player** (no migration). ✅ 28 Nov 2026, backend `013a387`, app `e0b3b69`. How it works now: `EASIER` in `app/services/workouts.py` maps a move to a gentler move already in the library (or the same move, half as long, never under 10 s); every `play` entry has `"easier": {name, cue, amount, mode, seconds, reps}` or `null`. App: `PlayStep.easier`; `PlayerEngine.toggleEasier()` / `canEase` / `isEased`; the choice is kept by the move's **name**, so the same move in later rounds starts easier too; never saved. Button key `player_easier`, labels 'Easier version' / 'Usual version'. **To add another easier move:** add one line to `EASIER` using ids from `EXERCISES`; the tests check it is a library move and never longer.
- Backend `app/services/workouts.py`: add a map of gentler versions using **only moves already in the library** (examples from it: `knee_pushup` → `wall_pushup`; `reverse_lunge` → `squat`; `plank` → a shorter plank). Put it in each step of the `play` list the API returns, e.g. `"easier": {"name": ..., "cue": ..., "amount": ...}` or `null`. All new phrases go in the five `app/i18n/*.py` tables (the test `tests/test_workouts.py` checks every library phrase).
- App `lib/screens/workout_player_screen.dart` + `lib/services/player_engine.dart`: an "Easier" button on a step that has one; it swaps what is shown for that step only (not saved). Old backends send no `easier`, so the button just doesn't appear.
- Keep the safety line. A test bans "burn" and calorie words (existing tests in `tests/test_workouts.py` show how).

**9b.** ✅ 28 Nov 2026 (third round), backend `e9e8819`, app `8fb3710`. Migration `2026-11-29_movement_sets.sql` run by the owner on 28 Nov (step 2f). How it works now:
- Player: on a rep move, small round − and + buttons (keys `player_reps_minus` / `player_reps_plus`, 1 to 500) change the big number to what the person really did. Under a main-part rep move done before: "Last time: N" (key `player_last`).
- Only **main-part** rep moves finished with **Done** are kept (`PlayerEngine.sets`); skipped moves, warm-up, cool-down and timed moves are not. The easier version is kept under its own move id (a wall push-up, not a knee push-up).
- Saving: `POST /movement` gets `"sets": [{"move": "squat", "reps": 12}, ...]` (only for a guided workout, only on the first save of that id; at most 100; moves not in `EXERCISES` are dropped, not refused). Rows go to `movement_sets`, written in a savepoint, so before the migration the workout still saves.
- Opening a workout: `GET /workouts/{id}` returns `"last_reps": {"squat": 12}` (the best set of the most recent session with that move, from the newest 300 rows) and every `play` step has `"move"` (its library id; `null` for rests). Before the migration `last_reps` is `{}`.
- An older app sends no sets; an older backend sends no `move`/`last_reps`, so the app shows no "Last time" and sends no sets.
- Account deletion: rows cascade from `profiles` and from `movement_logs`; no photos.

Older text: **Progress on strength moves** (needs a new table; do after 9a and only if the owner wants it): a `movement_sets(id, user_id, log_id → movement_logs on delete cascade, move, reps, created_at)` table written when a session is saved, and the player shows "Last time: 10" beside a reps step. Follow the optional-table pattern (AGENTS.md §5.3) and the account-deletion rule.

---

## Step 10. A backend address of our own (owner buys a domain; needed before phone apps)

**Why:** phone builds will call `calorie-backend-odc3.onrender.com` directly (the `/api` route is only for the web app), so users on networks that block onrender.com would be locked out of the phone app.

1. Owner buys a domain (any registrar) and decides the name, e.g. `api.nustreak.<tld>`.
2. Render → `calorie-backend` → Settings → Custom Domains → add `api.<domain>`. Render shows a CNAME target.
3. At the registrar: a `CNAME` record from `api` to that target. Wait until Render shows the certificate as issued.
4. Check: `curl -s https://api.<domain>/health`.
5. **Web app:** leave it on `/api` (no change). If you want Vercel to forward to the new name, change the destination in `vercel.json` **and** `ApiConfig.renderHost` together (`test/api_config_test.dart` checks they match).
6. **Phone builds:** build with `--dart-define=BACKEND_URL=https://api.<domain>`. `resolveBaseUrl` passes any non-Render address through unchanged.
7. `vapid_subject` in `app/core/config.py` defaults to the onrender address; it can stay.

---

## Step 11. iPhone app release path (needs the owner's Apple account; follow handover §7)

In order:
1. Owner: Apple Developer Program account; choose the **permanent bundle ID** (e.g. `com.<company>.nustreak`).
2. Agent: replace `com.example.calorieApp` in `ios/Runner.xcodeproj/project.pbxproj` (6 places, including `RunnerTests`) and, for Android later, `com.example.calorie_app` in `android/app/build.gradle.kts` (`namespace`, `applicationId`) plus the Kotlin package folder.
3. Step 10 (own backend domain) must be done first.
4. Codemagic: connect the GitHub repo, App Store Connect API key for signing, build with `flutter build ipa --release --dart-define=SUPABASE_ANON_KEY=... --dart-define=BACKEND_URL=https://api.<domain>` (variables stored encrypted in Codemagic), upload to TestFlight.
5. **Sign in with Apple** before submitting (Apple rule 4.8, because Google sign-in exists). Google stays hidden in the iOS build until then (`googleSignInAvailable()` in `lib/services/google_auth.dart`).
6. Phone push: Firebase project + APNs key, `firebase_messaging` in the app, a provider in `app/services/push_sender.py`, `PUSH_MODE` in Render, `NotificationPrefs.pushLive = true`. Handover "Notifications" section lists the steps.
7. Already done: camera, microphone, speech and photo-library usage texts in `Info.plist`; portrait only on iPhone; account deletion; Privacy and Terms pages.
8. Still needed for review: App Privacy labels (photos to Google Gemini, coach messages to Gemini, food logs, weight, date of birth, email), a demo account for Apple's reviewers, screenshots, a TheMealDB supporter key or removing Browse (handover M8, decision D13), a dietitian review (D19) and a native-speaker review of translations.
9. Then home-screen widgets (handover R8.10) and Android.

---

## Waiting on a decision: do NOT build these until the owner answers

The full list with each decision's status is `REFERENCE.md` §3. (Fixed 26 Nov: the handover used D13 and D14 twice; the newer dietitian-review and cycle-data decisions are now **D19** and **D20**.) Old note, kept for history: in the R6 list D13 = TheMealDB licence, D14 = first markets; in the newer R8.11-R8.18 section D13 = dietitian review, D14 = cycle/condition data privacy, D15 = rewards. When you ask the owner, describe the decision in words, not just the number.

- Pods / close-friends list (D9, D18); protein stickers (D3); one camera for log and share (D2); guessing game (D16); pair-streak rules (D17).
- Pro tier and billing (R8.6): needs the Apple account and good retention numbers.
- Scanners for fridge/menu/receipts (R8.7), creator payouts (R8.8, needs a lawyer).
- Meal ideas for medical conditions or the cycle (R8.15): dietitian and privacy decisions first.
- "Feel-good foods" (R8.16), exclusive rewards (R8.18).
- Healthy desserts and drinks catalogue (R8.12): content work; our own recipes with numbers from USDA ingredients.
- Low-intake check-in: wording needs a dietitian.
- **Parked by the owner:** smarter AI recommendations (R9.5): "don't build it yet".
- **Not wanted as written (R8.19 "Held or refused"):** calorie guessing on friends' meals, "log to unlock", a permanent photo grid on profiles.

## Small things that can be done any time (ask the owner first)

- ✅ 28 Nov 2026, app `90ceee8`: deleting a food retries by itself (timeout, dropped connection, 5xx; never another 4xx). It uses the same `_sendWithRetry` as saving, with `done: {204, 404}`.
- ✅ 28 Nov 2026, backend `399fc5d` + app `32a0c64`: tapping a **bite** line in Notifications opens that exact bite while it is still in the inbox. The backend sends `snap_id`, read from the `snap:<id>` dedupe key (no new column). Reactions, expired bites, and lines from before 28 Nov still open Friends. Bites from before the activity table existed are still not in the list at all.
- ✅ 28 Nov 2026, app `e7a4aae`: the recipe goal chips start on the person's own goal (`recipeGoalFor`, `ownRecipeGoalProvider`); All is one tap away; nothing saved.
- ✅ 28 Nov 2026, app `79268d3`: Settings → Today screen → "Bites and messages" switch (`DisplayPrefs.showHomeTiles`, device key `today_show_home_tiles`, on by default).
- ✅ 28 Nov 2026 (third round), backend `6530e1f`: reusing database connections instead of `NullPool` (saves ~1 s a request) is built **behind the `DB_POOL=queue` setting, off by default**. The owner switches it on (step 2g). Load-tested against PgBouncer in transaction mode, not against Supabase's real pooler.
