"""Security tests for the dashboard: local token, Tailscale-only remote access, device pairing.

Runs the FastAPI app in-process with simulated client addresses (no network, no Tailscale needed):
    .venv/bin/python tests/test_remote.py
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TEKBRO_HOME"] = tempfile.mkdtemp(prefix="tekbro-test-")

from tekbro import remote as R  # noqa: E402
from tekbro.app import TekBro, build_api  # noqa: E402
from tekbro.config import Config  # noqa: E402

PORT = 8765
TS = {"ip": "100.101.102.103", "dns": "macbook.tail1234.ts.net"}
PHONE, LAN, LOCAL = "100.90.1.2", "192.168.1.50", "127.0.0.1"
TOKEN = "local-run-token"


def request(app, client, path, *, host=None, method="GET", cookies=None, origin=None):
    """Minimal ASGI client: returns (status, headers dict, body)."""
    path, _, query = path.partition("?")
    headers = [(b"host", (host or f"{TS['ip']}:{PORT}").encode())]
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    if origin:
        headers.append((b"origin", origin.encode()))
    if method == "POST":
        headers.append((b"content-type", b"application/json"))
    scope = {"type": "http", "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": query.encode(), "headers": headers, "client": (client, 50000),
             "server": ("x", PORT), "scheme": "http", "root_path": ""}
    out = {"status": None, "headers": {}, "body": b""}
    body = b"{}" if method == "POST" else b""

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
            for k, v in msg["headers"]:
                out["headers"].setdefault(k.decode().lower(), []).append(v.decode())
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return out["status"], out["headers"], out["body"]


def device_cookie(headers):
    for c in headers.get("set-cookie", []):
        if c.startswith(R.DEVICE_COOKIE + "="):
            return c.split(";", 1)[0].split("=", 1)[1], c
    return None, None


results = []


def check(name, cond):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name)


cfg = Config()
cfg.port, cfg.hotkeys = PORT, False
j = TekBro(cfg, use_audio=False, use_screen=False)
store = R.DeviceStore()
local_only = build_api(j, TOKEN, None, store)
app = build_api(j, TOKEN, TS, store)
lh = f"127.0.0.1:{PORT}"

# ---- this Mac (unchanged behaviour) ----
check("local: no token → 401", request(app, LOCAL, "/", host=lh)[0] == 401)
st, h, _ = request(app, LOCAL, f"/?t={TOKEN}", host=lh)
check("local: run token → 303 + cookie", st == 303 and any("tekbro_token" in c for c in h.get("set-cookie", [])))
check("local: cookie → 200", request(app, LOCAL, "/api/state", host=lh, cookies={"tekbro_token": TOKEN})[0] == 200)

# ---- who may connect at all ----
check("Wi-Fi/LAN client → 403", request(app, LAN, "/", host=f"192.168.1.10:{PORT}")[0] == 403)
check("tailnet client while --remote is off → 403", request(local_only, PHONE, "/")[0] == 403)
check("tailnet client, rebinding Host → 403", request(app, PHONE, "/", host=f"evil.com:{PORT}")[0] == 403)

# ---- remote auth ----
check("tailnet: unpaired → 401", request(app, PHONE, "/api/state")[0] == 401)
check("tailnet: per-run token is NOT accepted remotely",
      request(app, PHONE, f"/?t={TOKEN}")[0] == 401)
check("tailnet: wrong pairing code → 401", request(app, PHONE, "/pair?c=nope")[0] == 401)

code = store.create_pairing("phone")
st, h, _ = request(app, PHONE, f"/pair?c={code}")
tok, raw = device_cookie(h)
check("tailnet: valid pairing → 303 + device cookie", st == 303 and tok is not None)
check("device cookie is HttpOnly + SameSite=Strict + long-lived",
      raw and "httponly" in raw.lower() and "samesite=strict" in raw.lower() and "max-age" in raw.lower())
check("pairing code works only once", request(app, PHONE, f"/pair?c={code}")[0] == 401)
check("tailnet: paired device → 200", request(app, PHONE, "/api/state", cookies={R.DEVICE_COOKIE: tok})[0] == 200)
check("MagicDNS host accepted",
      request(app, PHONE, "/api/state", host=f"{TS['dns']}:{PORT}", cookies={R.DEVICE_COOKIE: tok})[0] == 200)
check("paired device: POST from foreign origin → 403",
      request(app, PHONE, "/api/solve", method="POST", cookies={R.DEVICE_COOKIE: tok},
              origin="https://evil.com")[0] == 403)
check("paired device: same-origin POST → 200",
      request(app, PHONE, "/api/auto", method="POST", cookies={R.DEVICE_COOKIE: tok},
              origin=f"http://{TS['ip']}:{PORT}")[0] == 200)
check("only a hash of the device token is stored", tok not in store.path.read_text())
check("devices.json is private (0600)", (store.path.stat().st_mode & 0o777) == 0o600)

# ---- revoke + expiry ----
check("revoke works", store.revoke("phone"))
check("revoked device → 401", request(app, PHONE, "/api/state", cookies={R.DEVICE_COOKIE: tok})[0] == 401)
old = store.create_pairing("old")
import json  # noqa: E402
data = json.loads(store.path.read_text())
for p in data["pairings"]:
    p["expires"] = time.time() - 1  # force-expire
store.path.write_text(json.dumps(data))
time.sleep(0.01)
check("expired pairing code → 401", request(app, "100.90.1.9", f"/pair?c={old}")[0] == 401)

# ---- brute-force lockout ----
attacker = "100.90.7.7"
for _ in range(10):
    request(app, attacker, "/pair?c=guess")
code2 = store.create_pairing("late")
check("after 10 failures the client is locked out (even with a valid code) → 429",
      request(app, attacker, f"/pair?c={code2}")[0] == 429)
check("other devices are not affected by the lockout",
      request(app, "100.90.1.3", f"/pair?c={code2}")[0] == 303)

# ---- address helpers ----
check("tailnet ranges", R.is_tailnet("100.64.0.1") and R.is_tailnet("100.127.255.254")
      and not R.is_tailnet("100.128.0.1") and not R.is_tailnet("192.168.0.1"))

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
