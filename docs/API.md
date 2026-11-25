# API

The manager exposes three kinds of endpoints on port 8000: control, OpenAI-compatible proxy, and the WebUI itself. The public gated listener on 8445 exposes the same routes once authenticated.

## Control endpoints

| Method | Path | Body / result |
|--------|------|---------------|
| GET | `/api/status` | `{"running": bool, "model": "0.8b"\|"2b"\|"8b"\|null, "lastModel": ..., "pid": int\|null, "backendPort": 8001, "alias": "plamo-3-translate"}` |
| POST | `/api/switch` | `{"model": "8b"}` — validates first, unloads current model, spawns new one, waits for `/health` (up to 180 s). A failed switch leaves the old model loaded. |
| POST | `/api/stop` | Unloads the model server; manager and WebUI stay up. |
| POST | `/api/restart` | Reloads `lastModel`. |

```bash
curl http://127.0.0.1:8000/api/status
curl -X POST http://127.0.0.1:8000/api/switch -H "Content-Type: application/json" -d '{"model":"2b"}'
```

Switching takes roughly 30 s for the large models. All sizes use the same model alias, so API clients need no changes.

## Translation path 1 — raw PFML (`/v1/completions`)

This is what the WebUI uses because it streams token-by-token over SSE. The prompt must start **exactly** with the dataset/translation prefix:

```
<|plamo:tag|>dataset<|plamo:msg|>translation<|plamo:tag|>input<|plamo:msg|>SOURCE<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>TARGET<|plamo:msg|>
```

```bash
curl -N http://127.0.0.1:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "plamo-3-translate",
    "prompt": "<|plamo:tag|>dataset<|plamo:msg|>translation<|plamo:tag|>input<|plamo:msg|>会議は来週の月曜日に変更されました。<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>",
    "temperature": 0,
    "max_tokens": 512,
    "stop": ["<|plamo:tag|>", "<|plamo:bos|>"],
    "stream": true
  }'
```

Rules:

- `TARGET` is `en` or `ja`. The WebUI's two panels are just this call with the target flipped.
- Source text must **not** contain literal `<|plamo:` tokens. The model rejects them; the WebUI blocks them in the UI with an error message.
- `stop` prevents the model from continuing into another dataset record.
- Responses are SSE (`data: {...}\n\n`, ending with `data: [DONE]`). The manager proxies chunks with `read1()` so streaming is not buffered.

## Translation path 2 — chat template (`/v1/chat/completions`)

Simpler for third-party tools. The model's Jinja template accepts `chat_template_kwargs`:

```json
{
  "model": "plamo-3-translate",
  "messages": [{"role": "user", "content": "The meeting has been rescheduled to next Monday."}],
  "temperature": 0,
  "max_tokens": 512,
  "stop": ["<|plamo:tag|>", "<|plamo:bos|>"],
  "chat_template_kwargs": {"target_lang": "ja"}
}
```

- `target_lang`: `ja`, `en`, or `auto`. With `auto` the model detects Japanese↔English and you **omit** `source_lang`.
- `form` mode requires `target_lang=ja`.
- Do not put raw `<|plamo:...|>` tokens into ordinary messages — that previously produced `Unable to generate parser for this template ... message content must not contain reserved PFML tokens`. Use the raw-completions path for PFML.
- `translate_test.py` exercises this path with both directions.

## Immersive Translate (browser extension)

| Setting | Value |
|---------|-------|
| API URL | `http://127.0.0.1:8000/v1/chat/completions` |
| Model | `plamo-3-translate` |
| API key | any non-empty string (the manager ignores it on loopback) |
| Prompt template | `{{text}}` |
| Request body | `{"temperature": 0}` is fine |
| Rate limit | 2–3 requests/s (5/s is OK with 0.8b) |
| maxTextLengthPerRequest | 1200–2000 characters |
| System prompt | `[plamo-translate]\ntarget_lang=auto` for ja↔en auto-detection, or `target_lang=ja` to force Japanese |

Over Tailscale, use the Funnel URL with `/v1/chat/completions` and set the API key to the gate token (sent as `Authorization: Bearer <token>`).

## Limits

- All three models were trained on **32,768 combined tokens**; the manager starts `llama-server` with `-c 32768`.
- Character capacity therefore depends on language (Japanese is denser in tokens). Keep requests well below the context limit to leave room for output.
- The WebUI caps `max_tokens` at 8192 and scales it from input length.

## Public / gated access

```bash
# Browser: one-time token in the URL sets a 30-day cookie and redirects to the clean path
curl -L "https://<host>.ts.net:10000/plamo/?token=<token>"

# API clients: bearer token, no cookie needed
curl -H "Authorization: Bearer <token>" https://<host>.ts.net:10000/plamo/v1/chat/completions ...
```

Without a token, every path returns a generic `404` with no service identification. See [TAILSCALE.md](TAILSCALE.md).
