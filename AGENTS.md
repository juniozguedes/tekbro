# AGENTS.md: Tek Bro

Context for AI coding agents (Claude Code, Codex, etc.) and humans working on this repo.

## What this product is

Tek Bro is a **local, macOS-first live copilot for technical conversations**: interviews, pairing and meetings. It:

1. **Listens** to the call (system audio) and to you (mic), and transcribes both locally with faster-whisper.
2. **Detects real questions** from the other side (EN + PT) and answers them with Claude.
3. **Watches the screen** (a screenshot every 5 s, kept in memory). On demand (hotkey) it reads the coding problem or code on screen and returns the solution, ready-to-paste code and a short explanation.
4. **Shows everything** in the terminal and in a local web dashboard.

**Target user:** a developer on a **Claude Pro/Max subscription**. Tek Bro calls Claude through the locally logged-in **Claude Code CLI** (`claude -p`), so **no API key and no Anthropic SDK are needed**.

## Product principles (decided with the owner, keep them)

- **Not stealth.** Answers appear in a visible terminal or browser tab. Do **not** add features whose purpose is hiding Tek Bro (from screen share, proctoring, the process list, etc.).
- **Quiet by default.** No macOS notifications or sounds unless `TEKBRO_NOTIFY=1` / `TEKBRO_SOUNDS=1`.
- **Pro-plan friendly.** Claude is only called on a hotkey or button, a typed question, or a detected question. **Auto-screen is off by default**; with it on, a live-coding session can burn the 5-hour Pro window in ~20–30 min.
- **Sonnet by default.** Interview-style problems (LeetCode/HackerRank, concept questions) don't need Opus, and Sonnet is faster. Opus is an opt-in (`--model opus`).
- **Local first.** Audio never leaves the machine (local Whisper). Screenshots and transcripts live in memory only. Only the specific prompt + screenshot for a request goes to Claude.

## Architecture

```
tekbro/
  app.py        Orchestrator: `TekBro` class (job queue + single worker), FastAPI dashboard,
                terminal commands, CLI flags (main()).
  brain.py      Claude via `claude -p` (stream-json in/out, image input, streaming deltas,
                timeout, plan-usage parsing). SYSTEM_PROMPT defines the answer format.
  audio.py      Listener threads (mic via sounddevice, system audio via bin/tekbro-audio),
                silence-based utterance splitting, Whisper, EchoGate, echo text dedupe.
  questions.py  Question detection: sentence split, small-talk stripping, question cues (EN+PT).
  screen.py     ScreenWatcher: mss screenshots every N s, downscaled to ≤1568 px, change detection.
  remote.py     Tailscale remote access: device pairing (one-time codes → hashed device tokens), lockout.
  hotkeys.py    HotkeyListener (runs bin/tekbro-hotkey) + optional macOS notifications.
  config.py     Config dataclass, read from env / .env (TEKBRO_*).
  static/       Dashboard (index.html) + vendored libs (marked, DOMPurify, highlight.js).
native/
  tekbro-audio.swift   ScreenCaptureKit system-audio capture → 16 kHz mono float32 on stdout.
  tekbro-hotkey.swift  Carbon RegisterEventHotKey → prints the action name on stdout.
  build.sh             Builds both into bin/ (auto-run on first launch).
tests/          test_questions.py (unit), echo_test.py (live speakers/mic), stream_pcm.py,
                diagnostics/ (latency measurement scripts).
```

**Data flow:** Listener → `_on_text` → transcript, plus question detection → `Job` queue → single worker → `Brain.ask` → `publish()` events → dashboard SSE (`/events`) + terminal.

**Speakers:** `them` = system audio (the only source that triggers auto-answers), `me` = mic, `audio` = the mic when there's no system-audio source.

## Hard-won knowledge (read before changing these areas)

- **`claude -p` flags** (`brain.py`): `--tools ""` (text only, so prompt injection from the screen can't trigger actions), `--setting-sources project` + `--strict-mcp-config` (isolate from the user's hooks, plugins and MCP connectors), `--no-session-persistence` (nothing saved). `ANTHROPIC_API_KEY` is removed from the env so the subscription login is used. The `rate_limit_event` stream event carries `unifiedWindows.five_hour.utilization`, which is shown in the dashboard.
- **ScreenCaptureKit lifetime bug (fixed):** the `Capturer` and its `SCStream` must be held by a static/global. When it was a local, capture silently stopped after the first frame (0 bytes, no error).
- **Command Line Tools bug:** some CLT versions ship duplicate `SwiftBridging` modulemaps (`module.modulemap` + `bridging.modulemap`), so *any* `swiftc` build fails. `native/build.sh` hides one through a VFS overlay (`-vfsoverlay` **and** `-Xcc -ivfsoverlay`; both are needed). No sudo.
- **Echo gate (speakers without headphones):** measured with envelope cross-correlation on this hardware, system capture arrives ~40–110 ms *before* the mic hears the speakers, with delivery bursts of up to ~100 ms. Window: `LEAD_S=0.35`, `TAIL_S=0.45`. The mic is delayed by LEAD before deciding. A text dedupe (`is_echo_text`, 2.5 s hold) catches leftovers. Threshold-crossing onset measurement is unreliable (room noise); use cross-correlation (`tests/diagnostics/lag_xcorr.py`).
- **Whisper hallucinations** ("Yeah", "Okay, we're due") come from short noise blips. Mitigated by `MIN_VOICED_S=0.3` of loud frames plus dropping segments with `no_speech_prob > 0.6` or `avg_logprob < -1.0`.
- **Whisper on the Apple GPU:** `device="mps", compute_type="float16"` is ~2.5× faster than CPU int8 (2.1 s vs 5.0 s per sentence). It falls back to CPU automatically.
- **CLI audio:** ScreenCaptureKit audio includes CLI processes (`say`, `afplay`) too, once the stream is kept alive.
- **The `say` voice:** the default macOS voice on this machine is Portuguese, so use `say -v Samantha` for English test audio.
- **Sandboxing:** inside a sandboxed agent shell, ScreenCaptureKit and the mic may silently return nothing. Run audio tests from a real terminal.

## Security model (dashboard)

The dashboard exposes the screen and transcript, so `build_api`:
- requires a **Host header** of `127.0.0.1:<port>` / `localhost:<port>` (blocks DNS rebinding),
- requires a **per-run token** (`/?t=…` printed in the terminal, then an HttpOnly `SameSite=Strict` cookie),
- rejects non-GET requests with a foreign `Origin` (blocks CSRF),
- serves vendored JS only (no CDN) and **sanitizes all Claude output with DOMPurify** (the model can echo attacker-controlled screen text).

**Remote access (`--remote`, `remote.py`)** lets the owner read the dashboard on their own phone or laptop while screen-sharing:
- binds **only** to `127.0.0.1` and the Mac's **Tailscale IP** (never `0.0.0.0`), and the middleware rejects any client outside loopback / Tailscale ranges,
- remote clients must present a **paired device token** (the per-run token is local-only). Pairing uses one-time codes that expire after 10 min; only SHA-256 hashes are stored in `~/.config/tekbro/devices.json` (0600), and the file is re-read on change so `--pair` / `--revoke` work on a running instance,
- `FailureLimiter` locks a client out after 10 failed attempts in 10 min.
- Don't add a public-internet mode (ngrok, 0.0.0.0, etc.): the dashboard shows live screenshots and call transcripts.

`tests/test_remote.py` covers all of this in-process; run it after touching `build_api` or `remote.py`.

The `cmd:` audio source (runs a command) is a test hook, disabled unless `TEKBRO_ALLOW_CMD_SOURCE=1`.

## Running and testing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m tekbro                       # full app
.venv/bin/python tests/test_questions.py         # question detection (fast, no audio)
.venv/bin/python tests/test_remote.py            # dashboard security + device pairing (fast)
.venv/bin/python tests/echo_test.py              # live speakers+mic echo test (plays sound!)
REAL=1 .venv/bin/python tests/echo_test.py       # same, with real macOS capture (QuickTime as caller)
./native/test-system-audio.sh                    # helper sanity check → prints OK/FAIL
```

When you change `questions.py`, add the case to `tests/test_questions.py`. When you change `audio.py`, run `echo_test.py` with and without `REAL=1`.

## Conventions

- Python 3.12, stdlib + the pinned deps in `requirements.txt`. No Anthropic SDK (by design).
- Keep config in `config.py` (`TEKBRO_*` env vars) with matching CLI flags in `app.main()`, and document new ones in the README.
- macOS-only native code lives in `native/`. Everything else should stay portable where cheap.
- Never commit `.env`, `bin/`, `build/`, `captures/` or any audio/screenshot artifacts.
