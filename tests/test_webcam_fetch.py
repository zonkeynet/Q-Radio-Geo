"""Collector etiquette (scripts/webcam_fetch.py) and how the builder takes new inputs: no network here."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M
import webcam_fetch as F


class FakeClient(F.PoliteClient):
    """Serves canned responses instead of the network; records the order of requests."""

    def __init__(self, responses):
        super().__init__()
        self.responses, self.requested = responses, []

    def _open(self, url, max_bytes, headers=None):
        self.requested.append((url, dict(headers or {})))
        status, body = self.responses.get(url, (404, b""))
        return {"url": url, "final_url": url, "status": status, "headers": {"Content-Type": "x"}, "body": body[:max_bytes],
                "truncated": len(body) > max_bytes, "redirects": [], "started_at": F.now(), "observed_at": F.now()}


class EtiquetteTest(unittest.TestCase):
    def test_robots_is_read_first_and_honoured(self):
        c = FakeClient({"https://a.example.org/robots.txt": (200, b"User-agent: *\nDisallow: /private/\n"),
                        "https://a.example.org/cams.json": (200, b"[]")})
        self.assertEqual(c.get("https://a.example.org/cams.json")["body"], b"[]")
        self.assertEqual([u for u, _ in c.requested], ["https://a.example.org/robots.txt", "https://a.example.org/cams.json"])
        with self.assertRaises(F.Refused):
            c.get("https://a.example.org/private/cams.json")
        self.assertEqual(len(c.requested), 2, "a disallowed URL is never requested")

    def test_robots_wildcards_longest_match_and_our_own_group(self):
        r = F.Robots("User-agent: *\nDisallow: /api/\nAllow: /api/public\nDisallow: /explore/dataset/*/download\n"
                     "Disallow: /*.pdf$\n\nUser-agent: OtherBot\nDisallow: /\n")
        for url, allowed in (("https://x.org/explore/dataset/cams/download/", False), ("https://x.org/explore/dataset/cams/table/", True),
                             ("https://x.org/api/v1/cams", False), ("https://x.org/api/public/cams", True),
                             ("https://x.org/doc.pdf", False), ("https://x.org/doc.pdf?page=1", True), ("https://x.org/", True)):
            self.assertEqual(r.allows(url), allowed, url)
        own = F.Robots("User-agent: Q-Globe\nDisallow: /private\n\nUser-agent: *\nDisallow: /\n")
        self.assertTrue(own.allows("https://x.org/public")); self.assertFalse(own.allows("https://x.org/private/a"))
        self.assertTrue(F.Robots("User-agent: *\nDisallow: /\n").allows("https://x.org/robots.txt"))

    def test_missing_robots_allows_and_unreachable_robots_forbids(self):
        c = FakeClient({"https://b.example.org/robots.txt": (404, b""), "https://b.example.org/x": (200, b"ok")})
        self.assertEqual(c.get("https://b.example.org/x")["status"], 200)
        c = FakeClient({"https://c.example.org/robots.txt": (503, b""), "https://c.example.org/x": (200, b"ok")})
        with self.assertRaises(F.Refused):
            c.get("https://c.example.org/x")

    def test_refusals_and_plain_http_are_not_worked_around(self):
        c = FakeClient({"https://d.example.org/robots.txt": (404, b""), "https://d.example.org/x": (403, b"no")})
        with self.assertRaises(F.Refused):
            c.get("https://d.example.org/x")
        with self.assertRaises(F.Refused):
            c.get("http://d.example.org/x")

    def test_requests_to_one_host_are_spaced_and_identify_q_globe(self):
        self.assertIn("https://globe.qp1ng.com", F.USER_AGENT)
        c = F.PoliteClient(delay=0.2)  # never below one second
        self.assertEqual(c.delay, 1.0)
        sleeps = []
        with mock.patch.object(F.time, "sleep", sleeps.append), mock.patch.object(F.time, "monotonic", side_effect=[10.0, 10.0, 10.3, 10.3]):
            c._wait("e.example.org"); c._wait("e.example.org")
        self.assertEqual(len(sleeps), 1); self.assertAlmostEqual(sleeps[0], 0.7)

    def test_one_image_sample_reads_64_kib_and_keeps_only_the_signature(self):
        jpeg = b"\xff\xd8\xff\xe0" + b"0" * 100000
        c = FakeClient({"https://img.example.org/robots.txt": (404, b""), "https://img.example.org/c1.jpg": (206, jpeg)})
        event = c.check_image("https://img.example.org/c1.jpg", "p", "p:1", {"img.example.org"})
        self.assertEqual((event["signature"], event["bytes_read"], event["status"]), ("JPEG", 65536, "image_signature_confirmed"))
        self.assertEqual(c.requested[-1][1]["Range"], "bytes=0-65535")
        self.assertNotIn("body", event)
        hls = FakeClient({"https://v.example.org/robots.txt": (404, b""), "https://v.example.org/a.m3u8": (200, b"#EXTM3U\n")})
        event = hls.check_hls("https://v.example.org/a.m3u8", "p")
        self.assertTrue(event["manifest_valid"]); self.assertFalse(event["live_verified"])
        self.assertEqual(M.event_health(event)["status"], "playlist_ok", "a manifest check is never a live claim")


class RedirectTest(unittest.TestCase):
    def test_a_redirect_to_a_host_whose_robots_disallows_is_refused(self):
        handler = F._Redirects([], check=lambda url: not url.startswith("https://storage.example.net/"))
        req = __import__("urllib.request").request.Request("https://www.example.org/img/1.jpg")
        with self.assertRaises(F.Refused):
            handler.redirect_request(req, None, 302, "Found", {}, "https://storage.example.net/1.jpg")
        with self.assertRaises(F.Refused):
            handler.redirect_request(req, None, 302, "Found", {}, "http://www.example.org/1.jpg")


class NewInputsTest(unittest.TestCase):
    def item(self, provider, pid, page):
        return {"provider": provider, "provider_id": pid, "id": f"{provider}:{pid}", "name": pid, "lat": 46.2, "lng": 6.1,
                "country": "CH", "format": "official_page", "rights_status": "official_page_only", "official_page": page}

    def build(self, files):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for i, doc in enumerate(files):
                path = Path(folder) / f"in{i}.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                paths.append(path)
            return M.load_extra_catalogs(paths, "2026-11-14T00:00:00Z")

    def test_a_newer_collection_supersedes_a_provider_and_must_declare_it(self):
        old = {"sources": [{"id": "geneva_sitg"}], "items": [self.item("geneva_sitg", "1", "https://ge.ch/terinfomobilite/"),
                                                             self.item("geneva_sitg", "2", "https://ge.ch/terinfomobilite/")]}
        new = {"sources": [{"id": "geneva_sitg"}], "supersedes": ["geneva_sitg"],
               "items": [self.item("geneva_sitg", "1", "https://ge.ch/terinfomobilite/")]}
        items, _, provenance, rejected = self.build([old, new])
        self.assertEqual([x["id"] for x in items], ["geneva_sitg:1"])
        self.assertEqual([p.get("kind") for p in provenance], ["superseded_input", "normalized_extra_catalog"])
        self.assertEqual(rejected, [])
        with self.assertRaises(ValueError):
            self.build([old, {**new, "sources": [{"id": "osm_webcams"}], "items": []}])
        with self.assertRaises(ValueError):
            self.build([new, new])

    def test_items_of_a_held_source_are_refused(self):
        with mock.patch.dict(M.PROVIDER_POLICIES, {"held_x": {"status": "held", "held_reason": "key", "source": {"id": "held_x"}}}), \
                mock.patch.object(M, "EXTRA_CATALOG_PROVIDERS", M.EXTRA_CATALOG_PROVIDERS | {"held_x"}):
            with self.assertRaisesRegex(ValueError, "held"):
                M.normalize_extra_item(self.item("held_x", "1", "https://www.example.org/"), "now")


if __name__ == "__main__":
    unittest.main()
