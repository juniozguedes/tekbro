"""Remote dashboard access for your own devices, over Tailscale.

Why Tailscale: it's a private, encrypted network between devices logged into your
account. Tek Bro only listens on the Mac's Tailscale address (never on Wi-Fi/LAN or
the internet), so a device has to be in your tailnet before it can even connect.

On top of that, each device is paired once:
  1. `python -m tekbro --pair phone` (or `pair phone` in the running terminal)
     prints a one-time link + QR code, valid for 10 minutes.
  2. Opening it on the device swaps the one-time code for a long-lived device token
     (HttpOnly cookie). Only a SHA-256 hash of each token is stored on the Mac.
  3. `--devices` lists paired devices, `--revoke NAME` cuts one off immediately.
"""
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

DEVICE_COOKIE = "tekbro_device"
DEVICE_COOKIE_MAX_AGE = 365 * 24 * 3600
PAIR_TTL_S = 600                 # one-time pairing links expire after 10 minutes
LAST_SEEN_WRITE_S = 300          # don't rewrite the file on every request

# Tailscale hands out addresses from these ranges only.
TAILNET_NETS = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]

TAILSCALE_CANDIDATES = ["tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"]


def config_dir() -> Path:
    return Path(os.getenv("TEKBRO_HOME") or Path.home() / ".config" / "tekbro")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_loopback(host: str | None) -> bool:
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def is_tailnet(host: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return any(ip in net for net in TAILNET_NETS)


def tailscale_info() -> dict | None:
    """This Mac's Tailscale IPv4 address and MagicDNS name, or None if Tailscale isn't up."""
    for cand in TAILSCALE_CANDIDATES:
        exe = shutil.which(cand) or (cand if Path(cand).exists() else None)
        if not exe:
            continue
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5)
            st = json.loads(out.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            continue
        if st.get("BackendState") != "Running":
            return None
        me = st.get("Self") or {}
        ipv4 = next((a for a in me.get("TailscaleIPs") or [] if "." in a), None)
        if ipv4:
            return {"ip": ipv4, "dns": (me.get("DNSName") or "").rstrip(".")}
    return None


class DeviceStore:
    """Paired devices + pending one-time pairing codes, in ~/.config/tekbro/devices.json (0600).

    Re-read whenever the file changes, so `--pair` / `--revoke` from another terminal
    take effect in a running Tek Bro without a restart.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "devices.json"
        self._lock = threading.Lock()
        self._mtime = None
        self._data = {"devices": [], "pairings": []}

    # ---------- storage ----------
    def _load(self):
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._mtime, self._data = None, {"devices": [], "pairings": []}
            return
        if mtime != self._mtime:
            self._data = json.loads(self.path.read_text() or "{}")
            self._data.setdefault("devices", [])
            self._data.setdefault("pairings", [])
            self._mtime = mtime

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime_ns

    # ---------- pairing ----------
    def create_pairing(self, name: str) -> str:
        code = secrets.token_urlsafe(18)
        with self._lock:
            self._load()
            now = time.time()
            self._data["pairings"] = [p for p in self._data["pairings"] if p["expires"] > now]
            self._data["pairings"].append({"name": name, "hash": _hash(code), "expires": now + PAIR_TTL_S})
            self._save()
        return code

    def redeem(self, code: str) -> tuple[str, str] | None:
        """One-time code → (device name, long-lived device token). The code is consumed."""
        h = _hash(code)
        with self._lock:
            self._load()
            now = time.time()
            match = next((p for p in self._data["pairings"]
                          if p["expires"] > now and secrets.compare_digest(p["hash"], h)), None)
            if not match:
                return None
            self._data["pairings"].remove(match)
            token = secrets.token_urlsafe(32)
            name = match["name"]
            self._data["devices"] = [d for d in self._data["devices"] if d["name"] != name]  # re-pair replaces
            self._data["devices"].append({"name": name, "hash": _hash(token), "created": now, "last_seen": now})
            self._save()
        return name, token

    # ---------- checking ----------
    def check(self, token: str) -> str | None:
        if not token:
            return None
        h = _hash(token)
        with self._lock:
            self._load()
            for d in self._data["devices"]:
                if secrets.compare_digest(d["hash"], h):
                    now = time.time()
                    if now - d.get("last_seen", 0) > LAST_SEEN_WRITE_S:
                        d["last_seen"] = now
                        self._save()
                    return d["name"]
        return None

    def devices(self) -> list[dict]:
        with self._lock:
            self._load()
            return [{k: d[k] for k in ("name", "created", "last_seen")} for d in self._data["devices"]]

    def revoke(self, name: str) -> bool:
        with self._lock:
            self._load()
            before = len(self._data["devices"])
            self._data["devices"] = [d for d in self._data["devices"] if d["name"] != name]
            if len(self._data["devices"]) == before:
                return False
            self._save()
            return True


class FailureLimiter:
    """Blocks a client IP after too many failed auth attempts (guessing protection)."""

    def __init__(self, max_failures: int = 10, window_s: float = 600):
        self.max, self.window = max_failures, window_s
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, ip: str, now: float):
        q = self._fails[ip]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._trim(ip, time.time())) >= self.max

    def fail(self, ip: str):
        with self._lock:
            self._trim(ip, time.time()).append(time.time())


def pair_url(host: str, port: int, code: str) -> str:
    return f"http://{host}:{port}/pair?c={code}"


def print_pairing(name: str, url: str):
    print(f"\nPair '{name}': open this on the device (valid {PAIR_TTL_S // 60} minutes, works once):\n  {url}\n")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except ImportError:
        pass
    print("The device must be logged into your Tailscale account, and Tek Bro must be running with --remote.\n")
