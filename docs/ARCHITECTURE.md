# Architecture

```
                 browser / API client
                          |
              http://127.0.0.1:8000   (local, no token)
              https://<tailnet>:10000/plamo/   (gated via Funnel)
                          |
                  +-------+--------+
                  | manager.py      |
                  |  Handler        |  static WebUI, /api/*, /v1/* proxy
                  |  GateHandler    |  token gate, /plamo prefix strip
                  +-------+--------+
                          | 127.0.0.1:8001
                  +-------v--------+
                  | llama-server   |  child process, -c 32768, --jinja
                  +----------------+
```

`manager.py` is a single-threaded-logic, multi-threaded-I/O service using only the Python standard library.

## Threads and state

- `ThreadingHTTPServer` serves the local port; a second `ThreadingHTTPServer` with `GateHandler` runs in a daemon thread when `--public-port` is nonzero.
- One `Manager` instance owns the child `llama-server` process behind a `threading.Lock`. Model switches are serialized; validation happens **before** stopping the current process, so a bad request cannot unload a working model.
- `_wait_health()` polls `/health` for up to 180 s after spawning. Startup includes loading a multi-GB GGUF, so this is expected to take tens of seconds.
- `atexit` plus a `finally` block stop the child process when the manager exits, including Ctrl+C.

## Static WebUI

`/` and `/index.html` are read from `webui/index.html` on every request. There is no build step and no frontend dependency. The JS derives its API base from the URL: if the page path starts with `/plamo`, all fetches are prefixed with `/plamo`; otherwise they are same-origin bare paths. This is what makes the same file work locally and behind the Funnel path prefix.

## Proxy behavior

`Handler._proxy()` forwards `/v1/*`, `/health`, `/props`, `/slots*`, and `/models` to port 8001, copying headers except hop-by-hop ones. Responses are streamed with `resp.read1(65536)` with a `flush()` after each chunk — `read()` would wait for a full buffer and break SSE token streaming. Upstream errors (including 404/400 bodies) are relayed unchanged. A dead client raises `ConnectionError`, which is swallowed for the proxy loop.

## Token gate

`GateHandler` sits in front of the same `Handler` routes:

1. `?token=<exact token>` → sets `plamo_session=<sha256(token)>; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000` and 302-redirects to the bare path. Storing the hash, not the token, keeps the cookie safe to log.
2. `Authorization: Bearer <exact token>` → accepted directly, for API clients.
3. `plamo_session` cookie matching the hash → accepted for 30 days.
4. Everything else → generic `404` JSON (`File Not Found`) with no server banner (`version_string()` returns `nginx`). Scanners, crawlers, and visitors learn nothing about the service.

The external `/plamo` prefix is stripped before delegating to `Handler`, so all internal routes stay simple. Tokens are generated with `secrets.token_urlsafe(24)` and persisted in `.plamo_access_token` (mode 0600 where supported).

## Port preflight

Windows allows a second `bind()` with `SO_REUSEADDR` in some cases, silently sending visitors to the wrong server. Before starting, the manager probes ports 8000 and 8445 with `/api/status`: any HTTP response (even an error) means the port is already serving and the manager exits with a clear message.

## Known performance bug (fixed — do not regress)

A dead client caused `ConnectionError` in `handle_one_request()`. Because the `handle()` loop retried, the same error repeated forever and the process burned ~123% of one core with 50 threads. `Handler.handle_one_request()` now sets `close_connection = True` on `ConnectionError`; idle CPU is 0% with ~10 threads. `GateHandler.handle_one_request()` similarly closes silently.
