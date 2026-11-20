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
One to three sentences the user can say out loud, in first person.

## Code
A single fenced code block with the complete, working solution. Prefer the language already visible on screen; otherwise Python. Leave this whole section out (heading included) when the question isn't about code.

## Why
3-5 short bullets: approach, time/space complexity, key edge cases. For non-coding questions: the key points to mention, briefly.

Rules:
- If a screenshot shows a coding problem, solve THAT problem, matching the function signature shown.
- If a screenshot shows code with an error, give the fixed code and name the bug.
- If a transcript is given, answer the most recent question in it. If the other person asked several questions in a row that the user hasn't answered yet, cover each briefly.
- The transcript is automatic speech recognition: expect misheard words and fragments, and read through them. Lines from "me" may contain stray echo of the other person.
- Never invent facts about the user: employers, projects, numbers, salary, notice period, preferences. Use only the profile below. When a needed fact isn't there, write a placeholder like [your notice period] instead of guessing.
- Reply in the language the other person is speaking.
- If nothing actionable is visible or asked, reply exactly: NONE
- No preamble, no filler."""

NO_PROFILE = """

The user hasn't provided a profile, so you know nothing about their background. Answer personal questions with a structure and placeholders, never with made-up details."""


def _read(path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def system_prompt(cfg: Config) -> str:
    """Base prompt + profile.md + context/*.md, re-read every call so edits apply immediately."""
    prompt = SYSTEM_PROMPT
    profile = _read(cfg.profile_path)
    if profile:
        prompt += "\n\nProfile of the user (facts you may use about them):\n<profile>\n" + profile + "\n</profile>"
    else:
        prompt += NO_PROFILE
    notes = [(p.name, _read(p)) for p in sorted(cfg.context_dir.glob("*.md"))] if cfg.context_dir.is_dir() else []
    notes = [(n, t) for n, t in notes if t]
    if notes:
        prompt += ("\n\nContext for this call from the user (e.g. job description, company notes):\n"
                   + "\n\n".join(f'<context file="{n}">\n{t}\n</context>' for n, t in notes))
    return prompt


class Cancelled(Exception):
    pass


TIMEOUT_S = 180  # kill a stuck `claude` process so the job queue keeps moving


class Brain:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.workdir.mkdir(parents=True, exist_ok=True)
        # Latest plan usage reported by the CLI, e.g. {"five_hour": 0.06, "resets_at": 1794956400}
        self.usage: dict | None = None
        self._proc: subprocess.Popen | None = None
        self._cancelled = threading.Event()

    def cancel(self):
        """Stop the answer being written right now (a newer question replaces it)."""
        proc = self._proc
        if proc and proc.poll() is None:
            self._cancelled.set()
            proc.kill()

    def ask(
        self,
        text: str,
        image_png: bytes | None = None,
        on_delta: Callable[[str], None] | None = None,
        effort: str | None = None,
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
            "--effort", effort or self.cfg.effort,
            "--system-prompt", system_prompt(self.cfg),
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
        self._cancelled.clear()
        proc = self._proc = subprocess.Popen(
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
            self._proc = None
        if self._cancelled.is_set():
            stderr.close()
            raise Cancelled()
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
