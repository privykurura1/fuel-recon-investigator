"""Demo web page: python -m agent.web   then open http://localhost:5050

Streams the investigation live (Server-Sent Events), shows findings as evidence cards,
what Meterless H-MEM recalled and stored, and the Nightshift receipts proving which
NVIDIA Nemotron model answered. Managers can upload their own station records (CSV)
and investigate them. Standard library only, plus psycopg for loading records.
"""
import io
import json
import os
import queue
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import loader, memory
from .investigator import investigate

PORT = int(os.environ.get("WEB_PORT", "5050"))
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web.html")
RUN_LOCK = threading.Lock()
MAX_UPLOAD = 40_000_000   # bytes of CSV text per upload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True   # the browser closed the tab mid-request; nothing to do

    def _json(self, obj, code=200):
        data = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            with open(PAGE, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif url.path == "/api/memory":
            try:
                self._json({"memories": memory.list_all(), "stats": memory.stats()})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
        elif url.path == "/api/ledger":
            try:
                self._json({"ledger": memory.ledger(30)})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
        elif url.path == "/api/station":
            self._json({"station": loader.current_station(),
                        "files": {k: {"required": r, "optional": o, "about": d,
                                      "optional_file": k in loader.OPTIONAL_FILES}
                                  for k, (r, o, d) in loader.FILES.items()}})
        elif url.path == "/templates.zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for name in sorted(os.listdir(loader.TEMPLATES)):
                    if name.endswith(".csv"):
                        z.write(os.path.join(loader.TEMPLATES, name), f"station-templates/{name}")
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="station-templates.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif url.path == "/api/run":
            question = (parse_qs(url.query).get("q") or [""])[0].strip()
            self._stream(question)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            return self._json({"errors": [f"Upload too large (limit {MAX_UPLOAD // 1_000_000} MB)."]}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"errors": ["Request was not valid JSON."]}, 400)
        if path == "/api/detect":
            return self._json(loader.detect(str(body.get("name") or ""), str(body.get("header") or "")[:4000]))
        if path in ("/api/upload", "/api/restore-sample"):
            return self._load(body, sample=path == "/api/restore-sample")
        if path != "/api/feedback":
            return self.send_error(404)
        if body.get("kind") not in ("helpful", "not_helpful", "wrong"):
            return self._json({"error": "kind must be helpful, not_helpful or wrong"}, 400)
        try:
            self._json(memory.feedback(str(body.get("id")), body["kind"]))
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def _load(self, body, sample):
        # Never swap the data underneath a running investigation.
        if not RUN_LOCK.acquire(blocking=False):
            return self._json({"errors": ["An investigation is running. Load your records when it finishes."]}, 409)
        try:
            if sample:
                info = loader.load(loader.sample_files(), loader.SAMPLE_NAME)
            else:
                files = {k: v for k, v in (body.get("files") or {}).items() if k in loader.FILES and v}
                name = str(body.get("name") or "").strip()[:80]
                if not name:
                    return self._json({"errors": ["Please type your station's name."]}, 400)
                info = loader.load(files, name)
            self._json({"ok": True, "station": info})
        except loader.LoadError as exc:
            self._json({"errors": exc.errors}, 400)
        except Exception as exc:   # database unreachable, psycopg missing, ...
            self._json({"errors": [f"Could not write to the station database: {type(exc).__name__}: {exc}"]}, 500)
        finally:
            RUN_LOCK.release()

    def _send_event(self, kind, data):
        payload = json.dumps({"kind": kind, "data": data}, default=str)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _stream(self, question):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not question:
            self._send_event("error", "Please type a question.")
            return self._send_event("end", {})
        if not RUN_LOCK.acquire(blocking=False):
            self._send_event("error", "An investigation is already running. Wait for it to finish.")
            return self._send_event("end", {})
        events = queue.Queue()

        def work():
            try:
                result, trace = investigate(question, on_event=lambda k, d: events.put((k, d)))
                models = sorted({r.get("routed_model") for r in trace["receipts"] if r.get("routed_model")})
                events.put(("done", {
                    "result": result,
                    "models": models,
                    "receipts": [r.get("receipt_id") for r in trace["receipts"] if r.get("receipt_id")],
                    "steps": len(trace["steps"]),
                    "trace": trace.get("saved_to"),
                }))
            except Exception as exc:
                events.put(("error", f"{type(exc).__name__}: {exc}"))
            finally:
                events.put(("end", {}))

        threading.Thread(target=work, daemon=True).start()
        try:
            while True:
                try:
                    kind, data = events.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")   # Nemotron may think for a while
                    self.wfile.flush()
                    continue
                self._send_event(kind, data)
                if kind == "end":
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass   # browser closed; the investigation still finishes and saves its trace
        finally:
            RUN_LOCK.release()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Fuel Reconciliation Investigator running at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
