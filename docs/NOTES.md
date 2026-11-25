# Implementation notes and decisions

This file preserves the reasoning behind the current design so future contributors (human or LLM) don't re-litigate solved problems.

## Backend

- llama.cpp was upgraded via winget from build **11149** to **b12182**. The old build failed with `unknown tokenizer: 'plamo3'`; this is a backend-version issue, not a prompt issue.
- All three sizes use the recommended **Q4_K_M** quantization, downloaded from the `pfnet/plamo-3-translate-*-GGUF` Hugging Face repos. The 8B file was replaced during development (now 5,280,445,728 bytes, SHA-256 `94e5...187`) and the old `.old` copy removed. `models.json` records all current hashes.
- Default first-load model is **0.8b** — fast enough for interactive use and the lightest on VRAM.
- Context was raised from `-c 16384` to **`-c 32768`** to match the models' training limit. This is the combined input+output budget; character counts depend on language.

## Observed performance

| Size | Decode | VRAM | RAM |
|------|--------|------|-----|
| 8b | ~68–71 tok/s | 7,717 MiB | 5,040/5,867 MB |
| 2b | ~162–169 tok/s | 4,175 MiB | 1,789/2,386 MB |
| 0.8b | ~483–501 tok/s | 2,622 MiB | 661/832 MB |

## Networking and security

- The gated public listener uses **8445**. Port 8443 is occupied by WikiJump on WSL, and 8444 was abandoned because the tailnet ACL allows only `443, 8443, 10000`; it caused `ERR_CONNECTION_TIMED_OUT`.
- Public access is Tailscale Funnel port **10000** with external path **`/plamo`** → `http://127.0.0.1:8445`. Everything else on the gated listener returns a generic 404, including for scanners.
- Token gate: exact token in `?token=` → 30-day HttpOnly/Secure cookie holding only `sha256(token)`; bearer token for API clients; constant-time comparisons via `secrets.compare_digest`. Rotation = delete `.plamo_access_token` and restart.

## Persistence

- Originally a Startup shortcut; replaced with Task Scheduler task **`PLaMo 3 Translate`**, trigger *At logon* for the current user, action `run-at-logon.bat` → `start-plamo.bat`. The Startup shortcut was removed to avoid duplicate starts.
- Earlier task actions using `cmd /c start "" /min` and nested PowerShell quoting silently produced exit code 0 with no process. A tiny internal wrapper batch file (`run-at-logon.bat`) made quoting unambiguous.
- The running chain is `svchost.exe (Task Scheduler) → cmd → uv → python (manager.py) → llama-server.exe`, entirely detached from the interactive shell.
- `run-at-logon.bat` discards output so logs cannot grow without bound.

## The non-ASCII batch-file bug

Adding a `rem` comment containing the Japanese project folder name to `start-plamo.bat` broke cmd.exe under Task Scheduler's console codepage: the UTF-8 bytes decoded into shell metacharacters and cmd tried to run `'oint'` and `'0.8b'` as commands. All `.bat` files are now **pure ASCII** and use `%~dp0` instead of literal paths. This is why `AGENTS.md` calls it a hard rule.

## Manager fixes

- **CPU busy-loop**: a dead client raised `ConnectionError` in `handle_one_request()` and the `handle()` loop retried forever, burning ~123% of one core with 50 threads. Setting `close_connection = True` on `ConnectionError` fixed it: idle CPU 0%, threads ~10.
- **Port preflight**: Windows can allow a second HTTP bind via `SO_REUSEADDR`, silently routing visitors to the wrong server. The manager probes 8000/8445 with `/api/status` and refuses to start if already served.
- **SSE proxy**: `resp.read1()` + `flush()` per chunk was required to stream tokens immediately; plain `read()` buffers.
- Failed model switches validate the target file before stopping the running model, so a typo does not unload a working server.
- `manager.py` in this repo resolves `llama-server` through `--llama-server` → `PLAMO_LLAMA_SERVER` → PATH → winget glob, replacing a hard-coded path with a username in it.

## WebUI

- Two permanent panels show JA→EN and EN→JA simultaneously. Controls (Translate, Clear, Copy, Paste) sit in each panel's label bar next to the relevant field, minimizing wasted space.
- Pasting into a field triggers translation immediately. Mobile browsers generally won't run programmatic `paste()`, so the Paste button has a fallback: focus/select the old text and guide the user to the OS paste.
- Auto reverse translation is **on** by default (verification), Sync scroll **off**, Highlight **on**. A Fit/Full toggle shrinks short results on phones (iPhone SE, 375 px) so nothing clips.
- Paragraph highlighting uses a mirrored text layer aligned to the textarea's usable width; autoscroll is suppressed while the user is interacting.
- The UI rejects source text containing literal `<|plamo:` tokens with an inline error.

## Prompt formats

- Raw pass-through must begin **exactly** with `<|plamo:tag|>dataset<|plamo:msg|>translation`; the WebUI builds the rest (`input` / `output` + `lang` value) itself.
- Putting raw PFML tokens into ordinary chat messages caused `Unable to generate parser for this template ... message content must not contain reserved PFML tokens`. For chat completions, use `chat_template_kwargs.target_lang` (`ja` / `en` / `auto`; with `auto`, omit `source_lang`; `form` needs `target_lang=ja`).
- Stop tokens: `["<|plamo:tag|>", "<|plamo:bos|>"]`.

## Immersive Translate settings

API URL `http://127.0.0.1:8000/v1/chat/completions`, model `plamo-3-translate`, any API key, prompt `{{text}}`, body `{"temperature":0}`, rate limit 2–3/s (5/s for 0.8b), `maxTextLengthPerRequest` 1200–2000. System prompt `[plamo-translate]\ntarget_lang=auto` for ja↔en auto-switching, or `target_lang=ja` to force Japanese. Switching model sizes in the UI does not require touching these settings.
