"""Error handling must stay explicit.

Guards the `error-handling-and-logging` change: no bare `except:` clauses, no
raw `print()` in application code (the CLI/launcher use the console logger),
unhandled request errors become 5xx, and startup fails loudly.
"""

import asyncio
import logging
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

fail = []


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        fail.append(label)


def app_sources():
    """Application modules, excluding tests and the test runner itself."""
    paths = [os.path.join(REPO, "api_server.py"), os.path.join(REPO, "start_api.py")]
    for root, dirs, files in os.walk(os.path.join(REPO, "list_sync")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        paths += [os.path.join(root, f) for f in files if f.endswith(".py")]
    return paths


# --- no bare `except:` clauses (they swallow KeyboardInterrupt/SystemExit too) ---
bare = []
for path in app_sources():
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if line.strip().startswith("except:"):
                bare.append(f"{os.path.relpath(path, REPO)}:{i}")
check("no bare except clauses", bare, [])

# --- no raw print(): diagnostics go to the logger, CLI output to the console logger ---
prints = []
for path in app_sources():
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if "print(" in line and not line.lstrip().startswith("#"):
                prints.append(f"{os.path.relpath(path, REPO)}:{i}")
check("no print() calls in application code", prints, [])


# --- API boundary: an unexpected error must surface as 500, not a silent 200 ---
def stub(name, attrs=()):
    module = types.ModuleType(name)
    for attr in attrs:
        setattr(module, attr, type(attr, (), {}))
    sys.modules[name] = module
    return module


for needed in ("seleniumbase", "bs4", "halo"):
    try:
        __import__(needed)
    except ImportError:
        stub(needed, ("SB", "BeautifulSoup", "Halo"))
crypto = stub("cryptography")
fernet = stub("cryptography.fernet", ("Fernet", "InvalidToken"))
crypto.fernet = fernet
dotenv = stub("dotenv")
dotenv.load_dotenv = lambda *a, **k: None
dotenv.set_key = lambda *a, **k: None

logging.disable(logging.CRITICAL)

from starlette.requests import Request

import api_server

scope = {
    "type": "http",
    "method": "GET",
    "path": "/boom",
    "query_string": b"",
    "headers": [],
    "scheme": "http",
    "server": ("test", 80),
    "client": ("test", 12345),
}
response = asyncio.run(api_server.unhandled_exception_handler(Request(scope), RuntimeError("kaboom")))
check("unhandled error -> 500", response.status_code, 500)

# --- startup fails loudly when a required resource cannot be initialized ---
api_server.init_database = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
try:
    asyncio.run(api_server.startup_event())
    outcome = "returned"
except RuntimeError:
    outcome = "raised"
except Exception as exc:  # noqa: BLE001 - report whatever escaped
    outcome = type(exc).__name__
check("startup fails loudly on init error", outcome, "raised")

print()
print("FAILED:", fail if fail else "none")
sys.exit(1 if fail else 0)
