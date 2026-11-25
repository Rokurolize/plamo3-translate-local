# Instructions for LLM agents working on this repository

This repo packages a *working* local translation service. Treat these as invariants unless the user explicitly asks to change them.

## What this is

`manager.py` serves the WebUI at `http://127.0.0.1:8000/` and reverse-proxies `/v1/*` to a child `llama-server` on port 8001. It also runs an optional token-gated listener on 8445 for Tailscale Funnel. The WebUI is a single self-contained `webui/index.html`.

## Hard rules

1. **Keep `manager.py` standard-library only.** No pip dependencies, no build step. That is why it can run with bare `python` or `uv run --no-project`.
2. **Keep every `.bat` file pure ASCII and use `%~dp0`.** A non-ASCII byte in a comment caused cmd.exe (under Task Scheduler's codepage) to try to execute `'oint'` and `'0.8b'`. Literal absolute paths with non-ASCII folder names caused the same class of failure. Verify with a byte check before committing a `.bat`.
3. **Never commit secrets or weights.** `.plamo_access_token`, `*.gguf`, `*.log`, `**/.cache/` are gitignored for a reason. Check `git status` before every commit. If a token was ever committed, rotate it (delete the file, restart the task) — deleting in a later commit is not enough.
4. **Do not change port assignments casually.** 8000 = local UI/API, 8001 = internal llama-server, 8445 = gated public listener, 10000 = Tailscale Funnel with path `/plamo/`. The WebUI derives its fetch prefix from `location.pathname.startsWith('/plamo')`; a path change must be reflected in both the manager's `GATE_PATH` and the Tailserve config.
5. **The API alias is always `plamo-3-translate`.** Switching sizes must not require reconfiguring Immersive Translate or other clients.
6. **`CTX = 32768` is the model training limit**, not an arbitrary knob. Raising it breaks assumptions about supported input length.
7. **The WebUI has two permanent direction panels.** JA→EN and EN→JA must remain visible simultaneously; controls live in each panel's label bar; pasting into a field triggers translation immediately. Preserve this when editing CSS/JS.
8. **Raw PFML is strict.** Pass-through prompts must begin exactly with `<|plamo:tag|>dataset<|plamo:msg|>translation`, and source text must never contain literal `<|plamo:` tokens (the WebUI filters them). Ordinary chat messages must not contain those tokens either — doing so caused a Jinja parser error about reserved PFML tokens.
9. **Model builds matter.** `unknown tokenizer: 'plamo3'` means llama.cpp is older than b12182. Don't debug prompts before checking the backend build/version.
10. **Never add unbounded console logging to the Task Scheduler wrapper.** `run-at-logon.bat` deliberately discards output.

## Editing guide

- Backend lifecycle: `Manager` class in `manager.py` (start/stop/switch, health wait, proxy). The proxy uses `resp.read1()` so SSE tokens stream immediately; keep that.
- HTTP gating: `GateHandler` (URL token → HttpOnly cookie → 302; bearer token for API clients; hash-derived cookie value; 404 for everyone else). `version_string()` returns `nginx` on purpose.
- CPU bug to avoid: a dead client raised `ConnectionError` in `handle_one_request()` and the server spun at ~123% of a core. `Handler.handle_one_request()` sets `close_connection = True` on `ConnectionError`; keep it.
- WebUI behavior: `buildPrompt()` + `/v1/completions` (streaming), auto-reverse, `paintMirror()` highlight, guarded scroll sync, mobile-safe paste fallback, Fit/Full toggle. Test on a narrow viewport (iPhone SE, 375 px) after UI changes.
- Model files: `models.json` is the source of truth for URLs/sizes/hashes; `fetch-models.py` resumes via `.part` and verifies before renaming.

## Verification checklist

```bash
python -m py_compile manager.py fetch-models.py translate_test.py
curl.exe http://127.0.0.1:8000/api/status
python translate_test.py
curl.exe -o NUL -w "%{http_code}" http://127.0.0.1:8445/          # expect 404
curl.exe -o NUL -w "%{http_code}" "http://127.0.0.1:8445/?token=<token>"  # expect 302
```

For UI work, also load `http://127.0.0.1:8000/` at desktop width and 375 px, and check both panels translate.

## Windows persistence

Task name: `PLaMo 3 Translate`; trigger: AtLogOn for the current user; action: `run-at-logon.bat` → `start-plamo.bat`. Manage with `Start-ScheduledTask` / `Stop-ScheduledTask`. The Startup shortcut was intentionally removed — do not recreate it.

## Further reading

[README.md](README.md), [docs/SETUP.md](docs/SETUP.md), [docs/API.md](docs/API.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/TAILSCALE.md](docs/TAILSCALE.md), [docs/NOTES.md](docs/NOTES.md).
