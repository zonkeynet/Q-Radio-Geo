"""Privacy filter: no login, home dynamic-DNS host or (OSM/Wikidata) camera device endpoint is published."""
import contextlib
import gzip
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M

VECTORS = json.loads((ROOT / "tests" / "webcam_privacy_vectors.json").read_text(encoding="utf-8"))["cases"]
# The private records found in the package of 2026-11-14 (IDs only).
REVIEWED_PRIVATE_IDS = [
    "osm_webcams:node-11121976896-da65ec74e523",  # FRITZ!Box, login in the query
    "osm_webcams:node-11518170673-198f17e18eef", "osm_webcams:node-11518217243-e3f42db747a6",
    "osm_webcams:node-11520235060-2cfd19b679b9", "osm_webcams:node-11520240405-eed9c191417e",
    "osm_webcams:node-11520260836-fe14b711c127", "osm_webcams:node-11520265118-234559a95c44",
    "osm_webcams:node-11520279765-9ace003bed1e", "osm_webcams:node-11520280308-36ce4bad864b",  # ZoneMinder, login
    "osm_webcams:node-13075828343-d12f548351a4", "osm_webcams:node-13075828344-3acb194663bf",
    "osm_webcams:node-3276405297-05694595b2f5", "osm_webcams:node-4310736346-9fcfe49c3100",
    "osm_webcams:node-9580495498-635a7927fac0", "osm_webcams:way-1417680731-ae352b362270",  # dynamic DNS
]
FAKE = ("abcdefghijklmnop.myfritz.net", "homecam.ddns.net", "zm.example.es", "secret")


def osm_page(url, provider_id="node-1-aaaaaaaaaaaa", **changes):
    return {"provider": "osm_webcams", "provider_id": provider_id, "id": f"osm_webcams:{provider_id}",
            "name": "Harbour webcam", "lat": 54.3, "lng": 10.1, "country": "DE", "format": "official_page",
            "rights_status": "official_page_only", "official_page": url,
            "source_page": "https://www.openstreetmap.org/node/1", "coordinate_role": "camera_location", **changes}


class PrivacyRulesTest(unittest.TestCase):
    def test_shared_vectors(self):
        self.assertGreater(len(VECTORS), 40)
        for case in VECTORS:
            with self.subTest(case=case["case"], community=case["community"]):
                self.assertEqual(M.private_url_reason(case["url"], community=case["community"]), case["reason"])

    def test_page_url_refuses_exactly_the_private_vectors(self):
        for case in VECTORS:
            with self.subTest(case=case["case"]):
                link = M.page_url(case["url"], community=case["community"])
                if case["reason"]:
                    self.assertIsNone(link)
                else:
                    self.assertIsNotNone(link)

    def test_media_and_catalog_urls_refuse_logins_and_home_hosts_for_every_source(self):
        hosts = {"camera.example.com", "abcdefghijklmnop.myfritz.net"}
        self.assertEqual(M.canonical_url("https://camera.example.com/live.m3u8?v=1", hosts), "https://camera.example.com/live.m3u8?v=1")
        for url in ("https://camera.example.com/live.m3u8?token=abc", "https://camera.example.com/live.m3u8?Key=abc",
                    "https://abcdefghijklmnop.myfritz.net/live.m3u8"):
            self.assertIsNone(M.canonical_url(url, hosts), url)
        # Device endpoints are a community-record rule; official media hosts are reviewed per provider.
        self.assertEqual(M.canonical_url("https://camera.example.com/axis-cgi/jpg/image.cgi", hosts),
                         "https://camera.example.com/axis-cgi/jpg/image.cgi")

    def test_allow_list_is_per_host_and_documented(self):
        self.assertEqual(set(M.PUBLIC_QUERY_KEY_ALLOWLIST), {"api.qldtraffic.qld.gov.au"})
        self.assertIsNone(M.private_url_reason("https://api.qldtraffic.qld.gov.au/v1/floodcams?apikey=k"))
        with mock.patch.dict(M.PUBLIC_QUERY_KEY_ALLOWLIST, {"api.example.org": frozenset({"key"})}):
            self.assertIsNone(M.private_url_reason("https://api.example.org/v1?key=published"))
            self.assertEqual(M.private_url_reason("https://api.example.org/v1?pwd=x"), "credential_query")
            self.assertEqual(M.private_url_reason("https://www.example.org/v1?key=x"), "credential_query")

    def test_private_primary_link_removes_the_record_without_repeating_the_url(self):
        for case in VECTORS:
            if not case["reason"] or not case["community"]:
                continue
            with self.subTest(case=case["case"]):
                with self.assertRaises(M.PrivacyFiltered) as ctx:
                    M.normalize_extra_item(osm_page(case["url"]), "2026-11-14T00:00:00Z")
                self.assertEqual(ctx.exception.reason, case["reason"])
                self.assertEqual(ctx.exception.field, "official_page")
                for secret in FAKE:
                    self.assertNotIn(secret, str(ctx.exception))
        kept = M.normalize_extra_item(osm_page("https://www.example.org/webcam/image.jpg"), "now")
        self.assertEqual(kept["official_page"], "https://www.example.org/webcam/image.jpg")

    def test_device_paths_are_kept_for_reviewed_official_publishers(self):
        page = "https://www.example.it/panorama/axis-cgi/jpg/image.cgi"
        raw = {**osm_page(page), "provider": "opendatahub", "provider_id": "DSS_1", "id": "opendatahub:DSS_1",
               "country": "IT", "source_page": "https://opendatahub.com/"}
        self.assertFalse(M.community_source("opendatahub"))
        self.assertEqual(M.normalize_extra_item(raw, "now")["official_page"], page)

    def test_private_reference_is_dropped_from_a_kept_record_and_logged_without_url(self):
        log = []
        raw = osm_page("https://www.example.org/webcams", reference_snapshot_url="http://homecam.ddns.net/record/current.jpg",
                       reference_url="https://cam.example.de/axis-cgi/mjpg/video.cgi",
                       reference_hls_url="https://www.example.org/live/index.m3u8")
        item = M.normalize_extra_item(raw, "now", log)
        self.assertIsNone(item["reference_snapshot_url"])
        self.assertIsNone(item["reference_url"])
        self.assertEqual(item["reference_hls_url"], "https://www.example.org/live/index.m3u8")
        self.assertEqual({(e["field"], e["reason"], e["action"]) for e in log},
                         {("reference_snapshot_url", "dynamic_dns_host", "link_removed"),
                          ("reference_url", "device_path", "link_removed")})
        self.assertNotIn("ddns.net", json.dumps(log))
        self.assertNotIn("homecam", json.dumps(item))

    def test_sweep_removes_records_carrying_private_urls_in_any_copied_field(self):
        good = M.normalize_extra_item(osm_page("https://www.example.org/webcams"), "now")
        bad = {**good, "id": "osm_webcams:node-2-bbbbbbbbbbbb", "operator_notes": "mirror at http://homecam.ddns.net/live.jpg"}
        named = {**good, "id": "osm_webcams:node-3-cccccccccccc", "name": "Webcam · homecam.ddns.net"}
        kept, log = M.privacy_sweep([good, bad, named], [M.PROVIDER_POLICIES["osm_webcams"]["source"]])
        self.assertEqual([x["id"] for x in kept], [good["id"]])
        self.assertEqual([(e["field"], e["reason"]) for e in log], [("operator_notes", "dynamic_dns_host"), ("name", "dynamic_dns_host")])
        with self.assertRaises(ValueError):
            M.privacy_sweep([good], [{"id": "x", "url": "https://www.example.org/api?token=abc"}])

    def test_cli_build_publishes_no_private_link_and_reports_reasons(self):
        public = osm_page("https://www.example.org/webcams", "node-10-aaaaaaaaaaaa")
        private = [osm_page(case["url"], f"node-{20 + i}-aaaaaaaaaaaa")
                   for i, case in enumerate(c for c in VECTORS if c["reason"] and c["community"])]
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source_dir = folder / "caltrans"
            source_dir.mkdir()
            for district in range(1, 13):
                (source_dir / f"caltrans_d{district:02d}.json").write_text(json.dumps({"data": []}))
            extra = folder / "osm.json"
            extra.write_text(json.dumps({"sources": [{"id": "osm_webcams"}], "items": [public, *private]}))
            baseline = folder / "baseline.sqlite"
            db = sqlite3.connect(baseline)
            db.execute("CREATE TABLE surveillance_nodes(osm_node_id,lat,lon,operator,name,direction)")
            db.commit()
            db.close()
            out, out_db, audit = folder / "webcams.json", folder / "webcams.sqlite", folder / "audit"
            argv = ["build_webcams.py", "--source-dir", str(source_dir), "--osm-db", str(baseline),
                    "--extra-catalog", str(extra), "--out", str(out), "--db", str(out_db), "--audit-dir", str(audit),
                    "--compact-web", "--generated-at", "2026-11-14T00:00:00Z"]
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                M.main()
            catalog = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual([x["id"] for x in catalog["items"]], [public["id"]])
            report = json.loads((audit / "import_report.json").read_text(encoding="utf-8"))["privacy_filter"]
            self.assertEqual(report["records_removed"], len(private))
            self.assertEqual(set(report["records_removed_by_reason"]), {"credential_query", "dynamic_dns_host", "device_path"})
            ledger = json.loads((audit / "privacy_filter.json").read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["entries"]), len(private))
            written = "\n".join(p.read_text(encoding="utf-8") for p in audit.iterdir() if p.suffix in (".json", ".csv", ".geojson"))
            written += out.read_text(encoding="utf-8")
            with gzip.open(out_db.with_suffix(".sqlite.gz"), "rb") as f:
                written += f.read().decode("utf-8", "replace")
            for case in VECTORS:
                if case["reason"] and case["community"]:
                    self.assertNotIn(case["url"], written)
            for secret in FAKE:
                self.assertNotIn(secret, written)


class PublishedCatalogTest(unittest.TestCase):
    """The committed catalog itself: every URL in every record passes the filter."""

    def published(self):
        files = [p for p in (ROOT / "data" / "webcams.json", ROOT / "data" / "webcams-live.json") if p.exists()]
        if not files:
            self.skipTest("no published webcam catalog in this checkout")
        return files

    def test_no_private_url_in_published_catalogs(self):
        for path in self.published():
            with self.subTest(file=path.name):
                catalog = json.loads(path.read_text(encoding="utf-8"))
                if catalog.get("payload_kind") == "viewer_live":
                    catalog = M.expand_live_catalog(catalog)
                for source in catalog.get("sources", []):
                    self.assertIsNone(next(M.private_strings(source, False), None), source.get("id"))
                bad = [(row.get("id"), *hit) for row in catalog["items"]
                       for hit in M.private_strings(row, M.community_source(row.get("provider") or row.get("p")))]
                self.assertEqual(bad, [])
                text = path.read_text(encoding="utf-8")
                for record_id in REVIEWED_PRIVATE_IDS:
                    self.assertNotIn(record_id, text)
                # Independent of the filter's own code: no login-looking query key outside the allow-list.
                logins = re.findall(r"https?://([^/\"?#]+)[^\"]*?[?&;#](?:user|usr|login|pass|pwd|password|passwd|token|key)=", text, re.I)
                self.assertEqual([h for h in logins if h != "api.qldtraffic.qld.gov.au"], [])


class PublishingTest(unittest.TestCase):
    """The full webcam database is a release download: never tracked, never served, never mirrored."""

    def test_database_stays_out_of_the_site_and_the_ipfs_mirror(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("db/qp1ng-webcams.sqlite.gz", ignore)
        workflow = (ROOT / ".github" / "workflows" / "ipfs.yml").read_text(encoding="utf-8")
        self.assertIn(r"db/qp1ng-webcams\.sqlite", workflow)
        try:
            tracked = subprocess.run(["git", "ls-files", "db/"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git unavailable")
        if tracked.returncode:
            self.skipTest("not a git checkout")
        self.assertNotIn("db/qp1ng-webcams.sqlite.gz", tracked.stdout.split())


if __name__ == "__main__":
    unittest.main()
