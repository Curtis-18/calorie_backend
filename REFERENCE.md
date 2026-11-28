# NuStreak: reference facts (settings, accounts, endpoints, tables, what is unproven, decisions)

Written 26 Nov 2026. `AGENTS.md` says **how** to work and `NEXT_STEPS.md` says **what** to do next. This file holds the **facts** an agent can't see from the code alone:
- the settings and dashboards that live outside git;
- every backend endpoint and database table;
- what has never been seen working live;
- the decisions still waiting on the client.

**No secret values are in this file, and none may ever be added.** Names of settings only.

1. [Settings, accounts and scheduled jobs](#1-settings-accounts-and-scheduled-jobs)
2. [Never seen working live](#2-never-seen-working-live-assume-unproven-until-checked)
3. [Decisions waiting on the owner or client](#3-decisions-waiting-on-the-owner-or-client-d1-d20)
4. [Database tables and photo storage](#4-database-tables-and-photo-storage)
5. [Every backend endpoint](#5-every-backend-endpoint-generated-from-the-code)

---

## 1. Settings, accounts and scheduled jobs

### 1.1 Backend settings (Render → the `calorie-backend` service → Environment)

The code that reads them is `app/core/config.py`. Changing one restarts the service. "Set?" says what is known from the handover; **"not confirmed" means ask the owner to look**. An agent cannot see Render.

| Setting | What it does | If it's missing or wrong | Set? |
|---|---|---|---|
| `SUPABASE_URL` | The Supabase project address. Login tokens are checked against its keys. | The server won't start. | Yes (required). |
| `DATABASE_URL` | Postgres through Supabase's pooler. A `postgresql://` string is rewritten for asyncpg automatically. | The server won't start; `/health` says database error. | Yes (required). |
| `USDA_API_KEY` | Food search, barcodes, recipe pricing, one-tap extras. | The server won't start. | **Set, but the key was disabled by USDA on 18 Nov** (`403 API_KEY_DISABLED`). Search and barcodes fail until it is replaced (NEXT_STEPS step 2). |
| `GEMINI_API_KEY` | Photo scans, the coach, the Insights paragraph. Free tier, shared by all users. | The server won't start; scans fail if the quota is spent. | Yes. |
| `GEMINI_MODEL` | Which Gemini model (default `gemini-3.6-flash`). | Default is used. | Not confirmed. |
| `GEMINI_DAILY_BUDGET` | Our own daily cap on Gemini calls for the whole app, so scans aren't starved by the coach/Insights. `0` = no cap. | No cap of our own. | Asked for on 21 Nov; **not confirmed**. |
| `GEMINI_FALLBACK_MODEL`, `GEMINI_FALLBACK_DAILY_BUDGET` | A second model used when the main one's free quota is spent (Google counts quota per model). | No fallback. | Not confirmed. |
| `GEMINI_INSIGHTS` | `false` turns off the AI paragraph on Insights (saves the most calls; the chart stays). | On. | Not confirmed. |
| `SCANS_PER_USER_PER_DAY` | Photo scans one person may do per day. `0` = no limit. | No limit (decision D4). | Not confirmed. |
| `CORS_ORIGINS` | Which websites may call the backend **directly** (comma-separated, `*` allowed, trailing `/` ignored). Default: localhost and `https://calorie-app-*.vercel.app`. | Browser calls from other sites fail. Since 26 Nov the live web app goes through `/api` on its own address, so CORS only matters for local runs and old open tabs. | Not confirmed. |
| `SUPABASE_SERVICE_ROLE_KEY` | Saving and signing photos (bites, stories, avatars, recipe photos), the purge job, and deleting the login when an account is deleted. **Never put it in the app.** | Those photo routes answer 503. Account deletion falls back to deleting the database row. | Most likely set (people send bites); not confirmed. |
| `CRON_SECRET` | Protects the three scheduler routes (header `X-Cron-Secret`). | Those routes answer 404. | Set (5 Nov). **Should be rotated** (NEXT_STEPS step 2). |
| `PUSH_MODE` | `dry_run` (default: only records what would be sent) or `web` (sends browser push). | Nothing is sent. | Set to `web` (21 Nov). |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | Sign browser push. Make a pair with `scripts/generate_vapid_keys.py`. Changing them breaks every existing subscription. | No browser push. | Set (21 Nov). |
| `DB_POOL` | `queue` = keep a few database connections open and reuse them (about 1 s faster per request). Anything else, or unset = a new connection for every request, as before 28 Nov 2026 (`engine_options` in `app/core/database.py`). | A new connection per request (the old, safe way). | **Not set** (28 Nov 2026). The owner may set it (NEXT_STEPS step 2g); deleting it switches back. |
| `DB_POOL_SIZE` | How many connections each worker keeps open when `DB_POOL=queue` (3; at most 10), plus up to 10 short-lived extra in a burst. | 3. | Not set; leave it. |
| `VAPID_SUBJECT`, `PUSH_DAILY_CAP` | Push sender address (a web address, never an email); max pushes per person per day (3). | Defaults. | Defaults. |
| `SNAPS_BUCKET`, `MAX_SNAP_BYTES`, `MAX_AVATAR_BYTES`, `MAX_RECIPE_PHOTO_BYTES`, `MAX_PHOTO_BYTES` | Storage bucket name (`snaps`) and size limits. | Defaults are right. | Defaults. |
| `USDA_BASE_URL`, `OFF_BASE_URL`, `GEMINI_BASE_URL`, `JWT_AUDIENCE` | Outside addresses and the login token audience. | Defaults are right; don't change. | Defaults. |
| `PYTHON_VERSION`=3.13.5, `PYTHONUNBUFFERED`=1 | Set by `render.yaml`. | | Yes. |

For local runs, the same names go in `calorie_backend/.env`, which is gitignored. Never print it, and never commit it.

### 1.2 App build settings (GitHub → `Curtis-18/calorie_app` → Settings → Secrets and variables → Actions)

These are read by `.github/workflows/deploy.yml` at build time and baked into the web app.

| Name | Kind | What it does | If missing |
|---|---|---|---|
| `SUPABASE_ANON_KEY` | secret | The public Supabase key the app logs in with. | **The build stops on purpose** with an error (otherwise it would ship an app that only says "Supabase not configured"). |
| `SUPABASE_URL` | variable | Supabase address. | The default in `lib/config/supabase_config.dart`. |
| `BACKEND_URL` | secret | Backend address. If it names `calorie-backend-odc3.onrender.com`, the published web app still uses `/api` (`ApiConfig.resolveBaseUrl`). | Default: the Render address, which becomes `/api` on the web. |
| `THEMEALDB_KEY` | secret | TheMealDB key for the Recipes Browse tab. | The free test key `1`, which **is not allowed in a public app** (decision D13). |
| `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | secrets | Let the workflow upload the build to Vercel. | The deploy step fails. |

The Flutter version the deploy uses is pinned in `deploy.yml` (`flutter-version`). This laptop runs 3.47.7, and the deploy pin is 3.50.1 (see NEXT_STEPS step 4).

### 1.3 Outside accounts and dashboards

**Owner: fill in the "Login held by" column.** It is not recorded anywhere, and a new agent or developer will need to know whom to ask.

| Service | Used for | Where the important settings are | Login held by |
|---|---|---|---|
| GitHub `Curtis-18` | Both repos. **Both are PUBLIC** (checked 26 Nov). | Repo → Settings → Secrets (1.2); Actions tab for deploy results. | Owner |
| Render | The backend (`calorie-backend`, free plan, auto-deploys `master`). | Environment (1.1), Logs, Events/Deploys (rollback: see AGENTS.md §8.1). `render.yaml` says Frankfurt, but DNS points at Oregon, so the dashboard is the truth. | ? |
| Vercel | The web app `calorie-app-ug.vercel.app`, and the `/api` forwarding to Render. | Deployments (rollback), Usage (Hobby includes 10 GB "Fast Origin Transfer"; all API traffic now counts). | ? |
| Supabase `pbancnuceteomuyybrlb` | Database, logins, photo storage. | SQL Editor (migrations); Authentication → URL Configuration (Site URL and Redirect URLs, needed by password reset and Google sign-in); Authentication → Providers → Google; Storage → bucket `snaps` (private). | ? |
| Google Cloud / AI Studio | The Gemini key (quota visible in AI Studio); the OAuth client for "Continue with Google" (set up 21 Nov). | AI Studio → API keys / usage; Cloud Console → APIs & Services → Credentials. | ? |
| USDA FoodData Central (api.data.gov) | Food data. The key in use is **disabled**; a new one is free. | fdc.nal.usda.gov → API key signup. | ? |
| cron-job.org | Runs the hourly streak reminders (1.4). | The job list. | ? |
| TheMealDB | Browse tab recipes (test key). | Paid supporter key needed before launch (D13). | ? |
| Open Food Facts | Barcode fallback. No key or account. | n/a | n/a |

### 1.4 Scheduled jobs (the backend never runs anything on a timer by itself)

| Job | Route | How often | Status |
|---|---|---|---|
| Reminders, badge/level/freeze news, the Sunday weekly recap (17:00-19:00 local, from 28 Nov third round) (and, from 28 Nov, deleting expired bites and stories) | `GET` or `POST https://calorie-backend-odc3.onrender.com/notifications/cron/streak-reminders` with header `X-Cron-Secret` | **Every 10 minutes** (asked of the owner 28 Nov; was hourly) | Created on cron-job.org by the owner on 5 Nov. **28 Nov: the owner said it "failed to work".** Cause found: cron-job.org waits only 30 s and switches a job off after about 25 failures in a row; Render's free server takes 30-60 s to wake and the old route did all its work before answering. Fixed in backend `a269582`: the route answers `202 {"status":"started"}` at once and works in the background, at most once per UTC hour. **A 202 is success.** The result of each run is only in the Render log: `cron job done checked=N sent=M secs=S`, or `cron job failed` with a traceback. |
| Delete expired bites and stories (photos and rows) | `POST .../snaps/purge` with header `X-Cron-Secret` | Not needed any more | **Since backend `0ad060c` (28 Nov) the reminder job above does this every hour** (`_purge_expired_photos` in `app/routers/notifications.py`; the log line `cron job done ... purged=N`). It skips itself when photo storage is not set up (`SUPABASE_SERVICE_ROLE_KEY` missing). Expired ones are also still cleaned up when someone opens their inbox or the stories feed. A separate `/snaps/purge` job is harmless if one exists. |
| "What's new" announcement push | `POST .../notifications/cron/announce` | By hand, once per release | Always do the preview (`"send": false`) first (AGENTS.md §9.6). |

cron-job.org calls onrender.com directly, and that's fine: its own DNS can reach Render. If `CRON_SECRET` is rotated, update the header in every job.

---

## 2. Never seen working live (assume unproven until checked)

These are built and covered by tests with fakes, but **nobody has seen them work against the real services or on a real device.** If a user reports a problem in one of these areas, suspect the real-world part first.

**General rule:** most backend database code is tested only against fake databases. A few features were also run against a real Postgres 16 in Docker (micronutrients, account deletion, avatars and stories). Everything else has only been exercised by real users. If something fails only in production, read the SQL first.

| Area | What has not been seen | How to check it | Who |
|---|---|---|---|
| **26 Nov `/api` fix** | A signed-in person using the app through `/api`; a real scan through it; an affected user's phone. | Log in on the live site from the home network, log a food, scan a photo. | Owner (or agent with a test account) |
| Which backend commit is live | The latest pushed is `6530e1f` (28 Nov 2026, third round). Seen live from outside: the public API description (`https://calorie-app-ug.vercel.app/api/openapi.json`) started listing `MovementIn.sets` about 80 s after the push, which proves `e9e8819` or later is running; Render deploys the newest commit of a push, so it should be `6530e1f`. (Before that: `399fc5d`, proven by the cron route's GET changing from 405 to 403.) **The API description is the easiest marker:** when a push adds a field or route, check it there before and after. **How to check a backend deploy without the dashboard:** find a behaviour the new code changed (a new route answers 401 instead of 404, a method now allowed answers 403/401 instead of 405) and curl it before and after the push. | Render → Events: `6530e1f` should be "Live". | Owner |
| Migrations | Whether every migration has been run, especially `2026-11-24_message_quotes`, `2026-11-25_activity`, `2026-11-26_movement`, `2026-11-27_movement_prefs` and **`2026-11-29_movement_sets`** (new 28 Nov, third round; NEXT_STEPS step 2f) (`2026-11-28_caption_positions` is confirmed). | The `to_regclass` query in NEXT_STEPS step 2. | Owner |
| Photo scans after 20 Nov | A real scan with the "thinking" limit. | Render log after a scan: `gemini_call kind=scan ...` and `scan_done status=ok`, and **no** `gemini rejected thinkingConfig`. | Owner + agent |
| Scan speed | The p50/p95 timings and the matched share were never measured. The "lightweight preview" decision waits on them (R8.1 1a). | A week of `scan_done` lines from the Render log. | Owner sends logs |
| AI coach | Real answers, the `system_instruction` field against the live API, how often the safety filters wrongly refuse; whether meal-swap and workout cards use exact titles. | Talk to the coach; read `coach reply rejected` / `coach_care_reply` log lines. | Owner |
| Coach streaming (28 Nov 2026) | Never seen live. (1) Gemini's `streamGenerateContent?alt=sse` format was read from Google's API list, not checked against a real answer (no Gemini key on the laptop). If it differs, the server still answers, because an empty stream counts as a broken reply and the second attempt is asked in one piece. But every message then costs **two** Gemini calls, and the Render log shows `coach reply rejected (attempt 1/2): empty` on most coach messages. (2) Whether Vercel's `/api` forwarding passes the stream on as it comes or holds it to the end. Either way the app works; held to the end, the text only starts typing when the answer is complete. (3) The new tone, and no more cut-off answers. | Send the coach a few messages on the live site. Words should start appearing within a few seconds, before the answer is finished. Then read the Render log for `gemini_call kind=coach`, `coach reply rejected`, `coach reply cut at the limit` and `coach stream failed`. | Owner (logs), agent |
| Recipes from searched ingredients | `usda_service.get_foods_by_ids` has never run live, and it can't until the USDA key is replaced. | Create a recipe from searched ingredients. | After a new USDA key |
| Photo storage | The Supabase Storage upload/sign/delete calls follow the docs. They were proven only against fakes and real users' bites. Recipe photos are on a new path. HEIC photos get a 415 "couldn't be read". | Send a bite, add a recipe photo, delete an account with photos and check the bucket. | Owner |
| Account deletion | The path that deletes the login through Supabase's admin API (`SUPABASE_SERVICE_ROLE_KEY` set). | Delete a throwaway account; check Authentication → Users. | Owner |
| Password reset | No real reset email has been sent. A link opened in another browser can fail (shows "expired"). | Request a reset on the live site and follow it. | Owner |
| Google sign-in | Works on the web (owner, 21 Nov). Not seen: a brand-new Google account going through onboarding, a second device, inside the installed iPhone web app. Sign in with Apple is not built. | Try each. | Owner |
| Browser push | The permission prompt, subscription, and a push actually arriving (Chrome, Firefox, installed iPhone web app). The first announcement preview reached 0 people. | Turn on notifications in Settings on two browsers, wait for an 18:00–21:00 reminder, or send yourself a preview. Render log: `web push refused, status=`. | Owner |
| Streak reminder job | A run that succeeds on cron-job.org with the 28 Nov fix (`202`), the hourly `cron job done ... purged=N` line in the Render log, and expired bites and stories really being deleted from Storage by the job. | The owner changes the job (NEXT_STEPS step 2e), then reads cron-job.org's History and the Render log. | Owner |
| Notifications → exact bite (28 Nov) | Tapping a real bite line on the live site opening that bite. Every bite line was recorded with the `snap:<id>` key, so older lines work too, but only while the bite itself is still in the inbox (24 hours); after that the tap opens Friends. | Have a friend send a bite, open Notifications, tap the line. | Owner |
| Weekly recap push (28 Nov, third round) | A real recap arriving on a Sunday between 17:00 and 19:00 local, and the tap opening Insights (`/?shortcut=insights`) through `web/push/sw.js`. Needs browser push on, the Badges and levels switch on, at least 2 days logged that week, and the reminder job running (step 2e). | Wait for a Sunday evening with push on; Render log `cron job done ... sent=N`. | Owner |
| "Last time" in the workout player (28 Nov, third round) | Reps really saved to `movement_sets` and "Last time: N" showing in the next workout. Needs the migration (step 2f). The −/+ buttons were only seen in widget tests, not on a phone. | Run the migration, do a strength workout, change a count with + or −, finish, open it again. | Owner |
| `DB_POOL=queue` (28 Nov, third round) | Never run against Supabase's real pooler (Supavisor); load-tested only through PgBouncer 1.26 in transaction mode on a local Postgres 16 (handover "28 Nov 2026 (third round)"). | The owner sets it (step 2g) and watches the app and the Render log for an hour. | Owner |
| Install as an app (PWA) | The real install dialog on Android; Add to Home Screen on iPhone. | Try it. | Owner |
| Device features | Camera live preview, flip and flash (phone and browser); scanning a real barcode; voice note (microphone and speech); keeping the screen awake in the workout player; how it looks in light mode and on an OLED phone. | Use the app on a phone. | Owner |
| Vercel plan | Whether the Hobby plan's terms and limits fit all API traffic going through it. | Vercel → Usage after a week; Vercel's terms. | Owner |
| Brave on iPhone | Sessions lost there; the cause is unknown. | — | Open |
| Numbers never measured or sourced | Restaurant portion factor 1.25; the one-tap extras' USDA ids; the recipe tag and goal thresholds; the eat-back 500 kcal cap. | Need real data or a dietitian (D19). | Owner/client |
| Words | Every translation was written by AI (app tables and `app/i18n/*.py`). The Privacy and Terms pages have had no lawyer review. | Native speakers; a lawyer. | Owner/client |

---

## 3. Decisions waiting on the owner or client (D1-D20)

**Don't build anything in the "Waiting" rows until the owner answers.** When asking, describe the decision in words, not just its number.

**Numbering fix (26 Nov 2026):** the handover had used D13 and D14 twice. The older meanings (TheMealDB licence, first markets) keep those numbers. The newer ones are renamed **D19** (dietitian review, previously "D13") and **D20** (cycle and condition data, previously "D14"), and the handover now uses the new names.

| # | Question | Status | What is built meanwhile |
|---|---|---|---|
| D1 | Open the camera at launch: default, or only a setting? | Waiting | A setting, off by default, phone builds only. |
| D2 | One camera that both logs a meal and shares it, or separate cameras? | Waiting | Separate. |
| D3 | Protein-gram stickers on shared posts? (Allowed by the rules; kcal never is.) | Waiting | Not built. |
| D4 | How many free photo scans per day? | Waiting | `SCANS_PER_USER_PER_DAY` exists (0 = no limit). |
| D5 | Calorie banking (weekly budget): opt-in or default? Week start? Are ±15% and the floor right? | Waiting | Built as opt-in. |
| D6 | Menu scanner: free or Pro? | Waiting | Not built. |
| D7 | Creator payouts: share of revenue, method, minimum payout, who pays, tax forms. Needs a lawyer. | Waiting | Not built. |
| D8 | Do recipe saves count toward creator payouts? | Waiting | Not built. |
| D9 | Pods (small groups): max 8 people and 5 pods each? A group chat in v1? | Waiting | Not built. |
| D10 | Wording of the region hint, and which regions first. | Waiting | A general region hint is built. |
| D11 | Add exercise to the calorie plan ("eat-back")? | **Decided 26 Nov:** opt-in, off by default, at most 50%, at most 500 kcal a day. | Built (`movement_prefs`). |
| D12 | What 30-day retention is good enough to launch Pro? | Waiting | Retention SQL in the handover roadmap (P0.6). |
| D13 | TheMealDB: buy the supporter key or remove Browse? | Waiting (needed before a public launch) | Test key. |
| D14 | Which markets and currencies first? | Waiting | Nothing market-specific. |
| D15 | What is an "exclusive reward": cosmetic only, or Pro days? | Waiting | Not built. |
| D16 | Calorie-guessing game: drop it, or "guess the dish" only? (A kcal guess breaks the rules.) | Waiting | Not built. |
| D17 | Pair streak: keep "a missed day resets it" (current), or add a weekly line? (The mood-chip part was dropped on 22 Nov.) | Waiting | Reset, no grace. |
| D18 | A "close friends" list instead of pods, or as well? | Waiting | Not built. |
| D19 | Which registered dietitian reviews health content (eat-back card and cap, recipe goal thresholds, conditions, feel-good foods) before a store release? | Waiting | Content is general and labelled as not medical advice. |
| D20 | Cycle and condition data: consent text, how long it's kept, privacy policy and store labels. | Waiting | Nothing stored. |

Also waiting, without numbers:
- a native-speaker review of the translations;
- a lawyer for Privacy/Terms;
- the Apple Developer account and the iPhone build;
- a custom domain for the backend (needed before phone apps).

---

## 4. Database tables and photo storage

All tables are in Supabase's `public` schema with row-level security ON and no policies. The backend connects as `postgres` and bypasses RLS, and nobody else can read the tables. Tables with a `user_id` are meant to cascade on account deletion (the pattern in AGENTS.md §5.3; checked on real Postgres for the tables that existed on 14 Nov). Which migration made each table:

| Migration | Tables (what they hold) |
|---|---|
| (initial setup, before `migrations/`) | `profiles` (one per person; `username`, `username_changed_at` were added by `2026-11-04_usernames`), `targets` (calorie/protein targets and body details), `food_logs` (every logged food; `source` is only `manual` or `photo`, **never add a value**), `insights_cache` (the Insights text per day) |
| `2026-11-02_weight_logs_and_rls` | `weight_logs`; turns RLS on for the four initial tables |
| `2026-11-04_friends` | `friendships` (requests and friends), `blocks` |
| `2026-11-05_notifications` | `notification_prefs` (push switches), `device_tokens` (browser push subscriptions), `notification_log` (what was sent; dedupe keys) |
| `2026-11-05_snaps` | `snaps` (bites), `snap_recipients`, `snap_days` (pair-streak days), `snap_reports`; creates the private **`snaps` storage bucket** |
| `2026-11-14_avatars_and_stories` | `profile_avatars`, `stories`, `story_views`, `content_reports` (widen its kind check for any new reportable thing) |
| `2026-11-14_messages` | `messages` (friend chat) |
| `2026-11-14_micronutrients` | `food_log_nutrients` (fibre, sugar, sodium, iron, calcium) |
| `2026-11-18_ai_usage` | `ai_usage` (uses per person, day and feature) |
| `2026-11-18_budget_prefs` | `budget_prefs` (weekly calorie budget, opt-in) |
| `2026-11-18_recipes` | `recipes`, `recipe_ingredients`, `recipe_events` (a quiet record when a recipe is logged) |
| `2026-11-19_collections_and_sharing` | `collections`, `collection_items`, `recipe_pins`, `recipe_shares`, `message_attachments` (recipe cards in chat) |
| `2026-11-20_regional_estimates` | `user_prefs` (where the person mostly eats, for scans), `food_log_estimates` (marks estimated entries) |
| `2026-11-21_recipe_media` | `recipe_media` (recipe cover and slide photos) |
| `2026-11-22_user_language` | `user_language` (the person's app language, for server text and push) |
| `2026-11-23_coach_messages` | `coach_messages` (AI coach chat) |
| `2026-11-24_message_quotes` | `message_quotes` (reply to a specific message) |
| `2026-11-25_activity` | `activity` (the in-app Notifications list: bites and reactions) |
| `2026-11-26_movement` | `movement_logs` (workouts and movement) |
| `2026-11-27_movement_prefs` | `movement_prefs` (the opt-in eat-back share, D11) |
| `2026-11-28_caption_positions` | `snap_caption_positions`, `story_caption_positions` (where the caption strip sits) |
| `2026-11-29_movement_sets` | `movement_sets` (reps of each move in a finished guided workout, for "Last time"; cascades from `profiles` and `movement_logs`) |

The next migration file is `2026-11-30_<what>.sql`. The date is a sequence number, not today's date.

**Photo storage:** one **private** bucket, `snaps`. Photos are reached only through short-lived signed links made by the backend. Paths:
- bites: `<user>/<snap id>.<ext>`
- stories: `<user>/story-<id>.<ext>`
- profile pictures: `<user>/avatar-<random>.<ext>`
- recipe photos: `<user>/recipe-<recipe>-<position>-<random>.<ext>`

Photos **don't** cascade on account deletion, so `app/services/account_service.py` deletes them. Any new kind of photo must be added there and to its test. Photos taken for scans are never stored.

---

## 5. Every backend endpoint (generated from the code)

Regenerate this list after adding routes (paste the output over this section):

```bash
cd /home/curtis/calorie_backend
USDA_API_KEY=x GEMINI_API_KEY=x SUPABASE_URL=https://x.supabase.co \
DATABASE_URL=postgresql+asyncpg://u:p@h/d .venv/bin/python scripts/list_routes.py
```

How to read it:
- "Login yes" means the route needs `Authorization: Bearer <Supabase token>` and answers 401 without it.
- "cron secret" means it needs the `X-Cron-Secret` header.
- Text in brackets is the function name, shown where the function has no docstring.
- From the web app, every path is called as `https://calorie-app-ug.vercel.app/api<path>`.


#### `/`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/` | **no** | (Root) |

#### `/activity`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/activity` | yes | Bites and reactions from friends, newest first, and how many are unseen. Messages and friend requests are not part of this list. Since 28 Nov 2026 each item also has `snap_id` (the bite a "bite" line is about, from its `snap:<id>` dedupe key; `null` for reactions). |
| POST | `/activity/seen` | yes | Opening the Notifications screen: everything so far counts as seen. |

#### `/adjustments`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/adjustments` | yes | The one-tap extras for the photo review screen (oil, butter, dressing...). |

#### `/blocks`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/blocks` | yes | (List Blocks) |
| DELETE | `/blocks/{blocked_id}` | yes | (Unblock) |

#### `/budget`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/budget/prefs` | yes | (Get Prefs) |
| POST | `/budget/prefs` | yes | Change any weekly-budget choice. POST rather than PATCH, like the notification choices, so the CORS method list stays as it is. |
| GET | `/budget/week` | yes | This week's allowance, derived from the logs (nothing is stored). |

#### `/coach`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| DELETE | `/coach/messages` | yes | "Clear conversation": removes the person's whole history with the coach. |
| GET | `/coach/messages` | yes | The newest page, oldest first. Pass `before` (the first message's created_at) for the page before it. An empty thread if the table is missing, so... |
| POST | `/coach/messages` | yes | Store the person's turn, answer it, store and return the answer. |
| POST | `/coach/messages/stream` | yes | **Since 28 Nov 2026.** POST /messages, with the answer arriving while it is written, as server-sent events (`data: {...}` lines): `delta` (checked text, whole sentences), `reset`, `done` (the stored answer, as POST returns it), `error` (the app then asks POST with the same id). Problems before the answer starts are ordinary statuses. The app falls back to POST on a 404 (older server). |

#### `/collections`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/collections` | yes | My collections with the recipes in them. A recipe that was deleted, or a friend's recipe that is no longer shared with me, simply isn't listed. |
| POST | `/collections` | yes | (Create Collection) |
| DELETE | `/collections/{collection_id}` | yes | Delete a folder. The recipes in it are untouched. |
| POST | `/collections/{collection_id}/items` | yes | (Add Item) |
| DELETE | `/collections/{collection_id}/items/{recipe_id}` | yes | (Remove Item) |

#### `/estimate-photo`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| POST | `/estimate-photo` | yes | (Estimate Photo) |

#### `/foods`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/foods/barcode` | yes | A packaged food by its barcode: USDA Branded first, then Open Food Facts (credited in the app). 404 when neither has it. |
| GET | `/foods/search` | yes | Proxies the metered USDA key, so it can't be an open relay. |

#### `/friends`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/friends` | yes | (List Friends) |
| POST | `/friends/requests` | yes | Ask someone (by exact username) to be friends. If they already asked you, this accepts. Repeating a request is harmless. |
| POST | `/friends/requests/{friendship_id}/accept` | yes | (Accept Request) |
| POST | `/friends/requests/{friendship_id}/decline` | yes | Quietly remove a request. The sender is not told. |
| GET | `/friends/search` | yes | Suggestions while typing a username: people whose name starts with what was typed, shortest (closest) first. Never yourself, and never anyone... |
| DELETE | `/friends/{friendship_id}` | yes | Unfriend, or cancel a request you sent. Either side can do it. |
| POST | `/friends/{friendship_id}/block` | yes | Block the other person in a friendship or request: it is removed, and neither of you can find or add the other again until you unblock. |
| POST | `/friends/{friendship_id}/report-photo` | yes | Report the profile picture of a friend or of someone in a request. The team reviews reports in the database. |

#### `/health`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/health` | **no** | Liveness plus a real DB round-trip, so Render restarts us if the pooler dies. |

#### `/highlights`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/highlights` | yes | My pinned recipes, in order. |
| PUT | `/highlights` | yes | Replace my Highlights with these recipes, in this order (at most six, all my own). Repeating the request changes nothing. |

#### `/insights`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/insights` | yes | (Get Insights) |

#### `/logs`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| POST | `/logs` | yes | (Create Log) |
| GET | `/logs/today` | yes | (Get Today Logs) |
| DELETE | `/logs/{log_id}` | yes | (Delete Log) |
| PATCH | `/logs/{log_id}` | yes | Correct a saved entry (a wrong portion, food or meal). The values sent replace the stored ones, so repeating the request after a lost response is... |

#### `/me`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| DELETE | `/me` | yes | Delete the signed-in person's account and all of their data. There is no undo; the app asks them to confirm first. |
| GET | `/me` | yes | Who am I. `username` is None until the user picks one, which is how the app knows to ask. |
| DELETE | `/me/avatar` | yes | Go back to the coloured initial. Harmless if there is no picture. |
| POST | `/me/avatar` | yes | Set or replace your profile picture. |

#### `/messages`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/messages` | yes | Your conversations with current friends, newest first, with how many messages in each you haven't opened. Also what the unread badge uses. |
| GET | `/messages/with/{friend_id}` | yes | The latest messages with a friend, oldest first. |
| POST | `/messages/with/{friend_id}` | yes | Send a message to a friend. Repeating the same request (same id) is harmless: it returns the original. |
| POST | `/messages/with/{friend_id}/read` | yes | You opened the conversation: everything they sent is now read. |
| DELETE | `/messages/{message_id}` | yes | Delete a message you sent, for both of you. |
| POST | `/messages/{message_id}/report` | yes | Report a message you received. The team reviews reports in the database. The text is copied into the report, because the sender could delete the... |

#### `/movement`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/movement` | yes | The latest things you did, newest first. A missing table reads as an empty list. |
| POST | `/movement` | yes | Log some movement. Repeating the same request (same id) is harmless. Since 28 Nov 2026 (third round) a guided workout may send `sets: [{move, reps}]` (reps 1-500, at most 100; library moves only, others dropped), saved to `movement_sets` on the first save only. |
| GET | `/movement/choices` | yes | The activities that can be logged by hand, each with its slice. |
| GET | `/movement/prefs` | yes | Whether movement is added to the calorie plan, and how much (0 = off, the default). |
| POST | `/movement/prefs` | yes | Choose how much of your logged movement is added to today's plan. POST, like the other choices. |
| GET | `/movement/week` | yes | This week (Monday to Sunday): minutes, the four slices, rest days and the run of "moved weeks". Reads about a year back for the run. |
| DELETE | `/movement/{movement_id}` | yes | (Delete Movement) |

#### `/notifications`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| POST | `/notifications/cron/announce` | cron secret | Tell everyone with a registered device about a release, once. Run by hand. |
| GET | `/notifications/cron/streak-reminders` | cron secret | Same as the POST below (added 28 Nov 2026 because GET is cron-job.org's default). |
| POST | `/notifications/cron/streak-reminders` | cron secret | **Since 28 Nov 2026 (`a269582`): answers `202` at once and does the work below in the background, at most once per UTC hour, then deletes expired bites and stories (`0ad060c`). Also sends the Sunday weekly recap (`2fd303d`).** Older text: For a scheduler, run hourly. Sends the reminders that are due for each person at their own local time, each at most once a day (the day's dedupe... |
| POST | `/notifications/devices` | yes | Remember this phone's push token. A token that was on another account moves to this one, so signing out and in as someone else can't leave the old... |
| POST | `/notifications/devices/remove` | yes | Like DELETE /devices/{token}, for a browser subscription, which is long JSON text and does not belong in a URL. |
| DELETE | `/notifications/devices/{token}` | yes | Forget this phone (on sign-out). Only removes your own token. |
| GET | `/notifications/prefs` | yes | (Get Prefs) |
| POST | `/notifications/prefs` | yes | Change any of your notification choices. POST rather than PATCH so the CORS method list stays as it is. |
| POST | `/notifications/test` | yes | Send yourself one notification now, to check this device is set up. Skips quiet hours and the daily cap (you asked for it) and is not logged. |
| GET | `/notifications/web-push` | yes | Whether browsers can be notified, and the public key a browser needs to subscribe. The key is not a secret; the app asks here so it needs no... |

#### `/prefs`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/prefs/food` | yes | Where the person mostly eats (or null), and the choices to offer. Before the migration is run this simply answers "nothing chosen". |
| POST | `/prefs/food` | yes | (Set Food Prefs) |
| POST | `/prefs/language` | yes | The language the app is showing, so push notifications can use it. A best-effort note: it never fails the app (before the migration it is a no-op). |

#### `/progress`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/progress` | yes | Streak, freezes, XP, level and achievements, derived from the logs. |

#### `/recipes`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/recipes` | yes | (List Recipes) |
| POST | `/recipes` | yes | Save a recipe. Its numbers come from the ingredients (USDA), or, for a recipe with no ingredient list, from the author's own estimate (shown as... |
| DELETE | `/recipes/{recipe_id}` | yes | Soft delete: entries already logged from it keep their numbers, and past logs stay countable for any later creator program. |
| GET | `/recipes/{recipe_id}` | yes | (Get Recipe) |
| PATCH | `/recipes/{recipe_id}` | yes | (Update Recipe) |
| POST | `/recipes/{recipe_id}/log` | yes | Log some servings of a recipe in one tap: one food-log entry named after the recipe. Idempotent on the entry id, like POST /logs. |
| GET | `/recipes/{recipe_id}/media` | yes | (List Media) |
| DELETE | `/recipes/{recipe_id}/media/{position}` | yes | Harmless if there is no photo there. |
| PUT | `/recipes/{recipe_id}/media/{position}` | yes | Add or replace the cover (position 0) or a slide (1-5). Replacing gives the photo a new file name, so an old link can never show the new photo. |
| POST | `/recipes/{recipe_id}/report` | yes | Report a friend's recipe (App Store guideline 1.2). The team reviews reports in the database. You can't report your own. |
| POST | `/recipes/{recipe_id}/save` | yes | Keep a recipe (mine, or one a friend shared) in my "Saved" collection. |
| DELETE | `/recipes/{recipe_id}/share/{friend_id}` | yes | Take back a friend's access. The card stays in the chat but no longer opens. |
| POST | `/recipes/{recipe_id}/share/{friend_id}` | yes | Send one of my recipes to a friend as a chat card. It stays private: this one friend gets read access, which `DELETE` on the same path takes back.... |
| GET | `/recipes/{recipe_id}/shares` | yes | Who I have shared this recipe with, so I can take it back. Only the owner can see this list. Rows stay until revoked, even if the friendship... |

#### `/reports`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/reports/weekly` | yes | Your week in a few kind lines, plus any habit pattern the data supports. |

#### `/snaps`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| POST | `/snaps` | yes | Send a food photo to one or more friends. Repeating the same request (same id) is harmless: it returns the original result. |
| GET | `/snaps/inbox` | yes | Snaps friends sent you in the last 24 hours, newest first. |
| POST | `/snaps/purge` | cron secret | For a scheduler: delete every expired snap. Disabled until CRON_SECRET is set. |
| GET | `/snaps/sent` | yes | Your own snaps from the last 24 hours, with who opened and reacted. |
| DELETE | `/snaps/{snap_id}` | yes | Take back a snap you sent. The day still counts toward the streak. |
| POST | `/snaps/{snap_id}/react` | yes | (React) |
| POST | `/snaps/{snap_id}/report` | yes | Report a snap you received. The team reviews reports in the database. |
| POST | `/snaps/{snap_id}/view` | yes | (Mark Viewed) |

#### `/stories`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/stories` | yes | Your own live stories (with who has seen them) and your friends'. Friends with something you haven't seen come first, then the people you have the... |
| POST | `/stories` | yes | Add a food photo to your story. Repeating the same request (same id) is harmless: it returns the original result. |
| DELETE | `/stories/{story_id}` | yes | Take a photo off your story. |
| POST | `/stories/{story_id}/react` | yes | (React) |
| POST | `/stories/{story_id}/report` | yes | Report a friend's story. The team reviews reports in the database. |
| POST | `/stories/{story_id}/view` | yes | (Mark Viewed) |

#### `/targets`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/targets` | yes | Retrieves the specific target for the logged-in user. |
| POST | `/targets` | yes | Calculates and saves (or updates) the user's nutritional targets. |

#### `/username`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| POST | `/username` | yes | Pick a username (free the first time), or change it once per 30 days. |
| GET | `/username/check` | yes | Live availability for the picker. Your own current name counts as free. |

#### `/users`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/users/{friend_id}/highlights` | yes | A friend's Highlights: only the pinned recipes I am allowed to open (set to "friends", or shared with me). Anyone who is not a friend, including... |

#### `/weights`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/weights` | yes | (Get Weights) |
| POST | `/weights` | yes | Record a weigh-in (replacing any for that day) and, when it's the newest one, recompute the user's targets for the new weight. |
| DELETE | `/weights/{log_date}` | yes | (Delete Weight) |

#### `/workouts`

| Method | Path | Login | What it does (first line of the docstring) |
|---|---|---|---|
| GET | `/workouts` | yes | Every routine as a card (id, name, minutes, focus, slice, level, summary), shortest first. |
| GET | `/workouts/{routine_id}` | yes | One routine: its sections for reading and a flat step list for the player. Since 28 Nov 2026 each `play` step has `easier` (`{move, name, cue, amount, mode, seconds, reps}` or `null`) for the player's "Easier version" button, and `move` (the library id, `null` for rests); the answer has `last_reps` (`{"squat": 12}`, empty before the movement_sets migration) for "Last time". |

