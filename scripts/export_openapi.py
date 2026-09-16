"""Export the FastAPI OpenAPI schema for frontend type generation.

Heavy optional runtime dependencies are stubbed so the app can be imported
without a live server or their install (the same approach as
``tests/test_route_inventory.py``). The schema is written to
``listsync-nuxt/openapi.json``; ``npm run openapi:types`` turns it into
TypeScript. Exit code is non-zero if the app cannot be imported.
"""

import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "listsync-nuxt" / "openapi.json"
METADATA_METHODS = ("get", "post", "put", "delete", "patch")


def stub(name, attrs=()):
    """Register a placeholder module for an optionally-installed dependency."""
    module = types.ModuleType(name)
    for attr in attrs:
        setattr(module, attr, type(attr, (), {}))
    sys.modules[name] = module
    return module


def install_stubs():
    """Stub the dependencies that are not needed to build the schema."""
    for name in ("seleniumbase", "bs4", "halo"):
        try:
            __import__(name)
        except ImportError:
            stub(name, ("SB", "BeautifulSoup", "Halo"))
    cryptography = stub("cryptography")
    cryptography.fernet = stub("cryptography.fernet", ("Fernet", "InvalidToken"))
    dotenv = stub("dotenv")
    dotenv.load_dotenv = lambda *_args, **_kwargs: None
    dotenv.set_key = lambda *_args, **_kwargs: None


def operations(schema):
    """Return the (path, method) pairs the schema exposes."""
    return {
        (path, method) for path, methods in schema["paths"].items() for method in methods if method in METADATA_METHODS
    }


def main():
    install_stubs()
    sys.path.insert(0, str(REPO))

    try:
        from list_sync.web.app import create_app
    except ImportError as exc:
        sys.stderr.write(f"failed to import the FastAPI app: {exc}\n")
        raise SystemExit(1) from exc

    schema = create_app().openapi()
    found = operations(schema)

    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    path_count = len({path for path, _ in found})
    print(f"wrote {OUTPUT}: {path_count} paths, {len(found)} operations")


if __name__ == "__main__":
    main()
