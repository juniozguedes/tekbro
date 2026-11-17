"""Talks to Claude through the local Claude Code CLI (`claude -p`).

Uses your logged-in Claude subscription (Pro/Max), not an API key.
"""
import base64
import json
import os
import subprocess
import tempfile
import threading
from typing import Callable

from .config import Config

SYSTEM_PROMPT = """You are Tek Bro, a senior software engineer helping the user with technical questions and coding challenges in real time.

Be fast and practical. Always answer in this Markdown shape:

## Answer
One to three sentences the user can say out loud.

## Code
A single fenced code block with the complete, working solution (only when code is relevant). Prefer the language already visible on screen; otherwise Python.

## Why
3-5 short bullets: approach, time/space complexity, key edge cases.

Rules:
- If a screenshot shows a coding problem, solve THAT problem, matching the function signature shown.
- If a screenshot shows code with an error, give the fixed code and name the bug.
- If a transcript is given, answer the most recent question in it.
- If nothing actionable is visible or asked, reply exactly: NONE
- No preamble, no filler."""


TIMEOUT_S = 180  # kill a stuck `claude` process so the job queue keeps moving


class Brain:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.workdir.mkdir(parents=True, exist_ok=True)
        # Latest plan usage reported by the CLI, e.g. {"five_hour": 0.06, "resets_at": 1794956400}
        self.usage: dict | None = None

    def ask(
        self,
        text: str,
        image_png: bytes | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        content: list[dict] = []
        if image_png:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(image_png).decode(),
                },
            })
        content.append({"type": "text", "text": text})
        msg = {"type": "user", "message": {"role": "user", "content": content}}

        cmd = [
            "claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--no-session-persistence",
            "--tools", "",
            "--model", self.cfg.model,
            "--effort", self.cfg.effort,
            "--system-prompt", SYSTEM_PROMPT,
            # Isolate from your personal Claude Code setup: no user hooks, plugins,
            # settings or MCP servers. With --tools "" Claude can only reply with text,
            # so instructions hidden in a screenshot can't make it take any action.
            "--setting-sources", "project",
            "--strict-mcp-config",
        ]
        env = dict(os.environ)
        # Force the subscription login instead of any API key in the environment.
        env.pop("ANTHROPIC_API_KEY", None)

        stderr = tempfile.TemporaryFile(mode="w+")  # a file can't fill up and deadlock us
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            cwd=self.cfg.workdir,
            env=env,
        )
        killer = threading.Timer(TIMEOUT_S, proc.kill)
        killer.daemon = True
        killer.start()
        assert proc.stdin and proc.stdout
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.close()

            streamed: list[str] = []
            final = ""
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = ev.get("type")
                if kind == "stream_event":
                    delta = ev["event"].get("delta") or {}
                    if delta.get("type") == "text_delta":
                        streamed.append(delta["text"])
                        if on_delta:
                            on_delta(delta["text"])
                elif kind == "rate_limit_event":
                    self._record_usage(ev.get("rate_limit_info") or {})
                elif kind == "result":
                    if ev.get("is_error"):
                        final = f"**Error from Claude:** {ev.get('result') or ev.get('subtype')}"
                    else:
                        final = ev.get("result") or ""
            proc.wait()
        finally:
            killer.cancel()
        if proc.returncode and not final:
            if proc.returncode < 0:
                return f"**Claude timed out** after {TIMEOUT_S}s. Try again."
            stderr.seek(0)
            final = f"**Claude CLI failed** (exit {proc.returncode}): {stderr.read().strip()[:500]}"
        stderr.close()
        return final or "".join(streamed)

    def _record_usage(self, info: dict):
        window = (info.get("unifiedWindows") or {}).get("five_hour") or {}
        if "utilization" in window:
            self.usage = {"five_hour": window["utilization"], "resets_at": window.get("resetsAt"),
                          "status": window.get("status")}
