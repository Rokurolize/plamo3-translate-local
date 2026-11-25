# Setup

## Prerequisites

- **Python 3.10+** or [uv](https://docs.astral.sh/uv/). The manager needs no third-party packages. `uv run --no-project` is used by the launcher when available, with a plain `python` fallback.
- **llama.cpp with `llama-server`, build b12182 or newer.** Older builds (e.g. b11149) fail with `unknown tokenizer: 'plamo3'`. Check with `llama-server --version`.
- Disk space for the weights: ~7.7 GB for all three Q4_K_M files (573 MB + 1.8 GB + 5.3 GB), plus a little headroom for `.part` files while downloading.
- Optional: a Vulkan/CUDA/Metal GPU. CPU inference works but is much slower.

## Windows (recommended)

```powershell
git clone https://github.com/Rokurolize/plamo3-translate-local.git
cd plamo3-translate-local
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -All -RegisterTask
```

The script:

1. Finds `uv` or `python`.
2. Finds `llama-server` on PATH or under `winget`'s `ggml.llamacpp_*` package folder. If missing, install with `winget install --id ggml.llamacpp -e` (or grab a release zip from the llama.cpp GitHub repo).
3. Runs `fetch-models.py --all --verify` — resumable download with size + SHA-256 checks against `models.json`.
4. With `-RegisterTask`, registers and starts the `PLaMo 3 Translate` logon task.

Start manually at any time with:

```powershell
.\start-plamo.bat            # model 0.8b, port 8000
& .\start-plamo.bat 8b 8000  # explicit size/port
```

Open <http://127.0.0.1:8000/>.

## macOS / Linux

There is no launcher script needed:

```bash
python fetch-models.py --all --verify
python manager.py --model 0.8b --port 8000
```

If `llama-server` is not on PATH: `python manager.py --llama-server /abs/path/to/llama-server`.

Optional systemd user unit (`~/.config/systemd/user/plamo.service`):

```ini
[Unit]
Description=PLaMo 3 Translate manager
After=network.target

[Service]
WorkingDirectory=/abs/path/to/plamo3-translate-local
ExecStart=/usr/bin/python3 manager.py --model 0.8b
Restart=on-failure

[Install]
WantedBy=default.target
```

Enable with `systemctl --user enable --now plamo.service`.

## `manager.py` options

| Flag | Default | Meaning |
|------|---------|---------|
| `--model` | `0.8b` | Initial model: `0.8b`, `2b`, or `8b` |
| `--port` | `8000` | Local WebUI/API port (loopback only) |
| `--backend-port` | `8001` | Internal llama-server port |
| `--public-port` | `8445` | Gated listener; `0` disables it |
| `--public-host` | `0.0.0.0` | Gated listener bind address |
| `--public-path` | `/plamo` | External path prefix used by the Funnel |
| `--token` | from file | Override the access token |
| `--llama-server` | auto | Path to `llama-server(.exe)` |

`PLAMO_LLAMA_SERVER` is an alternative to `--llama-server`. Discovery order: flag → env var → PATH → winget package glob.

## Verifying the install

```bash
curl http://127.0.0.1:8000/api/status
python translate_test.py
```

Expected status: `{"running": true, "model": "0.8b", ..., "alias": "plamo-3-translate"}`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `unknown tokenizer: 'plamo3'` | Upgrade llama.cpp to b12182+ |
| `[manager] port 8000 is already serving HTTP` | Another copy is running; `netstat -ano \| findstr :8000`, stop it, retry |
| API returns 503 "model server is not reachable" | Click Start in the UI or `POST /api/switch`; check model file exists |
| garbled `'oint' is not recognized` from a `.bat` | Non-ASCII bytes in the file; keep `.bat` 100% ASCII |
| `Vulkan0 ... Flash Attention ... assigned to CPU` warning | Harmless; inference continues, sometimes slightly slower |
| WebUI says "Model controls unavailable" | Page not served by manager (opened as a file or via another server) |
