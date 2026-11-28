---
name: investigate-a-problem
description: How to find the real cause when the NuStreak owner reports something broken, whether users can't reach the app, a feature fails, or they send a screenshot of an error. Work from evidence first, map what users see to the code, check the live system from outside (DNS, health, deploys, logs), test hypotheses cheapest first, reproduce with a failing test, fix the cause, verify live under the user's conditions, and report plainly. Use it whenever something is reported broken or "not working", before proposing any fix.
---

# Investigating a reported problem

**What the owner expects:**
- Fix it **now**.
- Find the cause **from evidence** (screenshots, logs, DNS lookups, the code), not from guesses.
- **Don't lecture** about known limits. "The server sleeps" is not an answer unless you have proved it is the cause.
- At the end, say the **cause**, **what you changed** and **what is still unproven**.

For a full outage, also follow the step-by-step checklist in AGENTS.md §8.1. It includes how to undo a deploy.

---

## 1. Collect the evidence before forming an opinion

- **Screenshots or a zip:** extract it into a new empty folder and look at **every** image. Write down:
  - the exact text on screen (it's searchable in the code);
  - the screen it's on;
  - the browser or phone;
  - any language other than English.
- **Ask only what you need** (one short message):
  - When did it start?
  - Everyone or some people? On one network or app, or all?
  - Does it happen every time?
  - What did the person do just before?
- **Line it up with deploys.** Something pushed just before the trouble began is the first suspect:
  ```bash
  cd /home/curtis/calorie_backend && git log --format='%h %ci %s' -5
  cd /home/curtis/calorie_app     && git log --format='%h %ci %s' -5
  curl -s "https://api.github.com/repos/Curtis-18/calorie_app/actions/runs?per_page=3" | python3 -c 'import sys,json;[print(r["head_sha"][:7],r["created_at"],r["status"],r["conclusion"]) for r in json.load(sys.stdin)["workflow_runs"]]'
  ```

## 2. Map what the user sees to the code

Use the `read-the-codebase` skill, §4. Grep the exact on-screen sentence, then follow it to the provider, the service and the route. **Know what each message really means.** The text is often less specific than it sounds:
- **"Our server naps..." / "Couldn't reach the server"** (`lib/services/server_handshake.dart`, `deadline` 100 s): **any** failure to get an answer within 100 seconds. That includes a sleeping server, a DNS failure, a CORS refusal, an expired login being retried, or a crash. It is not proof that the server is down.
- **"Couldn't save your meal"**: read `lib/services/save_entries.dart` to see which items failed and why.
- **Signed out unexpectedly**: the app signs out after two 401 answers. Look for anything answering 401 that isn't a bad token (AGENTS.md §9.3).

## 3. Check from outside, cheapest first (read-only; safe to run any time)

```bash
curl -s -o /dev/null -w 'site %{http_code}\n' https://calorie-app-ug.vercel.app          # the web app loads?
curl -s -m 90 https://calorie-app-ug.vercel.app/api/health; echo                          # backend + database, the way the app reaches them
curl -s -o /dev/null -w '%{http_code}\n' https://calorie-app-ug.vercel.app/api/<route>    # 401 = route exists and answers; 404 = not deployed
dig +short calorie-app-ug.vercel.app; dig +short @8.8.8.8 calorie-app-ug.vercel.app        # does this network resolve it like Google does?
dig +short calorie-backend-odc3.onrender.com; dig +short @8.8.8.8 calorie-backend-odc3.onrender.com
```
- On this laptop's home network, `*.onrender.com` doesn't resolve. That's known and doesn't by itself mean anything. To reach Render directly, add `--resolve calorie-backend-odc3.onrender.com:443:<ip from @8.8.8.8>`.
- **What you can't see, ask the owner for, with exact instructions:**
  - **Render** → the service → **Logs**, around the time it happened. Search for `Traceback`, `request refused`, `gemini error`, `scan_done`, `web push refused`, `503`.
  - **Render** → **Events**: did a deploy fail or the service restart?
  - **Supabase**: is the project paused, or are there errors?
  - **Vercel** → Deployments / Usage.
  - Ask for screenshots or pasted text. Never ask for keys.

## 4. Hypotheses: write them down, test the cheapest first

List 2-4 possible causes. For each one, write what evidence would **prove** it and what would **rule it out**. Check them in order of cost: a `curl` or `dig` costs seconds, reading code minutes, asking the owner for logs an hour. Stop when one is **proven**, not merely when one is plausible.

In your report, say which causes you ruled out and how. That stops the next person re-checking them.

**Prefer the boring explanations first:**
1. Something was just deployed.
2. A setting is missing or expired (a disabled USDA key, a used-up Gemini quota, an unset `SUPABASE_SERVICE_ROLE_KEY`).
3. A migration hasn't been run.
4. A network or DNS problem on some users' side.
5. A real code bug.

## 5. Reproduce it in a test before fixing

- **Backend:** a route test with the fake database (`tests/test_activity.py` shows how), scripted to produce the failing answer. For example: the database raises, and the route must answer 503 instead of a misleading value.
- **App:** a unit or widget test that feeds the service the failing response: a 401, a missing field, a timeout.
- Watch the test **fail**, then fix the code and watch it pass. If you can't reproduce it in a test, say so, and say why you still believe your fix addresses the cause.

## 6. Fix the cause, not the symptom

- Don't widen a timeout for an address that doesn't resolve. Don't add a retry for a 4xx. Don't catch an error and show nothing.
- Before changing odd-looking code, read its comment and history (`git log -S`). It may be the fix for an older incident (`read-the-codebase` §5).
- Check AGENTS.md §9 for the same symptom: it may already have a known fix or a refused approach.
- Then run the `what-to-look-out-for` checklist and both test suites.

## 7. Verify live, under the user's conditions

Only push after the owner says "push" (AGENTS.md §4.5). Then:
- Check the deploy finished: the GitHub API command for the app, or a new route answering 401 for the backend.
- Repeat the check **from the same conditions the user had**. On 26 Nov that meant testing from the network that couldn't resolve onrender.com, not from a working one.
- Anything you couldn't check yourself (a signed-in session, a real phone, a real Gemini call), list it as **not verified**, and say how the owner can check it.

## 8. Report and record

- **To the owner, in plain words:** the cause; what you changed; what you verified live; what is still unproven; what users should do (reload the page, update nothing...); what the owner must do.
- **At the bottom of `handover.md`:** a dated section with the cause, commits, checks and open points.
- **If the same mistake could happen again:** add a line to AGENTS.md §9 ("Don't ... → why → Instead ...").
- **Never just write down a fault that can hit real users and move on.** In Nov 2026 the DNS problem was noted on 20-21 Nov, and on 26 Nov users were locked out. Fix it, or tell the owner plainly that users are at risk.

---

## Worked example 1: "my users can no longer access the app" (26 Nov 2026)

1. **Evidence:** the screenshots showed the app's "Couldn't reach the server" screen for several users at once. The owner said: "don't tell me the server times out, I know that."
2. **Mapped:** that screen means "no answer within 100 s, for any reason", so it didn't prove the server was down.
3. **Checked from outside:**
   - The backend's `/health` answered fine when reached by its IP.
   - `dig calorie-backend-odc3.onrender.com` returned **NXDOMAIN** on the local resolver, while `dig @8.8.8.8` returned an address.
   - So some networks' DNS refused `*.onrender.com`, and the browser never reached the server at all.
4. **Ruled out:** a sleeping or crashed server (it answered by IP); CORS (no request was ever sent to the server).
5. **Fixed the cause:** the web app calls the backend through its own address (`/api` on vercel.app, forwarded by `vercel.json`), so the network never has to resolve onrender.com. Tested in `test/api_config_test.dart`.
6. **Verified live from the blocking network:** health, login header, 6 MB upload and every HTTP method passed through `/api`.
7. **Reported unproven:** a signed-in session, a real scan, an affected user's phone, the Vercel plan's limits. Phone builds still need a domain of our own.

## Worked example 2: "people see their own username as taken" (earlier, AGENTS.md §9.3)

1. **Evidence:** people with a username were sent to the username picker, and their own name showed as "taken".
2. **Code path:** the app picks the screen from `GET /me`. The route caught a database error and answered `username: null`, which the app reads as "has no username".
3. **Cause:** a failure was reported as a real value, so "couldn't check" looked like "nothing there".
4. **Fix:** `/me` answers **503** on a database error, never a made-up `username: null`. The test is `tests/test_username.py::test_me_says_it_does_not_know_when_the_database_fails`; its docstring tells the story, as tests here do.
5. **Lesson** (now in `what-to-look-out-for` §3): never answer a value that means something else when a read fails.
