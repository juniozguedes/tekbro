# 🤙 Tek Bro

<p align="center"><img src="assets/mascot.svg" width="340" alt="Tek Bro mascot: a big bro in a #1 cap hugging a nerd with round glasses"></p>

**Your live technical copilot for calls, interviews and coding sessions, running locally on your Mac.**

Tek Bro listens to the conversation, notices when someone asks a technical question, and answers it. When code shows up on your screen, one hotkey gets you the solution, ready-to-paste code and a short explanation.

> ### ✅ Works with your Claude Pro plan. No API key needed.
> Tek Bro talks to Claude through the **Claude Code CLI** you're already logged into. If `claude` works in your terminal, Tek Bro works. Nothing to configure: no API key, no Anthropic Console, no billing setup. (Claude Max works too.)

---

## ✨ Features

| | Feature | What it does |
|---|---|---|
| 🎧 | **Hears both sides of the call** | Captures the call audio natively on macOS (Teams, Zoom, Meet, Discord…) plus your mic. No virtual audio driver needed |
| 📝 | **Local transcription** | Whisper runs **on your Mac's GPU**, so audio never leaves your machine. English and Portuguese, auto-detected |
| ❓ | **Smart question detection** | Answers real questions ("How does a hash map work?", "Given an array…", "Por quê?") and ignores small talk ("Hi, how are you?", "Can you hear me?", "Tá me ouvindo?") |
| 🧠 | **Instant answers** | Every answer comes in the same shape: **Answer** (what to say), **Code** (ready to paste), **Why** (approach, complexity, edge cases) |
| 🖥️ | **Screen solving** | Press **⌃⌥S** anywhere and Tek Bro reads the problem or code on your screen (LeetCode, HackerRank, your IDE) and solves or fixes it |
| 🔊 | **Speakers or headphones** | Built-in echo suppression: without headphones, the other person's voice from your speakers isn't transcribed again as yours |
| ⌨️ | **Global hotkeys** | Work from any app, with no Accessibility permission needed |
| 📊 | **Live dashboard** | Transcript, answers with syntax highlighting and copy buttons, latest screenshot, and your **Claude plan usage** |
| 🔒 | **Private and locked down** | Everything runs on localhost; the dashboard is protected by a per-session token; nothing is written to disk |

---

## 🚀 Quick start

**You need:** a Mac on macOS 13+ (Apple Silicon recommended), Python 3.11+, the Xcode Command Line Tools (`xcode-select --install`), and [Claude Code](https://claude.com/claude-code) logged in with your Claude account.

```bash
# 1. Install
cd tek-bro
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Make sure Claude Code is logged in (one time). If `claude` opens normally, you're set.
claude

# 3. Run
.venv/bin/python -m tekbro
```

Then open the **dashboard link printed in the terminal** (it includes a private access token):

```
Dashboard: http://127.0.0.1:8765/?t=…
```

**First run:**
- macOS asks for **Screen Recording** (screenshots + call audio) and **Microphone** permissions for your terminal app. Allow both, then restart the terminal.
- The Whisper speech model downloads once (~0.5 GB).
- The small native helpers (audio capture, hotkeys) compile automatically.

Tek Bro starts listening right away. 🎉

---

## 🎮 How to use it

### Global hotkeys (from any app)

| Keys | Action |
|---|---|
| **⌃⌥S** (Control + Option + S) | Take a fresh screenshot and **solve what's on screen** |
| **⌃⌥A** (Control + Option + A) | **Answer the last question** heard in the call |

### Terminal commands (type + Enter)

| Input | Action |
|---|---|
| `s` | Solve the screen |
| `a` | Answer the last question |
| `t` | Toggle auto-screen on/off |
| *any text* | Ask Claude anything, with your current screen attached, e.g. `what's the complexity of this?` |
| `h` | Help |
| `q` | Quit |

### Dashboard

- **Buttons:** Solve screen · Answer last question · Auto screen · Auto answer
- **Keys** while the page is focused: `s`, `a`
- **Ask box** for typed questions, and a **copy** button on every code block
- **Live transcript** (`them` = call audio, `me` = your mic) and the latest screenshot
- **Plan usage:** how much of your 5-hour Claude window you've used (turns red at 80%)

### What happens automatically

| Behaviour | Default | Uses Claude? |
|---|---|---|
| Transcribing the call and your mic | on | ❌ local |
| Screenshot every 5 s (dashboard preview) | on | ❌ local |
| **Auto-answer** detected questions from the call | on | ✅ per question |
| **Auto-screen** (solve whenever the screen changes) | **off** | ✅ per change: expensive, see below |

---

## 🤖 Changing the AI model ("agent")

Tek Bro uses **Claude Sonnet** by default: fast and more than enough for interview-style problems.

```bash
.venv/bin/python -m tekbro --model sonnet   # default: fast, great for LeetCode/HackerRank-style problems
.venv/bin/python -m tekbro --model opus     # strongest reasoning, slower, uses more of your plan
.venv/bin/python -m tekbro --model haiku    # fastest and lightest
```

Make it permanent in a `.env` file (copy `.env.example`):

```bash
TEKBRO_MODEL=opus      # sonnet | opus | haiku | or a full model id
TEKBRO_EFFORT=medium   # low = faster · medium · high = more careful
```

You can also change **how Tek Bro answers** (tone, format, language) by editing `SYSTEM_PROMPT` in `tekbro/brain.py`.

---

## 🎧 Audio setup

By default Tek Bro captures **all system audio** as the other side of the call, and your **default mic** as you.

```bash
.venv/bin/python -m tekbro --call-app Teams      # only capture one app (Teams, zoom, Chrome for Meet…)
.venv/bin/python -m tekbro --list-apps           # apps you can target
.venv/bin/python -m tekbro --mic "MacBook"       # choose a mic (see --list-devices)
.venv/bin/python -m tekbro --list-devices        # list mics / input devices
.venv/bin/python -m tekbro --headphones          # keep your mic open while they talk
.venv/bin/python -m tekbro --system off          # mic only
.venv/bin/python -m tekbro --system BlackHole    # use a loopback device instead of native capture
```

**Speakers vs headphones:** with speakers, Tek Bro mutes the mic while the other person is talking, so their voice isn't transcribed twice. The trade-off is that you aren't transcribed while you talk over them. On headphones, use `--headphones` to keep the mic always open.

**Tip:** `--call-app` keeps Spotify, YouTube or notification sounds out of the transcript.

---

## 💸 Claude Pro usage

On Pro there's no per-call cost, but there **are usage limits** (a rolling 5-hour window plus a weekly cap). The dashboard shows your current 5-hour usage.

| Setup | Claude calls per 1-hour session (approx.) |
|---|---|
| Hotkeys only (⌃⌥S / ⌃⌥A) | 3–10 |
| + auto-answer (default) | 20–60 |
| + auto-screen during live coding | 150–250 ⚠️ likely to hit the Pro limit in 20–30 min |

**Recommended:** keep auto-screen off and press **⌃⌥S** when code appears. If you're running low, turn off auto-answer in the dashboard and use **⌃⌥A** only for the questions you care about.

---

## ⚙️ All options

### Command-line flags

| Flag | Description |
|---|---|
| `--model NAME` | Claude model: `sonnet` (default), `opus`, `haiku`, or a full id |
| `--call-app NAME` | Only capture audio from this app |
| `--system SRC` | Call audio source: `macos` (default), `off`, or a device name |
| `--mic DEVICE` | Microphone (name or index) |
| `--headphones` | Disable echo suppression |
| `--auto-screen` | Solve automatically whenever the screen changes |
| `--interval SECONDS` | Screenshot interval (default 5) |
| `--monitor N` | Which display to capture (1 = main) |
| `--port N` | Dashboard port (default 8765) |
| `--no-audio` / `--no-screen` / `--no-hotkeys` / `--no-dashboard` | Turn features off |
| `--list-apps` / `--list-devices` | Show capturable apps / audio inputs |

### Environment variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TEKBRO_MODEL` | `sonnet` | Claude model |
| `TEKBRO_EFFORT` | `medium` | `low` / `medium` / `high` reasoning effort |
| `TEKBRO_WHISPER_MODEL` | `small` | `base` (faster) · `small` · `medium` (more accurate) · `large-v3` |
| `TEKBRO_LANGUAGE` | auto | Force a language, e.g. `en` or `pt` |
| `TEKBRO_SYSTEM_AUDIO` | `macos` | `macos`, `off`, or a loopback device |
| `TEKBRO_CALL_APP` | — | Only capture this app's audio |
| `TEKBRO_MIC_DEVICE` | default mic | Mic name or index |
| `TEKBRO_ECHO_CANCEL` | `1` | `0` = same as `--headphones` |
| `TEKBRO_AUTO_ANSWER` | `1` | Auto-answer detected questions |
| `TEKBRO_AUTO_SCREEN` | `0` | Auto-solve on screen change |
| `TEKBRO_SCREEN_INTERVAL` | `5` | Seconds between screenshots |
| `TEKBRO_MONITOR` | `1` | Display to capture |
| `TEKBRO_HOTKEYS` | `1` | Global hotkeys on/off |
| `TEKBRO_HOTKEY_SOLVE` | `ctrl+alt+s` | Solve-screen hotkey (`cmd`, `alt`, `ctrl`, `shift` + key) |
| `TEKBRO_HOTKEY_ANSWER` | `ctrl+alt+a` | Answer-question hotkey |
| `TEKBRO_NOTIFY` | `0` | macOS notification when a hotkey answer is ready |
| `TEKBRO_SOUNDS` | `0` | Click sound on hotkey press |
| `TEKBRO_PORT` | `8765` | Dashboard port |

---

## 🔒 Privacy and security

- **What stays on your Mac:** all audio and transcription, the screenshot loop, and the dashboard. Nothing is written to disk.
- **What goes to Claude:** only the prompt for a specific request, meaning the recent transcript and/or one screenshot, sent through your own Claude Code login.
- **Isolated Claude sessions:** Tek Bro runs Claude with **no tools, no MCP connectors, no plugins or hooks**, and without saving sessions. Text on your screen can't make it take actions.
- **Locked-down dashboard:** localhost only, with a private per-run token, protection against malicious websites (DNS rebinding and cross-site requests), and sanitized rendering of every answer.
- **Be fair to others:** Tek Bro transcribes other people's voices. Let participants know, and follow the recording-consent rules where you live and of the meeting you're in.

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| No `[them]` lines in the transcript | Run `./native/test-system-audio.sh`. It should print `OK`. If not, grant **Screen Recording** to your terminal and restart it |
| No `[me]` lines | Grant **Microphone** to your terminal; check `--list-devices` |
| "Unauthorized" in the browser | Open the full link printed in the terminal (it includes `?t=…`). The token changes every run |
| Hotkey does nothing | Another app may own that combo. Change it with `TEKBRO_HOTKEY_SOLVE=ctrl+alt+j` |
| `Claude CLI failed` | Run `claude` once in your terminal and make sure you're logged in |
| Answers are slow | Use `--model sonnet` (default) or `haiku`, and `TEKBRO_EFFORT=low` |
| Swift build error "redefinition of module SwiftBridging" | Already handled by `native/build.sh`. Run it directly to see the full error |

---

## 🧪 Development

```bash
.venv/bin/python tests/test_questions.py        # question detection (42 cases, EN+PT)
.venv/bin/python tests/echo_test.py             # live echo test with real speakers + mic (plays sound)
REAL=1 .venv/bin/python tests/echo_test.py      # same, with real macOS capture
./native/test-system-audio.sh                   # system-audio capture sanity check
./native/build.sh                               # rebuild native helpers
```

Architecture, design decisions and hard-won gotchas are in **[AGENTS.md](AGENTS.md)**.

```
tekbro/        Python app: orchestrator, Claude bridge, audio, screen, hotkeys, dashboard
native/        Swift helpers: system-audio capture, global hotkeys
tests/         unit + live tests, latency diagnostics
```
