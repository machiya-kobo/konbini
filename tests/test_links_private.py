"""The link checker never calls into the private network (the sweep's KONB-7): private and reserved addresses, private-looking
names and names that resolve to private addresses are not external links, and a fetch checks every hop, redirects included.
No network: names are resolved by a patched resolver and the 'remote' servers are on 127.0.0.1."""
import http.server, os, socket, sys, threading, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import links

# syntax: what counts as an external link
for private in ("http://172.17.0.5/x", "http://169.254.169.254/latest/meta-data", "http://127.1.2.3/", "http://10.1.2.3/", "http://192.168.1.1/",
                "http://100.64.0.1/", "http://printer.local/", "http://nas.lan/", "http://db.internal/", "http://a.b.localhost/",
                "http://[::1]/", "http://[fd00::1]/", "http://localhost/", "http://example.com:80@10.0.0.1/"):
    assert not links.is_external(private), private
for public in ("https://example.org/page", "https://93.184.216.34/x", "http://sub.example.co.uk/a?b=c"):
    assert links.is_external(public), public
assert links.extract("see https://example.org/a and http://172.17.0.5/b and http://db.internal/c .") == ["https://example.org/a"]

# resolution: every address must be public (a name that points inside is refused, IPv6 included)
real = socket.getaddrinfo
table = {}
def fake(host, port, *a, **k):
    if host in table:
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]
    return real(host, port, *a, **k)
socket.getaddrinfo = fake
table.update({"good.example": ["93.184.216.34"], "inside.example": ["10.0.0.5"], "mixed.example": ["93.184.216.34", "192.168.0.9"],
              "v6.example": ["::1"], "meta.example": ["169.254.169.254"], "v6ok.example": ["2606:2800:220:1:248:1893:25c8:1946"]})
links.check_public("https://good.example/x"); links.check_public("http://v6ok.example/")
for bad in ("https://inside.example/", "http://mixed.example/", "http://v6.example/", "http://meta.example/latest", "ftp://good.example/", "http:///x"):
    try:
        links.check_public(bad)
    except links.PrivateHost:
        pass
    else:
        raise AssertionError("not refused: " + bad)
socket.getaddrinfo = real

# a fetch: the first address and every redirect are checked; nothing is sent to a refused one
hits = {"a": [], "b": []}
def server(name, redirect_to=None):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_HEAD(self): self.do_GET()
        def do_GET(self):
            hits[name].append(self.path)
            if redirect_to:
                self.send_response(302); self.send_header("Location", redirect_to); self.send_header("Content-Length", "0"); self.end_headers()
            else:
                self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % srv.server_address[1]
b_url = server("b")
a_url = server("a", b_url + "/inside")
allowed = {a_url.rsplit(":", 1)[1]}                       # pretend only A's port is a public address
orig = links.check_public
def pretend(url):
    if str(urllib_port(url)) not in allowed:
        raise links.PrivateHost("private")
def urllib_port(url):
    import urllib.parse
    return urllib.parse.urlsplit(url).port
links.check_public = pretend
try:
    links.safe_request(a_url + "/start", "GET")
    raise AssertionError("a redirect into a private address was followed")
except links.PrivateHost:
    pass
assert hits["a"] == ["/start"] and hits["b"] == [], hits                      # A was asked once; B (the private one) never
assert links.Links.probe(links.Links.__new__(links.Links), b_url + "/direct") is None and hits["b"] == []   # a private first address: no request
assert links.Links.probe(links.Links.__new__(links.Links), a_url + "/start2") is None                       # a redirect into one: none
assert hits["b"] == [], hits
links.check_public = orig
print("private link tests: all passed")
