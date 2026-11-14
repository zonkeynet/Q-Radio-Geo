"""Polite fetching for the webcam catalogue collectors (scripts/collect_*.py).

robots.txt is read first and honoured; requests are sequential, at least one second
apart per host, and carry a descriptive User-Agent. No key, login, challenge or
geo-block is bypassed: a refusal is recorded and the source skipped. Camera images
and streams are only ever sampled (64 KiB at most, never kept) for one check per
provider, in the shapes build_webcams.py already reads (--snapshot-checks, --health).
Standard library only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import re
from urllib.parse import unquote, urljoin, urlsplit

USER_AGENT = "Q-Globe webcam catalogue collector/1.0 (+https://globe.qp1ng.com)"
SAMPLE_BYTES = 65536


class Refused(Exception):
    """robots.txt disallows the URL, or the host refused or blocked the request."""


class Robots:
    """robots.txt per RFC 9309: the group for our product token (else '*'), '*' and '$' in patterns,
    the longest matching rule wins and Allow wins a tie. (urllib.robotparser ignores wildcards.)"""
    TOKEN = "q-globe"

    def __init__(self, text):
        groups, agents, rules, last = [], [], [], None
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if last == "rule":
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
                last = "agent"
            elif key in ("allow", "disallow"):
                if agents:
                    rules.append((key == "allow", value))
                last = "rule"
        if agents:
            groups.append((agents, rules))
        mine = [r for a, rs in groups if any(x != "*" and x and x in self.TOKEN for x in a) for r in rs]
        self.rules = mine if any(any(x != "*" and x and x in self.TOKEN for x in a) for a, _ in groups) else \
            [r for a, rs in groups if "*" in a for r in rs]

    @staticmethod
    def _pattern(path):
        anchored = path.endswith("$")
        body = path[:-1] if anchored else path
        return re.compile("".join(".*" if c == "*" else re.escape(c) for c in body) + ("$" if anchored else ""))

    def allows(self, url):
        u = urlsplit(url)
        target = unquote(u.path or "/") + (("?" + u.query) if u.query else "")
        if target == "/robots.txt":
            return True
        best = None  # (length, allow)
        for allow, path in self.rules:
            if not path:
                continue
            if self._pattern(unquote(path)).match(target):
                key = (len(path), allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, log, check=None):
        self.log, self.check = log, check

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https" and urlsplit(req.full_url).scheme == "https":
            raise Refused(f"redirect away from HTTPS: {newurl}")
        # A redirect to another URL is a new request: its own host's robots.txt applies first.
        if self.check and urlsplit(newurl).path != "/robots.txt" and not self.check(newurl):
            raise Refused(f"robots.txt disallows the redirect target {newurl}")
        self.log.append({"from_url": req.full_url, "to_url": newurl, "http_status": code})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PoliteClient:
    def __init__(self, delay=1.0, timeout=40):
        self.delay, self.timeout = max(1.0, delay), timeout
        self.last = {}      # host -> monotonic time of the last request
        self.robots = {}    # scheme://host -> RobotFileParser or "allow"/"deny"
        self.log = []       # every request: url, status, bytes, time (for the collector's receipt)

    def _wait(self, host):
        gap = time.monotonic() - self.last.get(host, -1e9)
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self.last[host] = time.monotonic()

    def _open(self, url, max_bytes, headers=None):
        host = urlsplit(url).hostname
        self._wait(host)
        redirects = []
        check = None if urlsplit(url).path == "/robots.txt" else self.allowed
        opener = urllib.request.build_opener(_Redirects(redirects, check))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        started = now()
        try:
            with opener.open(req, timeout=self.timeout) as r:
                body = r.read(max_bytes + 1)
                status, final, head = r.status, r.geturl(), dict(r.headers.items())
        except urllib.error.HTTPError as e:
            body, status, final, head = e.read(4096), e.code, url, dict(e.headers.items()) if e.headers else {}
        self.log.append({"url": url, "status": status, "bytes": len(body[:max_bytes]), "started_at": started})
        return {"url": url, "final_url": final, "status": status, "headers": head, "body": body[:max_bytes],
                "truncated": len(body) > max_bytes, "redirects": redirects, "started_at": started, "observed_at": now()}

    def allowed(self, url):
        base = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if base not in self.robots:
            try:
                r = self._open(base + "/robots.txt", 512 * 1024)
                if r["status"] >= 500:
                    self.robots[base] = "deny"     # RFC 9309: unreachable robots.txt means no crawling
                elif r["status"] >= 400:
                    self.robots[base] = "allow"    # no robots.txt
                else:
                    self.robots[base] = Robots(r["body"].decode("utf-8", "replace"))
            except (OSError, urllib.error.URLError, Refused):
                self.robots[base] = "deny"
        rule = self.robots[base]
        return rule == "allow" or (rule != "deny" and rule.allows(url))

    def get(self, url, *, max_bytes=50 * 1024 * 1024, accept=None):
        """One camera-list request. Raises Refused when robots.txt disallows it or the host refuses."""
        if urlsplit(url).scheme != "https":
            raise Refused(f"not HTTPS: {url}")
        if not self.allowed(url):
            raise Refused(f"robots.txt disallows {url}")
        r = self._open(url, max_bytes, {"Accept": accept} if accept else None)
        if r["status"] in (401, 403, 407, 429, 451) or r["status"] >= 500:
            raise Refused(f"HTTP {r['status']} for {url}")
        if r["truncated"]:
            raise Refused(f"response over {max_bytes} bytes: {url}")
        return r

    def get_json(self, url, **kw):
        r = self.get(url, accept="application/json", **kw)
        return json.loads(r["body"].decode("utf-8-sig")), r

    # ---------- one sample per new provider, nothing kept ----------
    def check_image(self, url, provider, record_id, hosts):
        """A --snapshot-checks event for one image (first 64 KiB, signature only)."""
        event = {"provider": provider, "record_id": record_id, "url": url, "approved_media_hosts": sorted(hosts),
                 "started_at": now(), "freshness_evaluated": False, "live_evaluated": False}
        try:
            if not self.allowed(url):
                return {**event, "checked_at": now(), "http_status": None, "bytes_read": 0, "signature": None,
                        "redirects": [], "status": "inconclusive", "inconclusive_reason": "robots.txt disallows the image"}
            r = self._open(url, SAMPLE_BYTES, {"Range": f"bytes=0-{SAMPLE_BYTES - 1}"})
        except (OSError, urllib.error.URLError, Refused) as e:
            return {**event, "checked_at": now(), "http_status": None, "bytes_read": 0, "signature": None, "redirects": [],
                    "status": "inconclusive", "inconclusive_reason": ("timeout: " if "timed out" in str(e) else "") + str(e)[:200]}
        body = r["body"]
        signature = "JPEG" if body[:3] == b"\xff\xd8\xff" else "PNG" if body[:8] == b"\x89PNG\r\n\x1a\n" else None
        return {**event, "checked_at": r["observed_at"], "http_status": r["status"],
                "content_type": r["headers"].get("Content-Type"), "bytes_read": len(body), "signature": signature,
                "jpeg_signature": signature == "JPEG", "png_signature": signature == "PNG",
                "cors": {k.lower(): v for k, v in r["headers"].items() if k.lower() == "access-control-allow-origin"},
                "redirects": r["redirects"][:2], "final_url": r["final_url"],
                "status": "image_signature_confirmed" if signature else "inconclusive",
                "inconclusive_reason": None if signature else "no JPEG/PNG signature in the sampled bytes"}

    def check_hls(self, url, provider):
        """A --health event for one manifest (first 64 KiB): reachability and #EXTM3U only, never 'live'."""
        event = {"provider": provider, "url": url, "live_verified": False}
        try:
            if not self.allowed(url):
                return {**event, "checked_at": now(), "status": "network_unverified", "error": "robots.txt disallows the manifest"}
            r = self._open(url, SAMPLE_BYTES)
        except (OSError, urllib.error.URLError, Refused) as e:
            return {**event, "checked_at": now(), "status": "network_unverified", "error": str(e)[:200]}
        valid = r["body"].lstrip().startswith(b"#EXTM3U")
        return {**event, "checked_at": r["observed_at"], "http_status": r["status"], "manifest_valid": valid,
                "content_type": r["headers"].get("Content-Type"), "bytes_sampled": len(r["body"])}


def save_raw(folder, name, response):
    """Keep a list response and its receipt (URL, time, status, SHA-256) for provenance."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    body = response["body"]
    (folder / name).write_bytes(body)
    receipt = {"file": name, "url": response["url"], "final_url": response["final_url"], "status": response["status"],
               "observed_at": response["observed_at"], "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
               "content_type": response["headers"].get("Content-Type"), "user_agent": USER_AGENT}
    (folder / (name + ".receipt.json")).write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    return receipt


def write_catalog(path, sources, items, generated_at=None, supersedes=()):
    """A normalized extra catalogue in the shape build_webcams.py --extra-catalog reads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "generated_at": generated_at or now(), "sources": [{"id": s} for s in sources], "items": items}
    if supersedes:
        doc["supersedes"] = sorted(supersedes)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def absolute(base, href):
    return urljoin(base, href)
