"""The HTTP surface must not change when routes move into domain routers.

Guards the `modularize-api-server` change: `create_app()` is importable and
callable on its own, the compatibility shim exposes an app whose
paths/methods/operationIds match the captured baseline, the shim holds no
routes, and no single module owns every route.
"""

import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(REPO, "tests", "openapi_baseline.json")
METHODS = ("get", "post", "put", "delete", "patch")

fail = []


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        fail.append(label)


def check_true(label, cond):
    print(f"{'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        fail.append(label)


def stub(name, attrs=()):
    m = types.ModuleType(name)
    for a in attrs:
        setattr(m, a, type(a, (), {}))
    sys.modules[name] = m
    return m


for n in ("seleniumbase", "bs4", "halo"):
    try:
        __import__(n)
    except ImportError:
        stub(n, ("SB", "BeautifulSoup", "Halo"))
c = stub("cryptography")
f = stub("cryptography.fernet", ("Fernet", "InvalidToken"))
c.fernet = f
d = stub("dotenv")
d.load_dotenv = lambda *a, **k: None
d.set_key = lambda *a, **k: None

tmp = tempfile.mkdtemp()
import list_sync.utils.logger as lg

lg.DATA_DIR = tmp
import list_sync.database as db

db.DB_FILE = os.path.join(tmp, "list_sync.db")
db.init_database()

import api_server

api_server.DB_FILE = db.DB_FILE

from fastapi import FastAPI

from list_sync.web.app import create_app


def operations(app):
    """Map (path, method) -> operationId from an app's OpenAPI schema."""
    schema = app.openapi()
    return {
        (path, method): spec.get("operationId")
        for path, methods in schema["paths"].items()
        for method, spec in methods.items()
        if method in METHODS
    }


# --- the compatibility entrypoint still builds a real app ---
check_true("api_server.app is a FastAPI app", isinstance(api_server.app, FastAPI))

# --- the factory is importable and callable without binding a port ---
fresh = create_app()
check_true("create_app() returns a FastAPI app", isinstance(fresh, FastAPI))
check_true("create_app() builds its own app instance", fresh is not api_server.app)

# --- the OpenAPI surface is identical to the captured baseline ---
with open(BASELINE, encoding="utf-8") as fh:
    baseline_ops = {
        (path, method): spec.get("operationId")
        for path, methods in json.load(fh)["paths"].items()
        for method, spec in methods.items()
        if method in METHODS
    }
live_ops = operations(api_server.app)
check("openapi path count", len({p for p, _ in live_ops}), len({p for p, _ in baseline_ops}))
check_true("openapi operation surface matches baseline", live_ops == baseline_ops)

# --- routes live in domain modules; the shim holds none ---
routers_dir = Path(REPO) / "list_sync" / "web" / "routers"
counts = {path.name: path.read_text(encoding="utf-8").count("@router.") for path in routers_dir.glob("*.py")}

shim = (Path(REPO) / "api_server.py").read_text(encoding="utf-8")
check("compatibility shim holds no routes", shim.count("@app.") + shim.count("@router."), 0)
check("every baseline operation has a router decorator", sum(counts.values()), len(baseline_ops))
check_true("routes are split across domain modules", len([n for n in counts.values() if n]) >= 5)
check_true("no module owns every route", max(counts.values(), default=0) < len(baseline_ops))

print()
print("FAILED:", fail if fail else "none")
sys.exit(1 if fail else 0)
