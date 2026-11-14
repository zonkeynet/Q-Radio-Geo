"""Legal and safety exclusions (scripts/webcam_exclusions.json) and the no-media-as-page rule."""
import contextlib
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M

RULES = M.load_exclusions()["rules"]
LOG = []


def osm(url, node, lat=48.2, lng=16.37, country="AT", **changes):
    return {"provider": "osm_webcams", "provider_id": f"node-{node}-aaaaaaaaaaaa", "id": f"osm_webcams:node-{node}-aaaaaaaaaaaa",
            "name": "Webcam", "lat": lat, "lng": lng, "country": country, "format": "official_page",
            "rights_status": "official_page_only", "official_page": url,
            "source_page": f"https://www.openstreetmap.org/node/{node}", "coordinate_role": "camera_location", **changes}


def build(raw):
    return M.normalize_extra_item(M.repair_raw(raw, RULES, LOG), "2026-11-14T00:00:00Z")


def removed_by(item):
    rule = M.exclusion_rule(item, RULES)
    return rule and rule["id"]


class RulesFileTest(unittest.TestCase):
    def test_every_rule_has_a_reason_evidence_and_a_known_action(self):
        ids = [r["id"] for r in RULES]
        self.assertEqual(ids, ["ua-martial-law", "asfinag-terms", "nsw-livetraffic-terms", "kz-business-premises",
                               "kytc-cc0-withdrawn", "a22-image-not-page", "media-url-not-page"])
        for rule in RULES:
            self.assertTrue(rule["reason"].strip() and rule["evidence"], rule["id"])
            self.assertTrue(all(u.startswith("https://") for u in rule["evidence"]), rule["id"])

    def test_policies_marked_excluded_need_a_rule(self):
        excluded = {k for k, p in M.PROVIDER_POLICIES.items() if p.get("status") == "excluded"}
        self.assertEqual(excluded, {"nsw_transport", "kentucky_kytc"})
        self.assertNotIn("CC0", M.PROVIDER_POLICIES["kentucky_kytc"]["source"]["metadata_license"].split(".")[0])
        self.assertIn("not established", M.PROVIDER_POLICIES["kentucky_kytc"]["source"]["metadata_license"])
        policies = {"x": {"status": "excluded", "source": {}}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rules.json"
            path.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                M.load_exclusions(path, policies)
            path.write_text(json.dumps({"version": 1, "rules": [{"id": "no-evidence", "action": "remove_record",
                                                                 "match": {"providers": ["x"]}, "reason": "r"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                M.load_exclusions(path, policies)


class RemovalTest(unittest.TestCase):
    def test_ukraine_by_country_by_outline_for_unassigned_and_crimea_whatever_the_label(self):
        self.assertEqual(removed_by(build(osm("https://www.example.ua/cam", 1, 49.55, 25.6, "UA"))), "ua-martial-law")
        self.assertEqual(removed_by(build(osm("https://www.example.org/cam", 2, 50.45, 30.52, "ZZ"))), "ua-martial-law")
        self.assertEqual(removed_by(build(osm("https://www.example.org/cam", 3, 44.6, 33.52, "RU"))), "ua-martial-law")
        for lat, lng, country in ((47.01, 28.86, "ZZ"), (52.09, 23.69, "ZZ"), (50.6, 36.59, "RU"), (49.78, 22.77, "PL"),
                                  (49.44, 22.21, "PL"), (52.10, 30.97, "BY")):
            self.assertIsNone(removed_by(build(osm("https://www.example.org/cam", 4, lat, lng, country))), (lat, lng))
        self.assertIsNone(removed_by(build(osm("https://bukovel.com/cams/slope", 5, 48.36, 24.4, "UA"))), "Bukovel stays")

    def test_asfinag_anywhere_in_the_record_including_subdomains(self):
        self.assertEqual(removed_by(build(osm("https://www.asfinag.at/verkehr-sicherheit/webcams?id=1", 6))), "asfinag-terms")
        self.assertEqual(removed_by(build(osm("https://www.example.at/cams", 7, reference_url="https://webcams.asfinag.at/x"))), "asfinag-terms")
        self.assertIsNone(removed_by(build(osm("https://asfinag.at.example.org/cams", 8))))

    def test_whole_sources_and_business_premises(self):
        self.assertEqual(removed_by({"provider": "nsw_transport", "lat": -33.8, "lng": 151.2, "country": "AU"}), "nsw-livetraffic-terms")
        self.assertEqual(removed_by({"provider": "kentucky_kytc", "lat": 38.2, "lng": -85.7, "country": "US"}), "kytc-cc0-withdrawn")
        self.assertEqual(removed_by(build(osm("http://www.nexxiopizza.kz/cam1", 9, 51.2, 51.37, "KZ"))), "kz-business-premises")


class MediaPageTest(unittest.TestCase):
    def les(self, provider, page, **extra):
        return {"provider": provider, "provider_id": "abc123", "id": f"{provider}:abc123", "name": "Camera", "lat": 37.5, "lng": -77.4,
                "country": "US", "format": "official_page", "rights_status": "official_page_only", "stream_url": None,
                "snapshot_url": None, "official_page": page, "reference_url": page, "reported_media_format": "hls",
                "source_page": "https://github.com/william-ricchiuti/Live-Environment-Streams", **extra}

    def test_a22_image_becomes_an_image_reference(self):
        item = build(osm("https://www.autobrennero.it/WebCamImg/km68.jpg", 10, 46.53, 11.49, "IT"))
        self.assertEqual(item["official_page"], "https://www.openstreetmap.org/node/10")
        self.assertEqual(item["reference_snapshot_url"], "https://www.autobrennero.it/WebCamImg/km68.jpg")

    def test_stream_pages_become_the_operator_map_and_stay_references(self):
        vdot = build(self.les("les_vdot", "https://media-sfs2.vdotcameras.com/rtplive/HamptonRoads780/playlist.m3u8"))
        self.assertEqual(vdot["official_page"], "https://511.vdot.virginia.gov/")
        self.assertEqual(vdot["reference_url"], "https://media-sfs2.vdotcameras.com/rtplive/HamptonRoads780/playlist.m3u8")
        self.assertIsNone(vdot["stream_url"]); self.assertEqual(vdot["rights_status"], "official_page_only")
        bandung = build({**self.les("les_atcs_bandung", "https://atcs-dishub.bandung.go.id:1990/BubatSel/index.m3u8"),
                         "lat": -6.9, "lng": 107.6, "country": "ID"})
        self.assertEqual(bandung["official_page"], M.PROVIDER_POLICIES["les_atcs_bandung"]["source"]["url"])
        keelung = build({**self.les("les_tdx_city_cctv", "https://cctv.klcg.gov.tw/05c7e2d9", reported_media_format="mjpeg"),
                         "lat": 25.1, "lng": 121.7, "country": "TW"})
        self.assertNotEqual(keelung["official_page"], "https://cctv.klcg.gov.tw/05c7e2d9", "a URL its row reports as media is no page")
        self.assertEqual(M.media_page_records([vdot, bandung, keelung]), [])

    def test_community_media_moves_to_the_matching_reference(self):
        for url, field in (("https://www.example.de/cam/live.m3u8", "reference_hls_url"),
                           ("https://www.example.de/cam/last.jpeg", "reference_snapshot_url"),
                           ("https://www.example.de/cam/day.mp4", "reported_clip_url")):
            item = build(osm(url, 11, 51.0, 10.0, "DE"))
            self.assertEqual(item[field], url)
            self.assertEqual(item["official_page"], "https://www.openstreetmap.org/node/11")

    def test_a_private_media_page_still_removes_the_record(self):
        with self.assertRaises(M.PrivacyFiltered):
            build(osm("http://homecam.ddns.net/record/current.jpg", 12, 51.0, 10.0, "DE"))

    def test_the_build_stops_if_a_media_page_is_left(self):
        stray = osm("https://www.example.de/cam/live.m3u8", 13, 51.0, 10.0, "DE")
        self.assertEqual(M.media_page_records([M.normalize_extra_item(stray, "now")]), [(stray["id"], "official_page")])
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "caltrans").mkdir()
            for district in range(1, 13):
                (folder / "caltrans" / f"caltrans_d{district:02d}.json").write_text(json.dumps({"data": []}))
            extra = folder / "osm.json"
            extra.write_text(json.dumps({"sources": [{"id": "osm_webcams"}], "items": [stray]}))
            db = sqlite3.connect(folder / "base.sqlite")
            db.execute("CREATE TABLE surveillance_nodes(osm_node_id,lat,lon,operator,name,direction)")
            db.commit(); db.close()
            argv = ["build_webcams.py", "--source-dir", str(folder / "caltrans"), "--osm-db", str(folder / "base.sqlite"),
                    "--extra-catalog", str(extra), "--out", str(folder / "w.json"), "--db", str(folder / "w.sqlite"),
                    "--audit-dir", str(folder / "audit"), "--compact-web"]
            no_repair = {"version": 1, "sha256": None, "rules": [r for r in RULES if r["action"] == "remove_record"]}
            with mock.patch("sys.argv", argv), mock.patch.object(M, "load_exclusions", return_value=no_repair), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "media file as their page"):
                M.main()
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                M.main()
            report = json.loads((folder / "audit" / "import_report.json").read_text(encoding="utf-8"))["exclusions"]
            self.assertEqual(report["fields_repaired_by_rule"], {"media-url-not-page": 1})


class PublishedCatalogExclusionsTest(unittest.TestCase):
    def test_published_catalogues_hold_no_excluded_record_or_media_page(self):
        files = [p for p in (ROOT / "data" / "webcams.json", ROOT / "data" / "webcams-live.json") if p.exists()]
        if not files:
            self.skipTest("no published webcam catalog in this checkout")
        for path in files:
            with self.subTest(file=path.name):
                catalog = json.loads(path.read_text(encoding="utf-8"))
                if catalog.get("payload_kind") == "viewer_live":
                    catalog = M.expand_live_catalog(catalog)
                self.assertEqual([(r["id"], removed_by(r)) for r in catalog["items"] if removed_by(r)], [])
                self.assertEqual(M.media_page_records(catalog["items"]), [])
                self.assertFalse({"nsw_transport", "kentucky_kytc"} & {s["id"] for s in catalog["sources"]})
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"asfinag\.at|nexxiopizza", text))


if __name__ == "__main__":
    unittest.main()
