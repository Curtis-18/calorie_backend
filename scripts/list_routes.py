"""Print every backend endpoint as a Markdown table, grouped by the first part of the path.

Run from the backend folder (the fake values only let the settings load; nothing connects anywhere):

  USDA_API_KEY=x GEMINI_API_KEY=x SUPABASE_URL=https://x.supabase.co \
  DATABASE_URL=postgresql+asyncpg://u:p@h/d .venv/bin/python scripts/list_routes.py

It reads FastAPI's own OpenAPI description, so it works whatever FastAPI version is installed
(0.142 no longer lists included routes in `app.routes`).
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" imports from scripts/

from app.main import app  # noqa: E402

groups = defaultdict(list)
for path, ops in app.openapi()["paths"].items():
    group = "/" + path.strip("/").split("/")[0]
    for method, op in ops.items():
        doc = (op.get("description") or "").split("\n\n")[0].replace("\n", " ").replace("|", "/").strip()
        if not doc:  # no docstring: FastAPI's summary is the function name ("Accept Request")
            doc = f"({op.get('summary', '')})"
        if len(doc) > 150:
            doc = doc[:147].rsplit(" ", 1)[0] + "..."
        headers = {p["name"].lower() for p in op.get("parameters", []) if p.get("in") == "header"}
        login = "yes" if op.get("security") else ("cron secret" if "x-cron-secret" in headers else "**no**")
        groups[group].append((path, method.upper(), login, doc))

total = sum(len(v) for v in groups.values())
print(f"{total} endpoints.\n")
for group in sorted(groups):
    print(f"#### `{group}`\n")
    print("| Method | Path | Login | What it does (first line of the docstring) |")
    print("|---|---|---|---|")
    for path, method, login, doc in sorted(groups[group]):
        print(f"| {method} | `{path}` | {login} | {doc} |")
    print()
