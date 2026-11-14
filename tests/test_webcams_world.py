"""Worldwide imports: publication rights, deduplicated links and spatial precision."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import build_webcams as M
import collect_world_webcam_links as C


class WorldWebcamsTest(unittest.TestCase):
    def page(self, **changes):
        return {"provider": "wikidata_webcams", "provider_id": "Q42-test", "name": "Associated place",
                "lat": 51.5, "lng": -0.1, "country": "GB", "format": "official_page",
                "rights_status": "official_page_only", "official_page": "https://example.org/cameras#north",
                "source_page": "https://www.wikidata.org/wiki/Q42", "health": {"status": "live_confirmed"}, **changes}

    def test_page_preserves_anchor_without_becoming_an_embedded_stream(self):
        item = M.normalize_extra_item(self.page(), "2026-11-14T00:00:00Z")
        self.assertEqual(item["official_page"], "https://example.org/cameras#north")
        self.assertEqual(item["health"]["status"], "unverified")
        self.assertIsNone(item["stream_url"])
        self.assertIsNone(item["snapshot_url"])
        self.assertEqual(item["metadata_license"], "CC0-1.0")
        for update in ({"snapshot_url": "https://example.org/x.jpg"}, {"stream_url": "https://example.org/live.m3u8"},
                       {"format": "hls", "rights_status": "official_public_feed"}):
            with self.assertRaises(ValueError):
                M.normalize_extra_item(self.page(**update), "now")

    def test_source_file_cannot_self_approve_media_or_override_attribution(self):
        raw = self.page(metadata_license="public domain everywhere", attribution="attacker", media_rights="all allowed")
        item = M.normalize_extra_item(raw, "now")
        self.assertEqual(item["attribution"], M.PROVIDER_POLICIES["wikidata_webcams"]["source"]["attribution"])
        self.assertNotEqual(item["media_rights"], "all allowed")
        raw["provider"] = "unreviewed_provider"
        with self.assertRaises(ValueError):
            M.normalize_extra_item(raw, "now")

    def test_policy_prevents_coordinate_precision_promotion_and_spoofed_official_pages(self):
        item = M.normalize_extra_item(self.page(coordinate_role="camera_location", terms_url="https://evil.example.org/terms"), "now")
        self.assertEqual(item["coordinate_role"], "associated_feature")
        self.assertEqual(item["terms_url"], M.PROVIDER_POLICIES["wikidata_webcams"]["source"]["terms_url"])
        with self.assertRaises(ValueError):
            M.normalize_extra_item(self.page(provider="maryland_chart", country="US", official_page="https://evil.example.org/camera"), "now")

    def test_snapshot_requires_source_specific_approved_host(self):
        raw = {**self.page(), "provider": "digitraffic", "provider_id": "C123", "country": "FI", "lat": 62,
               "lng": 25, "format": "snapshot", "rights_status": "official_public_feed",
               "snapshot_url": "https://weathercam.digitraffic.fi/C123.jpg"}
        item = M.normalize_extra_item(raw, "now")
        self.assertEqual(item["coordinate_role"], "station_location")
        raw["snapshot_url"] = "https://another.example.org/C123.jpg"
        with self.assertRaises(ValueError):
            M.normalize_extra_item(raw, "now")
        raw["snapshot_url"] = "http://weathercam.digitraffic.fi/C123.jpg"
        with self.assertRaises(ValueError):
            M.normalize_extra_item(raw, "now")

    def test_web_links_reject_private_credentials_and_camera_search_aggregators(self):
        for url in ("https://127.0.0.1/a", "http://192.168.1.2/", "https://10.2.3.4/", "https://example.local/a",
                    "https://admin:password@example.org/", "javascript:alert(1)", "http://1.2.3.4/a",
                    "https://www.insecam.org/camera/1", "https://localhost/a", "https://0x7f.0.0.1/a",
                    "https://camera.pa.lcl/a", "https://camera.localdomain/a", "https://camera.intranet/a",
                    "https://camera.corp/a", "https://camera.home.arpa/a", "https://camera.%6cocal/path",
                    "https://127.0.0.0x1/path", "https://www.in%73ecam.org/camera/1"):
            self.assertIsNone(M.page_url(url), url)

    def test_nonstandard_public_ports_are_references_not_automatic_media_permissions(self):
        url = "https://video4.iowadot.gov:8888/ames/camera/playlist.m3u8"
        self.assertEqual(M.page_url(url), url)
        self.assertIsNone(M.canonical_url(url, {"video4.iowadot.gov"}))
        for bad in ("https://camera.pa.lcl:8888/view", "https://camera.example.org:0/view",
                    "https://camera.example.org:65536/view", "https://user:password@camera.example.org:8888/view"):
            self.assertIsNone(M.page_url(bad), bad)

    def test_multiple_provider_file_counts_each_source_once(self):
        rows = [self.page(), {**self.page(provider="osm_webcams", provider_id="node-1", country="IT"), "lat": 45, "lng": 9}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.json"
            path.write_text(json.dumps({"sources": [{"id": "wikidata_webcams"}, {"id": "osm_webcams"}], "items": rows}))
            items, _, provenance, rejected = M.load_extra_catalogs([path], "now")
            self.assertFalse(rejected)
            self.assertEqual(sum(p["records"] for p in provenance), 2)
            self.assertEqual({p["source"]: p["records"] for p in provenance}, {"wikidata_webcams": 1, "osm_webcams": 1})

    def test_associated_places_are_not_precise_camera_matches_and_dateline_is_handled(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE surveillance_nodes(osm_node_id INTEGER,lat REAL,lon REAL,operator TEXT,name TEXT,direction TEXT)")
        db.execute("INSERT INTO surveillance_nodes VALUES(1,0,-179.9997,NULL,NULL,NULL)")
        item = {"id": "test:1", "provider": "osm_webcams", "lat": 0, "lng": 179.9997, "coordinate_role": "associated_feature"}
        self.assertEqual(M.candidate_matches(db, item), [])
        item["coordinate_role"] = "camera_location"
        matches = M.candidate_matches(db, item)
        self.assertEqual([r["osm_node_id"] for r in matches], [1])
        self.assertLess(matches[0]["distance_m"], 100)
        item["coordinate_reference_system"] = "EPSG:7844"
        self.assertEqual(M.candidate_matches(db, item), [])

    def test_database_deduplicates_urls_without_merging_camera_identities(self):
        first = M.normalize_extra_item(self.page(), "2026-11-14T00:00:00Z")
        second = M.normalize_extra_item(self.page(provider_id="Q43-other"), "2026-11-14T00:00:00Z")
        catalog = {"schema_version": 2, "generated_at": "2026-11-14T00:00:00Z", "items": [first, second],
                   "sources": [M.PROVIDER_POLICIES["wikidata_webcams"]["source"]]}
        stats, shared = M.link_statistics(catalog["items"])
        self.assertEqual(stats["distinct_primary_urls"], 1)
        self.assertEqual(len(shared), 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.sqlite"
            M.write_database(path, catalog, [], stats)
            db = sqlite3.connect(path)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM public_webcams").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM published_urls").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM webcam_url_links").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM webcam_streams").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            db.close()

    def test_external_video_and_image_references_survive_exports_without_playback_permission(self):
        hls = "https://video4.iowadot.gov:8888/ames/camera/playlist.m3u8"
        snapshot = "https://atmsqf.iowadot.gov/SNAPSHOTS/PUBLIC/Metro/camera.jpeg"
        item = M.normalize_extra_item(self.page(reference_url=hls, reference_hls_url=hls,
                                                reference_snapshot_url=snapshot), "2026-11-14T00:00:00Z")
        self.assertEqual(item["format"], "official_page")
        self.assertEqual(item["rights_status"], "official_page_only")
        self.assertEqual(item["health"]["status"], "unverified")
        self.assertIsNone(item["stream_url"])
        self.assertIsNone(item["snapshot_url"])
        self.assertEqual(item["reference_hls_url"], hls)
        self.assertEqual(item["reference_snapshot_url"], snapshot)
        catalog = {"schema_version": 2, "generated_at": "2026-11-14T00:00:00Z", "items": [item],
                   "sources": [M.PROVIDER_POLICIES["wikidata_webcams"]["source"]]}
        stats, _ = M.link_statistics(catalog["items"])
        self.assertEqual(stats["distinct_published_urls_including_references"], 3)
        self.assertEqual(stats["hls_reference_urls_not_enabled_in_player"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "references.sqlite"
            M.write_database(path, catalog, [], stats)
            db = sqlite3.connect(path)
            try:
                self.assertEqual({r[0] for r in db.execute("SELECT url FROM published_urls")},
                                 {item["official_page"], hls, snapshot})
                links = set(db.execute("SELECT u.url,l.purpose,l.is_primary FROM webcam_url_links l "
                                       "JOIN published_urls u ON u.id=l.url_id"))
                self.assertIn((item["official_page"], "web_page", 1), links)
                self.assertIn((hls, "hls_reference_only", 0), links)
                self.assertIn((snapshot, "snapshot_reference_only", 0), links)
                self.assertEqual(db.execute("SELECT format,snapshot_url FROM public_webcams").fetchone(),
                                 ("official_page", None))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM webcam_streams").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM webcam_stream_links").fetchone()[0], 0)
                persisted = json.loads(db.execute("SELECT record_json FROM public_webcams").fetchone()[0])
                self.assertEqual(persisted["reference_hls_url"], hls)
                self.assertEqual(persisted["reference_snapshot_url"], snapshot)
            finally:
                db.close()
        expected = {hls: "hls_reference_only", snapshot: "snapshot_reference_only"}
        view = M.viewer_catalog(catalog)["items"][0]
        self.assertEqual(len(view["reference_links"]), 2)
        self.assertEqual({r["url"]: r["purpose"] for r in view["reference_links"]}, expected)
        self.assertEqual(view["format"], "official_page")
        self.assertIsNone(view.get("stream_url"))
        self.assertIsNone(view.get("snapshot_url"))
        # A reference repeated as the primary page must not become a second
        # viewer action; the distinct video and image references still survive.
        page_alias = {**item, "reference_url": item["official_page"]}
        projected = M.viewer_catalog({**catalog, "items": [page_alias]})["items"][0]
        self.assertEqual({r["url"]: r["purpose"] for r in projected["reference_links"]}, expected)

    def test_private_and_credential_references_are_removed_before_database_and_viewer_exports(self):
        unsafe = [
            ("https://10.2.3.4/live.m3u8", "https://user:password@camera.example.org/latest.jpg"),
            ("https://user:password@camera.example.org:8888/live.m3u8", "https://camera.local/latest.jpg"),
            ("https://camera.pa.lcl:8888/live.m3u8", "https://127.0.0.1/latest.jpg"),
        ]
        items = []
        for index, (video, snapshot) in enumerate(unsafe):
            with self.subTest(video=video, snapshot=snapshot):
                item = M.normalize_extra_item(self.page(provider_id=f"Q42-unsafe-{index}",
                                                        reference_url=video, reference_hls_url=video,
                                                        reference_snapshot_url=snapshot), "2026-11-14T00:00:00Z")
                for field in ("reference_url", "reference_hls_url", "reference_snapshot_url",
                              "stream_url", "snapshot_url"):
                    self.assertIsNone(item[field], field)
                self.assertEqual({link["url"] for link in M.published_links(item)}, {item["official_page"]})
                items.append(item)
        catalog = {"schema_version": 2, "generated_at": "2026-11-14T00:00:00Z", "items": items,
                   "sources": [M.PROVIDER_POLICIES["wikidata_webcams"]["source"]]}
        for row in M.viewer_catalog(catalog)["items"]:
            self.assertEqual(row.get("reference_links", []), [])
            self.assertEqual(row["rights_status"], "official_page_only")
        stats, _ = M.link_statistics(items)
        self.assertEqual(stats["distinct_published_urls_including_references"], 1)
        self.assertEqual(stats["hls_reference_urls_not_enabled_in_player"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsafe-references.sqlite"
            M.write_database(path, catalog, [], stats)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute("SELECT url FROM published_urls").fetchall(),
                                 [(items[0]["official_page"],)])
                self.assertEqual(db.execute("SELECT DISTINCT purpose FROM webcam_url_links").fetchall(),
                                 [("web_page",)])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM webcam_streams").fetchone()[0], 0)
                saved = "\n".join(row[0] for row in db.execute("SELECT record_json FROM public_webcams"))
                for pair in unsafe:
                    for url in pair:
                        self.assertNotIn(url, saved)
            finally:
                db.close()

    def test_country_inference_leaves_water_holes_and_unknown_places_unassigned(self):
        geo = {"features": [{"properties": {"ISO_A2_EH": "IT"}, "geometry": {"type": "Polygon", "coordinates": [
            [[0,0],[10,0],[10,10],[0,10],[0,0]], [[4,4],[6,4],[6,6],[4,6],[4,4]]
        ]}}]}
        countries = C.Countries(geo)
        self.assertEqual(countries.country(2, 2), "IT")
        self.assertEqual(countries.country(5, 5), "ZZ")
        self.assertEqual(countries.country(20, 20), "ZZ")

    def test_native_datum_is_preserved_without_false_wgs84_geojson_geometry(self):
        row = M.normalize_extra_item(self.page(coordinate_reference_system="EPSG:7844"), "now")
        feature = M.geojson_feature(row)
        self.assertIsNone(feature["geometry"])
        self.assertEqual(feature["properties"]["source_coordinates"], {"lat": 51.5, "lng": -0.1, "crs": "EPSG:7844"})
        row.pop("coordinate_reference_system")
        self.assertEqual(M.geojson_feature(row)["geometry"]["coordinates"], [-0.1, 51.5])

    def test_compact_view_preserves_media_status_and_source_rights_without_mutating_database_records(self):
        row = M.normalize_extra_item(self.page(requires_catalog_refresh=True, image_observed_at="2026-11-14T00:00:00Z"), "now")
        source = M.PROVIDER_POLICIES["wikidata_webcams"]["source"]
        full = {"schema_version": 2, "sources": [source], "items": [row]}
        view = M.viewer_catalog(full)
        self.assertEqual(view["items"][0]["official_page"], row["official_page"])
        self.assertEqual(view["items"][0]["rights_status"], "official_page_only")
        self.assertEqual(view["items"][0]["coordinate_role"], "associated_feature")
        self.assertTrue(view["items"][0]["requires_catalog_refresh"])
        self.assertNotIn("media_rights", view["items"][0])
        self.assertIn("media_rights", view["sources"][0])
        self.assertIn("media_rights", full["items"][0])


if __name__ == "__main__":
    unittest.main()
