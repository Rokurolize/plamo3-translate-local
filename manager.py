#!/usr/bin/env python3
"""
PLaMo 3 Translate - local model manager.

Serves the translation WebUI (./webui), reverse-proxies /v1/* to a
user-supplied llama-server child process, and exposes a control API:

  GET  /api/status    -> {"running": bool, "model": "8b"|"2b"|"0.8b"|null, "pid": int|null, ...}
  POST /api/switch    {"model": "8b"|"2b"|"0.8b"}  -> stops the current server, loads the new model, waits for health
  POST /api/stop      -> stops the model server
  POST /api/restart   -> restarts the currently loaded model (default: 0.8b)

Everything else: static files from ./webui, /v1/* (and /health, /props, /slots*)
is proxied to llama-server. Requires only the Python standard library.

Launch (Windows):
  start-plamo.bat [0.8b|2b|8b] [port]      (ports: manager 8000, llama-server 8001 internally)
  python manager.py --model 0.8b --port 8000 --backend-port 8001

llama-server discovery (first match wins):
  --llama-server PATH, $env:PLAMO_LLAMA_SERVER, PATH lookup,
  a winget install under $env:LOCALAPPDATA\\Microsoft\\WinGet\\Packages\\ggml.llamacpp_*
"""
import argparse
import atexit
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLAMA_SERVER = None  # resolved in main(); see find_llama_server()
ALIAS = "plamo-3-translate"
CTX = 32768  # model's training limit (32,768 tokens)
TOKEN_FILE = HERE / ".plamo_access_token"
GATE_TOKEN = ""          # set in main(); URL token = session cookie derivation key
GATE_HOST = "0.0.0.0"    # public listener (Tailscale Funnel forwards here)
GATE_PORT = 0            # 0 = public listener disabled
GATE_PATH = "/plamo"     # external path prefix configured in Tailscale Funnel

def load_or_create_token(explicit=None):
    """Persistence: reuse the token across restarts; rotate by deleting TOKEN_FILE."""
    for value in (explicit, os.environ.get("PLAMO_GATE_TOKEN")):
        if value and value.strip():
            return value.strip()
    if TOKEN_FILE.exists():
        value = TOKEN_FILE.read_text(encoding="ascii").strip()
        if value:
            return value
    value = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(value, encoding="ascii")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return value

# size -> (folder, file)
_MODELS = {
    "8b":   ("plamo-3-translate-8b-GGUF",   "plamo-3-translate-8b-Q4_K_M.gguf"),
    "2b":   ("plamo-3-translate-2b-GGUF",   "plamo-3-translate-2b-Q4_K_M.gguf"),
    "0.8b": ("plamo-3-translate-0.8b-GGUF", "plamo-3-translate-0.8b-Q4_K_M.gguf"),
}
_ALIASES = {"8b": "8b", "8B": "8b", "2b": "2b", "2B": "2b",
            "0.8b": "0.8b", "0.8B": "0.8b", "08b": "0.8b", "08B": "0.8b"}

def norm_model(name):
    return _ALIASES.get(str(name).strip()) if name is not None else None


def find_llama_server(explicit=None):
    """Locate llama-server.exe without assuming a particular username/source."""
    for value in (explicit, os.environ.get("PLAMO_LLAMA_SERVER")):
        if value and Path(value).is_file():
            return Path(value)
    found = shutil.which("llama-server")
    if found:
        return Path(found)
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for candidate in sorted(packages.glob("ggml.llamacpp_*/llama-server.exe")):
        if candidate.is_file():
            return candidate
    return None


class Manager:
    def __init__(self, backend_port: int):
        self.backend_port = backend_port
        self.lock = threading.Lock()
        self.model = None
        self.proc = None
        self.last_model = "8b"

    # ---- state ------------------------------------------------------------
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def status(self) -> dict:
        running = self.is_running()
        return {
            "running": running,
            "model": self.model if running else None,
            "lastModel": self.last_model,
            "pid": self.proc.pid if running else None,
            "backendPort": self.backend_port,
            "alias": ALIAS,
        }

    # ---- lifecycle ----------------------------------------------------------
    def _stop_locked(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()            # TerminateProcess on Windows
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass

    def _spawn_locked(self, name: str):
        model_path = self._model_path(name)
        if LLAMA_SERVER is None or not Path(LLAMA_SERVER).is_file():
            raise RuntimeError("llama-server not found: pass --llama-server PATH, set "
                               "PLAMO_LLAMA_SERVER, put it on PATH, or install llama.cpp")
        self.proc = subprocess.Popen(
            [str(LLAMA_SERVER), "-m", str(model_path), "-c", str(CTX),
             "--port", str(self.backend_port), "--alias", ALIAS,
             "--jinja", "--no-prefill-assistant"],
            cwd=str(HERE),
        )
        self.model = name
        self.last_model = name

    def _wait_health(self, timeout: float = 180.0) -> bool:
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{self.backend_port}/health"
        while time.time() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.5)
        return False

    def _model_path(self, name: str) -> Path:
        folder, fname = _MODELS[name]
        return HERE / folder / fname

    def start_model(self, name: str) -> dict:
        canon = norm_model(name)
        if canon is None:
            raise ValueError(f"unknown model: {name!r} (expected 8b, 2b or 0.8b)")
        with self.lock:
            # validate first: a failed switch must not unload the currently running model
            if not self._model_path(canon).exists():
                raise RuntimeError(f"model file not found: {self._model_path(canon)}")
            if self.is_running() and self.model == canon:
                return {"switched": True, "already": True, **self.status()}
            self._stop_locked()
            self._spawn_locked(canon)
            if not self._wait_health():
                self._stop_locked()
                raise RuntimeError("llama-server did not become healthy in time")
            return {"switched": True, **self.status()}

    def stop(self) -> dict:
        with self.lock:
            self._stop_locked()
            return self.status()

    def shutdown(self):
        with self.lock:
            self._stop_locked()


MANAGER = None  # set in main()
BACKEND_PORT = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PLaMoManager/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the console readable; startup lines only

    def handle_one_request(self):
        try:
            return super().handle_one_request()
        except ConnectionError:
            # A dead client would raise the same error on every retry of the
            # handle() loop -> busy-spin. Mark the connection closed so the
            # thread exits.
            self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        try:
            return super().send_error(code, message, explain)
        except ConnectionError:
            self.close_connection = True

    # ---------- low-level helpers ------------------------------------------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, code, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _proxy(self, method):
        body = None
        if method in ("POST", "PUT", "PATCH"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            body = self.rfile.read(length) if length else None
        url = f"http://127.0.0.1:{BACKEND_PORT}{self.path}"
        req = urllib.request.Request(url, data=body, method=method)
        for key, value in self.headers.items():
            low = key.lower()
            if low in ("host", "content-length", "connection", "keep-alive", "transfer-encoding"):
                continue
            req.add_header(key, value)
        req.add_header("Host", f"127.0.0.1:{BACKEND_PORT}")
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            status, src_headers = resp.status, resp.headers
        except urllib.error.HTTPError as e:
            resp, status, src_headers = e, e.code, e.headers  # relay upstream errors as-is
        except Exception as e:
            self._send_json({"error": {"message": f"model server is not reachable ({e}). "
                                                "It may be stopped - use the Start button or POST /api/switch."}}, 503)
            return

        content_type = src_headers.get("Content-Type", "application/octet-stream")
        length = src_headers.get("Content-Length")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        if length is not None:
            self.send_header("Content-Length", length)
            self.end_headers()
        else:
            self.send_header("Connection", "close")
            self.end_headers()
        try:
            while True:
                try:
                    chunk = resp.read1(65536)  # returns as soon as >=1 byte is available (SSE-safe)
                except AttributeError:
                    chunk = resp.read(8192)
                except Exception:
                    break
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except ConnectionError:
            pass  # client went away (e.g. closed the page or a stopped SSE stream)

    # ---------- routes -------------------------------------------------------
    _STATIC = {"/": ("webui/index.html", "text/html; charset=utf-8"),
               "/index.html": ("webui/index.html", "text/html; charset=utf-8")}
    _PROXY_GET_PREFIXES = ("/v1/", "/health", "/props", "/slots", "/models")
    _PROXY_POST_PREFIXES = ("/v1/", "/completion", "/slot_save", "/slot_restore", "/slot_erase")

    def do_GET(self):
        if self.path in self._STATIC:
            rel, ctype = self._STATIC[self.path]
            try:
                data = (HERE / rel).read_bytes()
            except OSError:
                self._send_json({"error": {"message": "not found"}}, 404)
                return
            self._send_bytes(data, 200, ctype)
            return
        if self.path == "/favicon.ico":
            self.send_response(204); self.send_header("Content-Length", "0"); self.end_headers(); return
        if self.path == "/api/status":
            self._send_json(MANAGER.status()); return
        if any(self.path.startswith(p) for p in self._PROXY_GET_PREFIXES):
            self._proxy("GET"); return
        self._send_json({"error": {"message": "not found"}}, 404)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/switch":
            obj = self._read_json()
            if obj is None:
                self._send_json({"error": {"message": "invalid JSON body"}}, 400); return
            try:
                self._send_json(MANAGER.start_model(obj.get("model")))
            except ValueError as e:
                self._send_json({"error": {"message": str(e)}}, 400)
            except RuntimeError as e:
                self._send_json({"error": {"message": str(e)}}, 500)
            return
        if self.path == "/api/restart":
            cur = MANAGER.last_model or "0.8b"
            try:
                self._send_json(MANAGER.start_model(cur))
            except RuntimeError as e:
                self._send_json({"error": {"message": str(e)}}, 500)
            return
        if self.path == "/api/stop":
            self._send_json(MANAGER.stop()); return
        if any(self.path.startswith(p) for p in self._PROXY_POST_PREFIXES):
            self._proxy("POST"); return
        self._send_json({"error": {"message": "not found"}}, 404)


_NOT_FOUND_BODY = b'{"error":{"message":"File Not Found","type":"not_found_error","code":404}}'


class GateHandler(Handler):
    """Public listener. A valid ?token=... sets an HttpOnly cookie and redirects
    to the bare path; subsequent requests use the cookie. Everyone else (port
    scanners, crawlers, random visitors) gets an ordinary-looking 404 for every
    path, with no hint that this is a translation service or that a token exists.
    An Authorization: Bearer <token> header is accepted for non-browser clients.
    """
    def version_string(self):
        return "nginx"  # don't advertise the manager on the public listener

    def send_response(self, code, message=None):
        super().send_response(code, message)
        cookie = getattr(self, "_set_cookie", None)
        if cookie:
            self.send_header("Set-Cookie", cookie)
            self._set_cookie = None

    def _deny(self):
        self.send_response(404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(_NOT_FOUND_BODY)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(_NOT_FOUND_BODY)

    def _authorized(self):
        parsed = urllib.parse.urlsplit(self.path)
        token_in_url = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
        auth = self.headers.get("Authorization", "")
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        cookie_token = ""
        try:
            jar = SimpleCookie()
            jar.load(self.headers.get("Cookie", ""))
            morsel = jar.get("plamo_session")
            if morsel:
                cookie_token = morsel.value
        except Exception:
            pass
        expected = hashlib.sha256(GATE_TOKEN.encode("utf-8")).hexdigest()
        if secrets.compare_digest(token_in_url, GATE_TOKEN):
            self._set_cookie = (f"plamo_session={expected}; Path=/; HttpOnly; Secure; "
                                "SameSite=Lax; Max-Age=2592000")
            if self.command == "GET":
                self.send_response(302)
                self.send_header("Location", GATE_PATH + (parsed.path if parsed.path != "/" else "/"))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return "redirect"
            return True
        if secrets.compare_digest(bearer, GATE_TOKEN):
            return True
        return secrets.compare_digest(cookie_token, expected)

    def _check(self, method):
        result = self._authorized()
        if result == "redirect":
            return
        if result is True:
            # Tailscale Funnel attaches this service at /plamo/; the base app only knows bare paths.
            if self.path.startswith("/plamo"):
                self.path = self.path[len("/plamo"):] or "/"
            return method()
        self._deny()

    def do_GET(self):     self._check(lambda: super(GateHandler, self).do_GET())
    def do_POST(self):    self._check(lambda: super(GateHandler, self).do_POST())
    def do_HEAD(self):    self._check(lambda: super(GateHandler, self).do_HEAD())
    def do_OPTIONS(self): self._check(lambda: super(GateHandler, self).do_OPTIONS())

    def handle_one_request(self):
        try:
            return super().handle_one_request()
        except ConnectionError:
            pass


def main():
    global MANAGER, BACKEND_PORT, GATE_TOKEN, GATE_HOST, GATE_PORT, GATE_PATH, LLAMA_SERVER
    ap = argparse.ArgumentParser(description="PLaMo 3 Translate local model manager")
    ap.add_argument("--model", default="0.8b", help="initial model to load: 0.8b (default) | 2b | 8b")
    ap.add_argument("--port", type=int, default=8000, help="local UI/API port (default 8000, no token needed)")
    ap.add_argument("--backend-port", type=int, default=8001, help="internal llama-server port (default 8001)")
    ap.add_argument("--public-port", type=int, default=8445, help="local token-gated port for Tailscale Funnel to proxy to (default 8445; Funnel itself may need this port free on the tailnet IP)")
    ap.add_argument("--public-host", default="0.0.0.0", help="bind address of the public listener (default 0.0.0.0)")
    ap.add_argument("--token", default=None, help="override the access token (otherwise read/generated in .plamo_access_token)")
    ap.add_argument("--public-path", default="/plamo", help="external path prefix used by Tailscale Funnel for the public listener")
    ap.add_argument("--llama-server", default=None,
                    help="path to llama-server(.exe); overrides PLAMO_LLAMA_SERVER and PATH lookup")
    args = ap.parse_args()

    LLAMA_SERVER = find_llama_server(args.llama_server)
    if LLAMA_SERVER:
        print(f"[manager] llama-server: {LLAMA_SERVER}")
    else:
        print("[manager] warning: llama-server not found; the UI will still load, but "
              "translation needs it (--llama-server / PLAMO_LLAMA_SERVER / PATH / winget install ggml.llamacpp).",
              file=sys.stderr)

    # Refuse to start if either port is already serving HTTP (Windows can allow a
    # second bind via SO_REUSEADDR, silently sending visitors to the wrong server).
    ports_to_check = [args.port] + ([args.public_port] if args.public_port and args.public_port != args.port else [])
    for port in ports_to_check:
        occupied = False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1):
                occupied = True
        except urllib.error.HTTPError:
            occupied = True  # any HTTP response means the port is already serving
        except urllib.error.URLError:
            pass             # nothing listening — good
        if occupied:
            raise SystemExit(
                f"[manager] port {port} is already serving HTTP. Stop that process first "
                f"(check: netstat -ano | findstr :{port}), then start the manager again."
            )

    GATE_TOKEN = load_or_create_token(args.token)
    GATE_HOST, GATE_PORT, GATE_PATH = args.public_host, args.public_port, args.public_path
    BACKEND_PORT = args.backend_port
    MANAGER = Manager(BACKEND_PORT)
    atexit.register(MANAGER.shutdown)

    try:
        first = MANAGER.start_model(args.model)
        print(f"[manager] PLaMo 3 Translate {first.get('model')} loaded on 127.0.0.1:{BACKEND_PORT} (pid {first.get('pid')})")
    except Exception as e:
        print(f"[manager] warning: could not load initial model: {e}", file=sys.stderr)
        print("[manager] UI is still served; use Start in the UI or POST /api/switch after fixing the model file.", file=sys.stderr)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    public_server = None
    if GATE_PORT:
        public_server = ThreadingHTTPServer((GATE_HOST, GATE_PORT), GateHandler)
        threading.Thread(target=public_server.serve_forever, name="public-gate", daemon=True).start()
    print(f"[manager] Local WebUI: http://127.0.0.1:{args.port}/  (no token needed)")
    print(f"[manager] API:         http://127.0.0.1:{args.port}/v1/ ...  (ctrl+c to quit; stopping the manager also stops the model server)")
    if public_server:
        print(f"[manager] Public gate: http://<host>:{GATE_PORT}/?token={GATE_TOKEN}")
        print(f"[manager]   (Tailscale Funnel: https://<your-host>.ts.net:<funnel-port>{GATE_PATH}/?token={GATE_TOKEN})")
        print(f"[manager]   token file: {TOKEN_FILE}  (delete it and restart to rotate)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[manager] shutting down model server ...")
    finally:
        if public_server:
            public_server.shutdown()
        MANAGER.shutdown()


if __name__ == "__main__":
    main()
