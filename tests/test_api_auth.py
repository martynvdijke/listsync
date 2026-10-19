"""Optional bearer auth, env-driven CORS, and settings masking.

The browser talks to the Nuxt server, which proxies /api and injects the bearer
token. These checks cover the backend contract that proxy relies on: no token
means the request is rejected, the health probe stays open, and a configured
origin is the only one CORS reflects.
"""

import base64
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def stub(n, a=()):
    m = types.ModuleType(n)
    for x in a:
        setattr(m, x, type(x, (), {}))
    sys.modules[n] = m
    return m


for n in ("seleniumbase", "bs4", "halo"):
    try:
        __import__(n)
    except ImportError:
        stub(n, ("SB", "BeautifulSoup", "Halo"))


class FakeFernet:
    def __init__(self, key):
        pass

    @staticmethod
    def generate_key():
        return base64.urlsafe_b64encode(b"k" * 32)

    def encrypt(self, data):
        return base64.urlsafe_b64encode(data)

    def decrypt(self, token):
        return base64.urlsafe_b64decode(token)


c = types.ModuleType("cryptography")
f = types.ModuleType("cryptography.fernet")
f.Fernet = FakeFernet
f.InvalidToken = type("InvalidToken", (Exception,), {})
c.fernet = f
sys.modules["cryptography"] = c
sys.modules["cryptography.fernet"] = f

d = stub("dotenv")
d.load_dotenv = lambda *a, **k: None
d.set_key = lambda *a, **k: None

tmp = tempfile.mkdtemp()
import list_sync.utils.logger as lg

lg.DATA_DIR = tmp

from pathlib import Path

from list_sync import encryption

encryption.ENCRYPTION_KEY_FILE = Path(tmp) / ".encryption_key"

import list_sync.database as db

db.DB_FILE = os.path.join(tmp, "list_sync.db")
db.init_database()

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


from fastapi.testclient import TestClient

from list_sync.web.app import create_app, get_allowed_origins

# --- auth disabled by default keeps existing deployments working ---
os.environ.pop("LISTS_SYNC_API_TOKEN", None)
client = TestClient(create_app())
check("open without token", client.get("/api/lists").status_code, 200)

# --- token configured: API requires it, health probe does not ---
os.environ["LISTS_SYNC_API_TOKEN"] = "test-shared-secret"
client = TestClient(create_app())

r = client.get("/api/lists")
check("unauthenticated API rejected", r.status_code, 401)
check_true("rejection advertises bearer", r.headers.get("www-authenticate") == "Bearer")

r = client.get("/api/lists", headers={"Authorization": "Bearer wrong"})
check("wrong token rejected", r.status_code, 401)

r = client.get("/api/lists", headers={"Authorization": "Bearer test-shared-secret"})
check("proxy-injected bearer accepted", r.status_code, 200)

r = client.get("/api/system/health")
check("health probe stays public", r.status_code, 200)

r = client.get("/api/system/health", headers={"Authorization": "Bearer test-shared-secret"})
check("health probe with token works", r.status_code, 200)

# --- CORS is env-driven, not a hardcoded LAN sweep ---
os.environ.pop("CORS_ALLOWED_ORIGINS", None)
check("CORS empty by default", get_allowed_origins(), [])

os.environ["CORS_ALLOWED_ORIGINS"] = "https://dash.example.com, https://alt.example.com"
check("CORS reads env list", get_allowed_origins(), ["https://dash.example.com", "https://alt.example.com"])

client = TestClient(create_app())
r = client.get(
    "/api/system/health",
    headers={"Origin": "https://dash.example.com", "Authorization": "Bearer test-shared-secret"},
)
check("allowed origin reflected", r.headers.get("access-control-allow-origin"), "https://dash.example.com")

r = client.get(
    "/api/system/health",
    headers={"Origin": "https://evil.example.com", "Authorization": "Bearer test-shared-secret"},
)
check("other origins not reflected", r.headers.get("access-control-allow-origin"), None)

r = client.options(
    "/api/lists",
    headers={
        "Origin": "https://dash.example.com",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    },
)
check("preflight succeeds without token", r.status_code, 200)
check("preflight carries allowed origin", r.headers.get("access-control-allow-origin"), "https://dash.example.com")

# --- settings GET masks secrets instead of returning them ---
from list_sync.config import ConfigManager

config = ConfigManager()
config.save_setting("gotify_token", "super-secret-token-1234")
config.save_setting("overseerr_api_key", "seerr-api-key-abcd")

r = client.get("/api/settings/config", headers={"Authorization": "Bearer test-shared-secret"})
check("settings reachable with token", r.status_code, 200)
body = r.json()
check_true("gotify token not returned", "super-secret-token-1234" not in body.get("gotify_token", ""))
check_true("gotify token masked", body.get("gotify_token", "").endswith("1234"))
check_true("seerr key not returned", "seerr-api-key-abcd" not in body.get("overseerr_api_key", ""))
check_true("seerr key masked", body.get("overseerr_api_key", "").endswith("abcd"))

print()
print("FAILED:", fail if fail else "none")
sys.exit(1 if fail else 0)
