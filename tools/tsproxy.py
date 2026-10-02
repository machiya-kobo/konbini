"""Test stand-in for tailscale serve: forwards to the app and adds the identity header."""
import http.client, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
LISTEN, UPSTREAM = int(sys.argv[1]), int(sys.argv[2])
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_ANY(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")}
        headers["Tailscale-User-Login"] = "test@test"
        headers["Host"] = "127.0.0.1:%d" % LISTEN
        try:
            c = http.client.HTTPConnection("127.0.0.1", UPSTREAM, timeout=30)
            c.request(self.command, self.path, body=body, headers=headers)
            r = c.getresponse()
        except OSError:
            data = b"upstream down\n"
            self.send_response(502); self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self.send_response(r.status)
        streaming = r.getheader("Content-Length") is None
        for k, v in r.getheaders():
            if k.lower() not in ("connection", "transfer-encoding"):
                self.send_header(k, v)
        if streaming: self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                chunk = r.read(4096)
                if not chunk: break
                self.wfile.write(chunk); self.wfile.flush()
        except OSError:
            pass
        if streaming: self.close_connection = True
    do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = do_ANY
ThreadingHTTPServer(("127.0.0.1", LISTEN), H).serve_forever()
