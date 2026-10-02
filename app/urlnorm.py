#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Micheal Waltz and Machiya contributors
"""urlnorm.py - the one URL normalisation rule shared by Niwa and Konbini (their copies are identical).

The keys of a cold-archive map are norm(url), so a link written in a note is matched
to its snapshot. The rule:

  1. scheme http -> https; scheme + host lowercased; leading "www." dropped; :80/:443 dropped
  2. path kept as written (case and percent-encoding untouched), ONE trailing "/" removed,
     empty path -> "/"
  3. query: tracking parameters dropped (utm_*, fbclid, gclid, dclid, msclkid, mc_cid, mc_eid,
     igshid, _hsenc, _hsmi, ref_src); the rest keep their order and exact text; empty -> no "?"
  4. fragment dropped, UNLESS it is app state: starts with "!" or "#", or contains "=" or "/"
     (a single-page app keeping its whole state in "##@...")

Stdlib only. Run `python3 urlnorm.py` to execute the self-tests.
"""
from urllib.parse import urlsplit

__all__ = ["norm"]

TRACKING = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "_hsenc", "_hsmi", "ref_src"}


def _keep_param(pair: str) -> bool:
    name = pair.split("=", 1)[0].lower()
    return not (name.startswith("utm_") or name in TRACKING)


def _keep_fragment(frag: str) -> bool:
    return frag.startswith(("!", "#")) or "=" in frag or "/" in frag


def norm(url: str) -> str:
    """Normalise URL for matching; returns the input stripped if it is not an http(s) URL."""
    url = url.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.netloc:
        return url
    netloc = parts.netloc
    userinfo = ""
    if "@" in netloc:
        userinfo, netloc = netloc.rsplit("@", 1)
        userinfo += "@"
    host, port = netloc, ""
    if netloc.startswith("["):                       # IPv6 literal
        end = netloc.find("]")
        host, port = netloc[: end + 1], netloc[end + 2 :] if netloc[end + 1 : end + 2] == ":" else ""
    elif ":" in netloc:
        host, port = netloc.rsplit(":", 1)
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if port in ("80", "443", ""):
        port = ""
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    if path in ("", "/"):
        path = "/"
    query = "&".join(p for p in parts.query.split("&") if p and _keep_param(p))
    frag = parts.fragment if _keep_fragment(parts.fragment) else ""
    out = f"https://{userinfo}{host}{':' + port if port else ''}{path}"
    if query:
        out += "?" + query
    if frag:
        out += "#" + frag
    return out


def _selftest() -> None:
    cases = [
        ("http://www.Example.com/", "https://example.com/"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:443/a/", "https://example.com/a"),
        ("http://example.com:8080/a", "https://example.com:8080/a"),
        ("https://Example.com/Path/Case%2Fkept/", "https://example.com/Path/Case%2Fkept"),
        ("https://example.com/a?utm_source=x&id=3&fbclid=y", "https://example.com/a?id=3"),
        ("https://example.com/a?UTM_Medium=x", "https://example.com/a"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?b=2&a=1"),
        ("https://example.com/a#section-2", "https://example.com/a"),
        ("https://example.com/app#!/route", "https://example.com/app#!/route"),
        ("https://example.com/app#/route", "https://example.com/app#/route"),
        ("http://www.app.example/##@_k=%23ff", "https://app.example/##@_k=%23ff"),
        ("https://example.com/a?x=1#k=v", "https://example.com/a?x=1#k=v"),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("gopher://example.com/1/", "gopher://example.com/1/"),
        ("https://[2001:db8::1]:443/x/", "https://[2001:db8::1]/x"),
        ("https://www2.example.com/", "https://www2.example.com/"),
    ]
    bad = [(i, norm(i), e) for i, e in cases if norm(i) != e]
    for i, got, exp in bad:
        print(f"FAIL {i!r}: got {got!r}, want {exp!r}")
    assert norm(norm(cases[5][0])) == norm(cases[5][0]), "not idempotent"
    print(f"{len(cases) - len(bad)}/{len(cases)} ok")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    _selftest()
