"""Orchestrator: wires audio, screen and Claude together; serves the dashboard."""
import argparse
import asyncio
import itertools
import json
import queue
import secrets
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from .brain import Brain
from .config import Config
from .screen import ScreenWatcher

STATIC = Path(__file__).parent / "static"
QUESTION_QUIET_S = 1.5      # wait this long after the last chunk before answering
TRANSCRIPT_WINDOW_S = 180   # how much recent transcript to send with a question
ECHO_DEDUPE_WAIT_S = 2.5    # hold "me" lines this long to compare with "them"
ECHO_DEDUPE_WINDOW_S = 20   # compare against "them" lines within this window


@dataclass
class Job:
    kind: str           # "answer" | "screen" | "ask"
    title: str
    prompt: str
    image: bytes | None = None
    notify: bool = False  # macOS notification when done (hotkey-triggered jobs)


class TekBro:
    def __init__(self, cfg: Config, use_audio: bool, use_screen: bool):
        self.cfg = cfg
        self.brain = Brain(cfg)
        self.transcript: deque[tuple[float, str, str]] = deque(maxlen=500)
        self.jobs: "queue.Queue[Job]" = queue.Queue()
        self.ids = itertools.count(1)
        self.subscribers: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.history: deque[dict] = deque(maxlen=200)
        self._question_timer: threading.Timer | None = None
        self.listeners = []
        self.echo_gate = None
        self.screen = (
            ScreenWatcher(cfg.monitor, cfg.screen_interval, self._on_screen_change)
            if use_screen else None
        )
        if use_audio:
            from .audio import EchoGate, Listener
            system = cfg.system_device if cfg.system_device not in (None, "", "off") else None
            self.echo_gate = EchoGate() if system and cfg.echo_cancel else None
            if system:
                self.listeners.append(Listener("them", system, cfg.whisper_model, cfg.language,
                                               self._on_text, call_app=cfg.call_app,
                                               echo_gate=self.echo_gate, role="reference"))
            # Without a "them" source, the mic is the only input, so treat it as the questioner.
            self.listeners.append(Listener("me" if system else "audio", cfg.mic_device,
                                           cfg.whisper_model, cfg.language, self._on_text,
                                           echo_gate=self.echo_gate, role="gated"))

    # ---------- events ----------
    def publish(self, event: dict):
        # Deltas are only for live streaming; job_end carries the full text for replay.
        if event["type"] != "delta":
            self.history.append(event)
        if not self.loop:
            return
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(q.put_nowait, event)

    # ---------- inputs ----------
    def _on_text(self, speaker: str, text: str):
        if speaker == "me" and self.echo_gate is not None:
            # "them" may still be transcribing the same words; decide a bit later.
            t = threading.Timer(ECHO_DEDUPE_WAIT_S, self._maybe_publish_me, args=(text, time.time()))
            t.daemon = True
            t.start()
            return
        self._publish_text(speaker, text)

    def _maybe_publish_me(self, text: str, heard_at: float):
        from .audio import is_echo_text
        recent = [t for ts, s, t in self.transcript
                  if s == "them" and abs(ts - heard_at) <= ECHO_DEDUPE_WINDOW_S]
        if recent and is_echo_text(text, recent):
            print(f"\033[2m[echo dropped] {text}\033[0m")
            return
        self._publish_text("me", text, heard_at)

    def _publish_text(self, speaker: str, text: str, ts: float | None = None):
        from .audio import looks_like_question
        self.transcript.append((ts or time.time(), speaker, text))
        self.publish({"type": "transcript", "speaker": speaker, "text": text, "ts": time.time()})
        print(f"\033[2m[{speaker}] {text}\033[0m")
        if self.cfg.auto_answer and speaker != "me" and looks_like_question(text):
            if self._question_timer:
                self._question_timer.cancel()
            self._question_timer = threading.Timer(QUESTION_QUIET_S, self.answer_question)
            self._question_timer.daemon = True
            self._question_timer.start()

    def _on_screen_change(self, png: bytes):
        self.publish({"type": "screen", "ts": time.time()})
        if self.cfg.auto_screen:
            self.jobs.put(Job("screen", "Screen changed",
                              "Look at this screenshot. If it shows a coding problem or code with a bug, solve it. Otherwise reply NONE.",
                              png))

    # ---------- actions ----------
    def recent_transcript(self) -> str:
        cutoff = time.time() - TRANSCRIPT_WINDOW_S
        return "\n".join(f"[{s}] {t}" for ts, s, t in self.transcript if ts >= cutoff)

    def latest_screen(self) -> bytes | None:
        if not self.screen:
            return None
        return self.screen.latest_png or self.screen.capture()

    def answer_question(self, notify: bool = False):
        convo = self.recent_transcript()
        if not convo:
            return
        self.jobs.put(Job("answer", "Question heard",
                          f"Live conversation transcript (most recent last):\n\n{convo}\n\n"
                          "Answer the most recent question. The screenshot shows my screen for context.",
                          self.latest_screen(), notify=notify))

    def solve_screen(self, notify: bool = False):
        png = self.screen.capture() if self.screen else None
        if not png:
            return
        self.jobs.put(Job("screen", "Solve screen",
                          "Solve the coding problem (or fix the code) shown in this screenshot.", png,
                          notify=notify))

    def ask(self, text: str, with_screen: bool = True):
        self.jobs.put(Job("ask", text[:80], text, self.latest_screen() if with_screen else None))

    # ---------- worker ----------
    def worker(self):
        while True:
            job = self.jobs.get()
            # Skip automatic jobs that a newer job of the same kind already supersedes
            # (e.g. three questions asked while Claude was busy → answer only the latest).
            if job.title in ("Question heard", "Screen changed") and not job.notify:
                with self.jobs.mutex:
                    superseded = any(p.title == job.title for p in self.jobs.queue)
                if superseded:
                    continue
            jid = next(self.ids)
            self.publish({"type": "job_start", "id": jid, "kind": job.kind, "title": job.title, "ts": time.time()})
            print(f"\n\033[1;36m━━ Tek Bro · {job.title} ━━\033[0m")
            try:
                text = self.brain.ask(
                    job.prompt, job.image,
                    on_delta=lambda d, jid=jid: (self.publish({"type": "delta", "id": jid, "text": d}),
                                                 sys.stdout.write(d), sys.stdout.flush()),
                )
            except Exception as e:
                text = f"**Error:** {e}"
            print()
            self.publish({"type": "job_end", "id": jid, "text": text, "none": text.strip() == "NONE"})
            if self.brain.usage:
                self.publish({"type": "usage", **self.brain.usage})
            if job.notify and self.cfg.notify and text.strip() != "NONE":
                from .hotkeys import notify
                notify(job.title, text)

    def start(self):
        threading.Thread(target=self.worker, daemon=True, name="worker").start()
        if self.cfg.hotkeys:
            from .hotkeys import HotkeyListener
            HotkeyListener(
                {"solve": self.cfg.hotkey_solve, "answer": self.cfg.hotkey_answer},
                {"solve": lambda: self.solve_screen(notify=True),
                 "answer": lambda: self.answer_question(notify=True)},
                sounds=self.cfg.sounds,
            ).start()
        if self.screen:
            self.screen.start()
        for l in self.listeners:
            l.start()


COOKIE = "tekbro_token"
VENDOR = {p.name: p for p in (STATIC / "vendor").glob("*")}


def build_api(j: TekBro, token: str) -> FastAPI:
    """Local dashboard. Locked down because it exposes your screen and transcript:
    - Host header must be localhost (blocks DNS-rebinding attacks from websites)
    - every request needs the per-run token (URL printed in the terminal → cookie)
    - the cookie is SameSite=Strict and POSTs must come from the same origin (blocks CSRF)
    """
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    allowed_hosts = {f"127.0.0.1:{j.cfg.port}", f"localhost:{j.cfg.port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    @api.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host", "") not in allowed_hosts:
            return Response("forbidden host", status_code=403)
        if request.method != "GET":
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return Response("forbidden origin", status_code=403)
        query_token = request.query_params.get("t")
        if request.url.path == "/" and query_token and secrets.compare_digest(query_token, token):
            resp = RedirectResponse("/", status_code=303)  # drop the token from the address bar
            resp.set_cookie(COOKIE, token, httponly=True, samesite="strict")
            return resp
        if not secrets.compare_digest(request.cookies.get(COOKIE, ""), token):
            return Response("Unauthorized: open the dashboard link printed in the Tek Bro terminal.",
                            status_code=401)
        return await call_next(request)

    @api.on_event("startup")
    async def _startup():
        j.loop = asyncio.get_running_loop()

    @api.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @api.get("/vendor/{name}")
    def vendor(name: str):
        path = VENDOR.get(name)
        return FileResponse(path) if path else Response(status_code=404)

    @api.get("/events")
    async def events(request: Request):
        q: asyncio.Queue = asyncio.Queue()
        j.subscribers.add(q)

        async def gen():
            try:
                for ev in list(j.history):
                    yield f"data: {json.dumps(ev)}\n\n"
                while not await request.is_disconnected():
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {json.dumps(ev)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                j.subscribers.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @api.get("/api/screen.png")
    def screen_png():
        png = j.screen.latest_png if j.screen else None
        return Response(png or b"", media_type="image/png", status_code=200 if png else 404)

    @api.post("/api/solve")
    def solve():
        j.solve_screen()
        return {"ok": True}

    @api.post("/api/answer")
    def answer():
        j.answer_question()
        return {"ok": True}

    @api.post("/api/ask")
    async def ask(req: Request):
        body = await req.json()
        text = str(body.get("text", "")).strip()[:4000]
        if text:
            j.ask(text, bool(body.get("with_screen", True)))
        return {"ok": True}

    @api.post("/api/auto")
    async def auto(req: Request):
        body = await req.json()
        if "screen" in body:
            j.cfg.auto_screen = bool(body["screen"])
        if "answer" in body:
            j.cfg.auto_answer = bool(body["answer"])
        return {"auto_screen": j.cfg.auto_screen, "auto_answer": j.cfg.auto_answer}

    @api.get("/api/state")
    def state():
        return {"auto_screen": j.cfg.auto_screen, "auto_answer": j.cfg.auto_answer,
                "model": j.cfg.model, "audio": [l.speaker for l in j.listeners],
                "screen": bool(j.screen)}

    return api


def terminal_loop(j: TekBro):
    help_ = ("commands: [s] solve screen · [a] answer last question · "
             "[t] toggle auto-screen · anything else = ask Claude (with screen) · [q] quit")
    print(help_)
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "s":
            j.solve_screen()
        elif cmd == "a":
            j.answer_question()
        elif cmd == "t":
            j.cfg.auto_screen = not j.cfg.auto_screen
            print(f"auto-screen: {j.cfg.auto_screen}")
        elif cmd in ("q", "quit", "exit"):
            import os
            os._exit(0)
        elif cmd in ("h", "help", "?"):
            print(help_)
        elif cmd:
            j.ask(cmd)


def main():
    p = argparse.ArgumentParser(prog="tekbro", description="Tek Bro: live technical copilot")
    p.add_argument("--list-devices", action="store_true", help="list audio devices and exit")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--no-screen", action="store_true")
    p.add_argument("--no-dashboard", action="store_true")
    p.add_argument("--auto-screen", action="store_true", help="auto-solve whenever the screen changes")
    p.add_argument("--mic", help="mic input device (name or index)")
    p.add_argument("--system", help="call audio source: 'macos' (default, native capture), 'off', or a loopback device like 'BlackHole'")
    p.add_argument("--call-app", help="only capture audio from this app, e.g. Teams, zoom, Chrome")
    p.add_argument("--list-apps", action="store_true", help="list apps whose audio can be captured and exit")
    p.add_argument("--headphones", action="store_true", help="disable echo suppression (mic stays open while they talk)")
    p.add_argument("--no-hotkeys", action="store_true", help="disable global hotkeys (⌃⌥S solve screen, ⌃⌥A answer)")
    p.add_argument("--monitor", type=int, help="display for screenshots: 1 = main (default), 2 = second, 0 = all displays")
    p.add_argument("--interval", type=float, help="seconds between screenshots")
    p.add_argument("--model", help="Claude model: sonnet (default), opus, haiku, or a full model id")
    p.add_argument("--port", type=int)
    args = p.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return
    if args.list_apps:
        import subprocess
        from .audio import ensure_helper
        subprocess.run([str(ensure_helper()), "--list"])
        return

    cfg = Config()
    if args.auto_screen: cfg.auto_screen = True
    if args.mic: cfg.mic_device = args.mic
    if args.system: cfg.system_device = args.system
    if args.call_app: cfg.call_app = args.call_app
    if args.headphones: cfg.echo_cancel = False
    if args.no_hotkeys: cfg.hotkeys = False
    if args.monitor is not None:  # 0 is valid (all displays), so don't test truthiness
        cfg.monitor = args.monitor
    if not args.no_screen:
        import mss
        with mss.mss() as sct:
            displays = len(sct.monitors) - 1
        if not 0 <= cfg.monitor <= displays:
            p.error(f"--monitor {cfg.monitor}: this Mac has {displays} display(s); use 1-{displays}, or 0 for all")
    if args.interval: cfg.screen_interval = args.interval
    if args.model: cfg.model = args.model
    if args.port: cfg.port = args.port

    j = TekBro(cfg, use_audio=not args.no_audio, use_screen=not args.no_screen)
    j.start()
    threading.Thread(target=terminal_loop, args=(j,), daemon=True).start()

    if args.no_dashboard:
        j.loop = None
        threading.Event().wait()
    else:
        token = secrets.token_urlsafe(24)
        print(f"Dashboard: http://127.0.0.1:{cfg.port}/?t={token}", flush=True)
        uvicorn.run(build_api(j, token), host="127.0.0.1", port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
