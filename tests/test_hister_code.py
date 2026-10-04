"""The code-import service stores repositories, READMEs, issues and releases in Hister with metadata.source "code"; only
Shiori's Code area shows them. Every query Konbini sends to Hister leaves them out (" -metadata.source:code"), and a code
document that comes back anyway (a fake Hister that ignores the exclusion) is never a page "I've read", a saved copy, a count
or something to delete. A fake Hister records the queries."""
import datetime, http.server, json, os, sys, threading, urllib.parse

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import hister  # noqa: E402

PAGE = {"url": "https://example.org/konbini-board", "title": "Konbini board notes", "label": "reading", "added": 1790000000,
        "metadata": {"source": "feed"}}
CODE = {"url": "https://forge.example/owner/konbini", "title": "owner/konbini: Konbini board", "label": "code",
        "added": 1790000001, "metadata": {"source": "code", "repo": "owner/konbini"}}
queries, deletes = [], []


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q", [""])[0]
        queries.append(q)
        docs = [PAGE, CODE]                      # ignores the exclusion on purpose: the client must still drop the code document
        if q.startswith("url:"):
            docs = [d for d in docs if d["url"] in q]
        self.reply({"documents": docs, "total": len(docs)})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        deletes.append(body.get("query"))
        self.reply({"deleted": 0})


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
h = hister.Hister("http://127.0.0.1:%d" % srv.server_address[1], "https://hister.example")
NO = " -metadata.source:code"

# pages I've read: the code document is dropped even though the fake returned it, and the query excludes it
pages, _ = h.reading("Konbini board", topics=["board"])
assert [p["url"] for p in pages] == [PAGE["url"]], pages
assert queries and all(q.endswith(NO) for q in queries), queries
assert any("-label:vault" in q for q in queries)                                    # the vault exclusion is still there
# a saved copy: a URL that is a code document is not found; a page is
del queries[:]
assert h.find(CODE["url"]) is None and h.find(PAGE["url"])["title"] == PAGE["title"]
assert queries and all(q.endswith(NO) for q in queries), queries
# saved pages in a window: the count doesn't include the code document, and the link into Hister carries the exclusion
del queries[:]
saved = h.saved_between(datetime.date(2026, 9, 1), datetime.date(2026, 10, 1))
assert saved["total"] == 1 and [k for k, _ in saved["top"]] == ["reading"], saved
assert queries[0].endswith(NO) and urllib.parse.quote(NO.strip()) in saved["search"], (queries, saved["search"])
# deleting a page by URL can't reach a code document
h.delete(PAGE["url"])
assert deletes and all(d.endswith(NO) for d in deletes), deletes
print("hister code tests: all passed")
