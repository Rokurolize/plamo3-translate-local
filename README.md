# PLaMo 3 Translate — local WebUI + OpenAI-compatible API

Run [PLaMo 3 Translate](https://huggingface.co/collections/pfnet/plamo-3-translate) models locally behind a small, dependency-free Python manager. The manager serves a compact WebUI, proxies the OpenAI-compatible API, lets you switch model sizes live, and can expose a token-gated endpoint through Tailscale Funnel.

Everything in this repo is stdlib Python + one self-contained HTML file. The only external pieces are `llama-server` (llama.cpp) and the GGUF weights, both downloaded during setup.

## Features

- **Two permanent panels**: Japanese → English and English → Japanese at the same time.
- **Icon controls**: a single 📋 button to the left of each "Original" label pastes clipboard text (replacing the old text) and translates immediately, or clears both boxes if the clipboard is empty. A matching ⧉ button to the left of each "Translation" label copies the result. Auto-reverse verification and paragraph highlight included.
- **Draggable divider** between Original and Translation in each panel — resize the two boxes to suit your reading (pointer drag, arrow keys, saved across reloads).
- **Sync scroll on by default**: scrolling or clicking a paragraph in one field brings the matching paragraph into view in the other, using real line positions rather than character-count estimates.
- **Live model switch** between `0.8b`, `2b`, and `8b` without restarting the manager or reconfiguring API clients (alias is always `plamo-3-translate`).
- **OpenAI-compatible** `/v1/completions` and `/v1/chat/completions` proxies, including SSE streaming.
- **Token-gated public listener** for Tailscale Funnel; everyone else sees an ordinary 404 for every path.
- **Persists at logon** on Windows via Task Scheduler; no desktop shortcut needed.

## Quick start (Windows)

Prerequisites: [uv](https://docs.astral.sh/uv/) or Python 3.10+, and llama.cpp **build b12182 or newer** (`unknown tokenizer: 'plamo3'` means your build is too old).

```powershell
git clone https://github.com/Rokurolize/plamo3-translate-local.git
cd plamo3-translate-local
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -All -RegisterTask
```

Then open <http://127.0.0.1:8000/>. `setup-windows.ps1` checks the runtime, downloads the three Q4_K_M models with hash verification, and (with `-RegisterTask`) registers a logon task. To start without registering the task:

```powershell
.\start-plamo.bat          # or: python manager.py --model 0.8b
```

### Desktop / Start menu shortcut

`PLaMo 3 Translate.lnk` is placed on the Desktop and in the current user's Start Menu (**All apps**). Double-clicking it starts the manager if it is down, or **restarts the loaded model** if the manager is already running — handy after a GPU driver update kills `llama-server`. To put a tile on the Start screen: open **Start → All apps**, right-click **PLaMo 3 Translate**, choose **Pin to Start**. (Windows 11 does not allow pinning from a script.)

## Any other OS

```bash
python fetch-models.py --all --verify      # downloads into the repo's model folders
python manager.py --model 0.8b             # llama-server must be on PATH
```

If `llama-server` is not on PATH, pass `--llama-server /path/to/llama-server` or set `PLAMO_LLAMA_SERVER`. See [docs/SETUP.md](docs/SETUP.md).

## Models

Q4_K_M quantization, 32,768-token context (the models' training limit). Numbers are from an RTX-class GPU; character capacity depends on language.

| Size | File size | Decode speed | VRAM | RAM |
|------|-----------|--------------|------|-----|
| 0.8b (default) | 573 MB | ~480–500 tok/s | ~2.6 GiB | ~0.8 GB |
| 2b | 1.8 GB | ~160–170 tok/s | ~4.2 GiB | ~2.4 GB |
| 8b | 5.3 GB | ~68–71 tok/s | ~7.7 GiB | ~5.9 GB |

Model files are **not** in git. `models.json` has URLs, byte sizes, and SHA-256 hashes.

## Ports

| Port | Bind | Purpose |
|------|------|---------|
| 8000 | `127.0.0.1` | WebUI + control API + OpenAI proxy (no token needed) |
| 8001 | `127.0.0.1` | Internal `llama-server`, never exposed directly |
| 8445 | `0.0.0.0` | Token-gated listener for Tailscale Funnel to forward to |
| 10000 | tailnet | Tailscale Funnel port, path `/plamo/` (see [docs/TAILSCALE.md](docs/TAILSCALE.md)) |

Ports 8443/8444 are deliberately avoided: 8443 is used by another local service and Tailscale's ACL here only allows 443, 8443, and 10000.

## API at a glance

```bash
curl http://127.0.0.1:8000/api/status
curl -X POST http://127.0.0.1:8000/api/switch -H "Content-Type: application/json" -d '{"model":"2b"}'
curl -X POST http://127.0.0.1:8000/api/stop
curl -X POST http://127.0.0.1:8000/api/restart
```

Translation uses either the raw PFML prompt (`/v1/completions`, what the WebUI uses for streaming) or the model's chat template with `chat_template_kwargs.target_lang` (`/v1/chat/completions`). Full examples and browser-extension settings are in [docs/API.md](docs/API.md).

## Security

- Local port 8000 requires no token; keep it bound to loopback (the default).
- The generated access token lives in `.plamo_access_token`, which is gitignored. Delete it and restart to rotate it. **Never commit it.**
- Unauthenticated requests to the public listener get a generic `404`, with no hint that a translation service or a token exists. A valid `?token=...` sets a 30-day HttpOnly/Secure cookie; `Authorization: Bearer <token>` works for non-browser clients.

## Repository layout

```
manager.py            stdlib proxy + lifecycle manager + token gate
webui/index.html      entire WebUI (no build step, no dependencies)
start-plamo.bat       single user-facing launcher (must stay pure ASCII)
start-plamo.ps1       thin wrapper around the .bat
run-at-logon.bat      internal Task Scheduler wrapper
fetch-models.py       resumable, hash-verified GGUF downloader
models.json           model URLs / sizes / SHA-256
setup-windows.ps1     one-shot Windows setup (+ optional task registration)
translate_test.py     dependency-free chat-template smoke test
docs/                 setup, API, architecture, Tailscale, implementation notes
AGENTS.md             instructions for LLM agents working on this repo
```

Documentation: [Setup](docs/SETUP.md) · [API](docs/API.md) · [Architecture](docs/ARCHITECTURE.md) · [Remote access](docs/TAILSCALE.md) · [Implementation notes](docs/NOTES.md)

## License

The wrapper code in this repository is MIT licensed ([LICENSE](LICENSE)). The GGUF weights are governed by the [PLaMo Community License](https://huggingface.co/pfnet/plamo-3-translate-8b-GGUF/blob/main/LICENSE) from Preferred Networks; this repository does not redistribute them.
