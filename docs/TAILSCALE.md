# Remote access with Tailscale Funnel

Goal: use the WebUI/API from a phone or another computer via a public Tailscale Funnel URL, while revealing nothing to scanners and requiring a token for every request.

All values below are placeholders. **Never commit real hostnames or tokens.**

## Layout

```
https://<your-tailnet-name>.ts.net:10000/plamo/?token=<token>
        |                          |       |
        |                          |       +-- one-time gate token -> 30-day cookie
        |                          +---------- external path prefix
        +------------------------------------- Funnel port allowed by the tailnet ACL
```

Funnel forwards `/plamo/*` to `http://127.0.0.1:8445/` on the machine running the manager. The manager's `GateHandler` strips `/plamo` and validates the token before serving any route.

## Steps

1. On the machine (or WSL distro) that shares the LAN/loopback with the manager, configure Tailscale serve for path-based routing. Example shape, adapted to your setup:

   ```bash
   tailscale serve --bg --https=10000 /plamo http://127.0.0.1:8445/
   tailscale funnel --bg 10000
   tailscale serve status
   ```

   If you use a `tailscale serve` config file, the relevant entry is a handler on port 10000 with path `/plamo` → `http://127.0.0.1:8445`. Existing services on the same port can coexist when routed by path.

2. Start the manager with the gated listener enabled (default). It prints:

   ```
   [manager] Public gate: http://<host>:8445/?token=<token>
   ```

   The token is in `.plamo_access_token` in the repo root; treat it as a password.

3. Open the public URL once with `?token=...` in the browser. You should be redirected to `/plamo/` with a clean URL and a session cookie that lasts 30 days.

4. For API clients on the public URL, send the token on every request:

   ```bash
   curl -H "Authorization: Bearer <token>" \
        https://<your-tailnet-name>.ts.net:10000/plamo/v1/chat/completions ...
   ```

## Verify the gate

```bash
curl -o NUL -w "%{http_code}" https://<host>:10000/plamo/                       # expect 404
curl -o NUL -w "%{http_code}" "https://<host>:10000/plamo/?token=<token>"      # expect 302
curl -o NUL -w "%{http_code}" -H "Authorization: Bearer <token>" ...           # expect 200
```

A 404 for the no-token case is intentional: the service must look like nothing at all to port scanners and crawlers.

## Port notes

- Tailnet ACLs here only allow **443, 8443, and 10000**. Port **8444** was tried and produced `ERR_CONNECTION_TIMED_OUT` — do not use it.
- **8443** is already used by a different local service (WikiJump on WSL), so the gated listener uses **8445** internally and Funnel exposes it as path `/plamo` on **10000**.
- The manager binds local port 8000 to `127.0.0.1` only. The gated listener binds `0.0.0.0` by default so the Funnel/Tailscale process can reach it; it is protected by the token gate. Set `--public-host` if you need a narrower bind.

## Rotating the token

If the URL was shared with someone who should lose access, or the token leaked:

```powershell
Remove-Item .\.plamo_access_token
# then restart the manager (or the 'PLaMo 3 Translate' scheduled task)
```

A new token is generated at startup. Update your bookmarks and clients; old cookies stop working. Because the cookie stores only a SHA-256 hash of the token, rotation invalidates every existing session at once.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `ERR_CONNECTION_TIMED_OUT` on the Funnel URL | Port not allowed by ACL, or Funnel not enabled for that port |
| 404 even with the correct token | External path differs from `--public-path` (default `/plamo`), or Funnel is forwarding to the wrong port |
| 404 in browser after redirect but API works with bearer | Cookie `Secure` attribute requires HTTPS; use the Funnel URL, not plain HTTP |
| Token appears in browser history | Expected with `?token=`; rotate it if the history is shared, then bookmark the clean URL |
