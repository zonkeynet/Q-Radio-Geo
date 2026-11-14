"""Data integrity tests: identity, unsafe URLs, health evidence, spatial ambiguity."""
import importlib.util
import contextlib
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("build_webcams", pathlib.Path(__file__).parents[1] / "scripts/build_webcams.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class WebcamBuildTest(unittest.TestCase):
    def test_resumed_jsonl_import_preserves_corrupt_line_and_reports_degradation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "health.jsonl"
            first = {"url": "https://wzmedia.dot.ca.gov/first.m3u8", "checked_at": "2026-11-13T00:00:00Z"}
            later = {"url": "https://wzmedia.dot.ca.gov/later.m3u8", "checked_at": "2026-11-13T01:00:00Z"}
            raw = (json.dumps(first) + '\n{"url":\n' + json.dumps(later) + '\n').encode()
            path.write_bytes(raw)
            diagnostics = []
            with self.assertWarnsRegex(RuntimeWarning, "malformed JSONL line skipped"):
                events = M.load_probe_events([path], diagnostics)
            self.assertEqual(events, [first, later])
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics[0]["line"], 2)
            self.assertEqual(diagnostics[0]["reason"], "invalid_json")
            self.assertEqual(diagnostics[0]["line_sha256"], M.hashlib.sha256(b'{"url":').hexdigest())

    def test_jsonl_split_utf8_tail_is_preserved_and_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "health.jsonl"
            row = {"url": "https://wzmedia.dot.ca.gov/ok.m3u8"}
            raw = b'{"name":"\xc3\n' + json.dumps(row).encode() + b'\n'
            path.write_bytes(raw)
            diagnostics = []
            with self.assertWarns(RuntimeWarning):
                self.assertEqual(M.load_probe_events([path], diagnostics), [row])
            self.assertEqual(diagnostics[0]["reason"], "invalid_utf8")
            self.assertEqual(path.read_bytes(), raw)
            # Legacy callers still get the original list return type and a warning.
            with self.assertWarns(RuntimeWarning):
                self.assertEqual(M.load_probe_events([path]), [row])

    def test_malformed_whole_json_is_not_treated_as_partial_jsonl(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "health.json"
            path.write_text('[{"url":')
            with self.assertRaises(json.JSONDecodeError):
                M.load_probe_events([path])

    def camera(self, index="1", image="cam-a.jpg", stream="cam.stream/playlist.m3u8"):
        return {"index": index, "location": {"latitude": "38.5", "longitude": "-121.5", "locationName": "Test junction"},
                "inService": "true", "imageData": {"streamingVideoURL": "https://wzmedia.dot.ca.gov/" + stream,
                    "static": {"currentImageURL": "https://cwwp2.dot.ca.gov/" + image}}}

    def norway_camera(self, provider_id="4600001_1", format_="hls"):
        return {"id": f"vegvesen:{provider_id}", "provider": "vegvesen", "provider_id": provider_id,
                "name": "Norwegian road camera", "lat": 60.4, "lng": 5.3, "country": "NO",
                "region": "countyNumber:46", "county_number": 46, "road_number": "E39",
                "orientation_description": "Bergen", "orientation_is_bearing": False,
                "format": format_, "provider_in_service": True, "rights_status": "official_public_feed",
                "stream_url": f"https://kamera.vegvesen.no/public/{provider_id}/playlist.m3u8" if format_ == "hls" else None,
                "snapshot_url": f"https://kamera.atlas.vegvesen.no/api/images/{provider_id}",
                "observed_at": "2026-11-13T17:09:20+00:00"}

    def write_extra(self, path, items, sources=None, **extra):
        # The approved first adapter lacks an explicit schema version and a
        # source-level rights flag; neither omission grants trust to its items.
        obj = {"sources": sources if sources is not None else [{"id": "vegvesen"}], "items": items, **extra}
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    def test_extra_catalog_preserves_metadata_but_discards_embedded_health(self):
        raw = self.norway_camera()
        raw.update(health={"status": "live_confirmed", "checked_at": "2026-11-13T17:09:20Z"},
                   url_repair={"evidence": "untrusted"}, attribution="Override", district=99)
        item = M.normalize_extra_item(raw, "fallback")
        self.assertEqual(item["id"], raw["id"])
        self.assertEqual(item["region"], "Norway")
        self.assertEqual(item["county_number"], 46)
        self.assertEqual(item["road"], "E39")
        self.assertIsNone(item["direction"])
        self.assertFalse(item["orientation_is_bearing"])
        self.assertIsNone(item["district"])
        self.assertEqual(item["source_catalog"], M.VEGVESEN_SOURCE["catalog_url"])
        self.assertEqual(item["attribution"], M.VEGVESEN_SOURCE["attribution"])
        self.assertEqual(item["health"], M.unverified_health())
        self.assertNotIn("url_repair", item)
        snapshot = M.normalize_extra_item(self.norway_camera("4600002_1", "snapshot"), "fallback")
        self.assertTrue(snapshot["provider_in_service"])
        self.assertEqual(snapshot["format"], "snapshot")
        self.assertIsNone(snapshot["stream_url"])
        self.assertEqual(snapshot["health"]["status"], "unverified")

    def test_extra_catalog_cannot_self_approve_provider_rights_or_hosts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "extra.json"
            for source in ({"id": "unknown", "rights_status": "official_public_feed"},
                           {"id": "vegvesen", "rights_status": "public_domain"}):
                self.write_extra(path, [], [source])
                with self.subTest(source=source), self.assertRaises(ValueError):
                    M.load_extra_catalogs([path], "now")
            for change in ({"provider": "unknown"}, {"rights_status": "unreviewed"}, {"rights_status": None},
                           {"stream_url": "https://unknown.example/camera.m3u8"},
                           {"snapshot_url": "https://kamera.atlas.vegvesen.no.evil.example/camera.jpg"},
                           {"stream_url": "http://kamera.vegvesen.no/camera.m3u8"},
                           {"country": "US"}, {"lat": 38.5, "lng": -121.5}, {"lat": float("nan")},
                           {"id": "caltrans:some-id"}, {"format": "snapshot"}):
                raw = {**self.norway_camera(), **change}
                with self.subTest(change=change), self.assertRaises(ValueError):
                    M.normalize_extra_item(raw, "now")
            self.write_extra(path, [self.norway_camera(), {**self.norway_camera("2"), "rights_status": "unreviewed"},
                                    {**self.norway_camera("3"), "provider": "unknown"}],
                             [{"id": "vegvesen", "allowed_media_hosts": ["unknown.example"],
                               "terms_url": "https://unknown.example/terms"}])
            items, sources, provenance, rejected = M.load_extra_catalogs([path], "now")
            self.assertEqual(len(items), 1)
            self.assertEqual(len(rejected), 2)
            self.assertTrue(all(r["reason"] for r in rejected))
            self.assertEqual(provenance[0]["records"], 3)
            stats = M.provider_statistics(items, provenance, rejected, [], [])
            self.assertEqual(stats["vegvesen"]["source_records"], 3)
            self.assertEqual(stats["vegvesen"]["rejected_records"], 2)
            self.assertEqual(sources[0]["terms_url"], "https://data.norge.no/nlod/en/2.0")
            self.assertEqual(sources[0]["rights_status"], "official_public_feed")
            self.assertNotIn("unknown.example", str(sources))

    def test_repeatable_extra_catalog_hashes_each_input_and_rejects_identity_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self.write_extra(pathlib.Path(folder) / "part-one.json", [self.norway_camera()])
            second = self.write_extra(pathlib.Path(folder) / "part-two.json", [self.norway_camera("4600002_1", "snapshot")], schema_version=1)
            items, sources, provenance, rejected = M.load_extra_catalogs([first, second], "now")
            self.assertEqual(len(items), 2)
            self.assertEqual([s["id"] for s in sources], ["vegvesen"])
            self.assertEqual(rejected, [])
            self.assertEqual([p["sha256"] for p in provenance], [M.hashlib.sha256(p.read_bytes()).hexdigest() for p in [first, second]])
            self.assertEqual(provenance[0]["observed_at"], "2026-11-13T17:09:20+00:00")
            with self.assertRaisesRegex(ValueError, "Duplicate camera identity"):
                M.load_extra_catalogs([first, first], "now")
            self.write_extra(second, [], schema_version=2)
            with self.assertRaisesRegex(ValueError, "schema"):
                M.load_extra_catalogs([second], "now")

    def test_provider_health_is_allowlisted_and_local_stops_preserve_completed_evidence(self):
        for stopped in ("budget_exhausted", "stopped", "interrupted"):
            item = M.normalize_extra_item(self.norway_camera(), "now")
            live = {"url": item["stream_url"], "checked_at": "2026-11-13T00:00:00Z", "live_verified": True,
                    "manifest_valid": True, "segment_ok": True, "advancing": True}
            stop = {"url": item["stream_url"], "checked_at": "2026-11-13T01:00:00Z", "status": stopped,
                    "manifest_valid": True, "http_status": 200, "error": stopped}
            events = [stop, live]
            before = json.dumps(events)
            with self.subTest(stopped=stopped):
                M.apply_health([item], events)
                self.assertEqual(item["health"]["status"], "live_confirmed")
                self.assertEqual(item["health"]["checked_at"], "2026-11-13T00:00:00.000000+00:00")
                self.assertEqual(item["health"]["last_probe_at"], "2026-11-13T01:00:00.000000+00:00")
                self.assertEqual(item["health"]["incomplete_probe_count"], 1)
                self.assertEqual(item["health"]["probe_count"], 2)
                self.assertEqual(json.dumps(events), before)
                M.apply_health([item], [stop])
                self.assertEqual(item["health"]["status"], "live_confirmed")
                self.assertEqual(item["health"]["last_completed_probe_at"], "2026-11-13T00:00:00.000000+00:00")
                fresh = M.normalize_extra_item(self.norway_camera(), "now")
                M.apply_health([fresh], [stop])
                self.assertEqual(fresh["health"]["status"], "unverified")
                self.assertIsNone(fresh["health"]["checked_at"])
                self.assertIsNone(fresh["health"]["last_completed_probe_at"])
                stats = M.provider_statistics([fresh], [], [], [stop], [])["vegvesen"]
                self.assertEqual(stats["attempted_distinct_hls_urls"], 1)
                self.assertEqual(stats["probed_distinct_hls_urls"], 0)
                # A later real HTTP failure still supersedes the completed positive.
                failure = {"url": item["stream_url"], "checked_at": "2026-11-13T02:00:00Z", "http_status": 404}
                M.apply_health([item], [live, stop, failure])
                self.assertEqual(item["health"]["status"], "unavailable")
        item = M.normalize_extra_item(self.norway_camera(), "now")
        M.apply_health([item], [{**live, "provider": "caltrans"}])
        self.assertEqual(item["health"]["status"], "unverified")
        item["stream_url"] = "https://wzmedia.dot.ca.gov/camera.m3u8"
        M.apply_health([item], [{**live, "url": item["stream_url"]}])
        self.assertEqual(item["health"]["status"], "unverified")

    def test_operator_hint_uses_the_camera_provider_without_confirming_identity(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE surveillance_nodes(osm_node_id,lat,lon,operator,name,direction)")
        db.executemany("INSERT INTO surveillance_nodes VALUES(?,?,?,?,?,?)", [
            (1, 60.4, 5.3, "Statens vegvesen", "North", "N"),
            (2, 60.4, 5.3, "Caltrans", "Unrelated operator", "S")])
        candidates = M.candidate_matches(db, M.normalize_extra_item(self.norway_camera(), "now"))
        self.assertEqual([(x["osm_node_id"], x["operator_hint"]) for x in candidates], [(1, True), (2, False)])
        self.assertTrue(all(not x["identity_confirmed"] for x in candidates))
        db.close()

    def test_fixture_cli_build_combines_providers_without_changing_baseline_or_caltrans(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            source_dir = folder / "sources"
            source_dir.mkdir()
            for district in range(1, 13):
                rows = [{"cctv": self.camera()}] if district == 3 else []
                (source_dir / f"caltrans_d{district:02d}.json").write_text(json.dumps({"data": rows}))
            caltrans = M.normalize_caltrans(self.camera(), 3, "2026-11-13T00:00:00Z")
            norway = self.norway_camera()
            first = self.write_extra(folder / "norway-hls.json", [norway])
            second = self.write_extra(folder / "norway-snapshot.json", [self.norway_camera("4600002_1", "snapshot")])
            evidence = folder / "health.json"
            events = [{"url": item["stream_url"], "checked_at": "2026-11-13T01:00:00Z", "manifest_valid": True,
                       "segment_ok": True, "advancing": True, "live_verified": True} for item in [caltrans, norway]]
            events.append({"url": norway["stream_url"], "checked_at": "2026-11-13T02:00:00Z",
                           "status": "budget_exhausted", "error": "budget_exhausted", "manifest_valid": True})
            evidence.write_text(json.dumps(events))
            baseline = folder / "baseline.sqlite"
            db = sqlite3.connect(baseline)
            db.execute("CREATE TABLE surveillance_nodes(osm_node_id,lat,lon,operator,name,direction)")
            db.executemany("INSERT INTO surveillance_nodes VALUES(?,?,?,?,?,?)", [
                (10, 38.5, -121.5, "Caltrans", "California", "N"),
                (11, 60.4, 5.3, "Statens vegvesen", "Norway", "S")])
            db.commit()
            db.close()
            before = baseline.read_bytes()
            out, out_db, audit = folder / "webcams.json", folder / "webcams.sqlite", folder / "audit"
            argv = ["build_webcams.py", "--source-dir", str(source_dir), "--osm-db", str(baseline),
                    "--extra-catalog", str(first), "--extra-catalog", str(second), "--health", str(evidence),
                    "--out", str(out), "--db", str(out_db), "--audit-dir", str(audit),
                    "--generated-at", "2026-11-13T00:00:00Z"]
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                M.main()
            catalog = json.loads(out.read_text())
            report = json.loads((audit / "import_report.json").read_text())
            self.assertEqual(baseline.read_bytes(), before)
            self.assertEqual(report["provider_counts"], {"caltrans": 1, "vegvesen": 2})
            self.assertEqual(report["source_records"], 3)
            self.assertEqual(report["hls_camera_records"], 2)
            self.assertEqual(report["snapshot_only_records"], 1)
            self.assertEqual(report["health_camera_counts"], {"live_confirmed": 2, "unverified": 1})
            self.assertEqual(report["scope_providers"], ["caltrans", "vegvesen"])
            self.assertEqual(report["scope_countries"], ["NO", "US"])
            self.assertIn("Norway", report["scope"])
            no_stats = report["provider_stats"]["vegvesen"]
            self.assertEqual(no_stats["probed_distinct_hls_urls"], 1)
            self.assertEqual(no_stats["completed_probe_events"], 1)
            self.assertEqual(no_stats["incomplete_probe_events"], 1)
            self.assertEqual(report["probed_distinct_hls_urls"], 2)
            caltrans_output = next(x for x in catalog["items"] if x["provider"] == "caltrans")
            self.assertEqual({k: v for k, v in caltrans_output.items() if k != "health"},
                             {k: v for k, v in caltrans.items() if k != "health"})
            self.assertEqual(json.loads((audit / "probe_evidence.json").read_text()), events)
            db = sqlite3.connect(out_db)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute("SELECT provider,count(*) FROM public_webcams GROUP BY provider").fetchall(), [("caltrans", 1), ("vegvesen", 2)])
            self.assertEqual(db.execute("SELECT count(*) FROM webcam_streams").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM webcam_stream_links").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM public_webcams WHERE provider='vegvesen' AND district IS NULL AND source_catalog IS NOT NULL").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT url,rights_status FROM sources WHERE id='vegvesen'").fetchone(),
                             (M.VEGVESEN_SOURCE["url"], "official_public_feed"))
            self.assertEqual(db.execute("SELECT count(*) FROM osm_candidate_links WHERE operator_hint=1").fetchone()[0], 3)
            db.close()

    def test_identity_survives_source_index_change(self):
        a = M.normalize_caltrans(self.camera("1"), 3, "2026-11-13T00:00:00Z")
        b = M.normalize_caltrans(self.camera("900"), 3, "2026-11-13T00:00:00Z")
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(a["provider_id"], b["provider_id"])

    def test_close_distinct_views_keep_distinct_identity(self):
        a = M.normalize_caltrans(self.camera(image="cam-a.jpg"), 3, "now")
        b = M.normalize_caltrans(self.camera(image="cam-b.jpg"), 3, "now")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(a["stream_url"], b["stream_url"])

    def test_private_credentials_and_unapproved_hosts_rejected(self):
        for url in ["http://10.0.0.1/video", "http://127.0.0.1/video", "http://[::1]/video", "http://169.254.169.254/",
                    "https://user:pass@wzmedia.dot.ca.gov/video", "https://wzmedia.dot.ca.gov.evil.example/video",
                    "https://wzmedia.dot.ca.gov\\@evil.example/video", "https://wzmedia.dot.ca.gov:8443/video", "file:///etc/passwd"]:
            with self.subTest(url=url):
                self.assertIsNone(M.canonical_url(url, M.ALLOWED_HOSTS))

    def test_snapshot_never_becomes_hls_by_provider_flag(self):
        raw = self.camera(stream="not-a-playlist")
        item = M.normalize_caltrans(raw, 3, "now")
        self.assertEqual(item["format"], "snapshot")
        self.assertIsNone(item["stream_url"])
        self.assertEqual(item["health"]["status"], "unverified")
        self.assertTrue(item["provider_in_service"])

    def test_http200_never_implies_live(self):
        self.assertEqual(M.event_health({"http_status": 200, "valid": True, "status": "manifest_reachable"})["status"], "playlist_ok")
        self.assertNotEqual(M.event_health({"live_verified": True, "valid": True})["status"], "live_confirmed")
        e = {"checked_at": "2026-11-13T00:00:00Z", "live_verified": True, "valid": True, "segment_ok": True, "advancing": True}
        self.assertEqual(M.event_health(e)["status"], "live_confirmed")
        e["endlist"] = True
        self.assertNotEqual(M.event_health(e)["status"], "live_confirmed")

    def test_error_or_missing_time_cannot_claim_live(self):
        e = {"live_verified": True, "valid": True, "segment_ok": True, "advancing": True}
        self.assertNotEqual(M.event_health(e)["status"], "live_confirmed")
        e.update(checked_at="2026-11-13T00:00:00Z", http_status=404, error="HTTP Error 404")
        self.assertNotEqual(M.event_health(e)["status"], "live_confirmed")

    def test_segment404_does_not_relabel_master_as404(self):
        h = M.event_health({"observed_at": "2026-11-13T00:00:00Z", "manifest_valid": True,
                            "http_status": 200, "has_segments": True, "error": "HTTP Error 404"})
        self.assertEqual(h["status"], "network_unverified")
        self.assertEqual(h["http_status"], 200)
        self.assertEqual(h["failure_http_status"], 404)

    def test_output_cannot_overwrite_baseline(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            base = pathlib.Path(folder) / "base.sqlite"
            base.write_bytes(b"do-not-change")
            with self.assertRaises(ValueError):
                M.protect_baseline(base, [base.parent / "." / base.name])
            self.assertEqual(base.read_bytes(), b"do-not-change")

    def test_unclassified_video_without_snapshot_is_rejected(self):
        raw = self.camera(stream="not-a-playlist")
        raw["imageData"]["static"]["currentImageURL"] = ""
        with self.assertRaises(ValueError):
            M.normalize_caltrans(raw, 3, "now")

    def test_repair_must_match_source_and_have_manifest_evidence(self):
        item = M.normalize_caltrans(self.camera(stream="missing-suffix"), 3, "now")
        r = {"provider_id": item["provider_id"], "original_url": item["source_video_url"],
             "candidate_url": "https://wzmedia.dot.ca.gov/repaired.stream/playlist.m3u8",
             "checked_at": "2026-11-13T00:00:00Z", "http_status": 404, "hls_manifest_valid": False}
        self.assertEqual(M.apply_verified_repairs([item], [r]), [])
        self.assertIsNone(item["stream_url"])
        r.update(http_status=200, hls_manifest_valid=True)
        self.assertEqual(len(M.apply_verified_repairs([item], [r])), 1)
        self.assertEqual(item["format"], "hls")
        self.assertEqual(item["source_video_url"], r["original_url"])
        self.assertEqual(item["health"]["status"], "unverified")

    def test_newer_failure_replaces_old_live_evidence(self):
        item = M.normalize_caltrans(self.camera(), 3, "now")
        live = {"url": item["stream_url"], "checked_at": "2026-11-13T00:00:00Z", "live_verified": True,
                "valid": True, "segment_ok": True, "advancing": True}
        fail = {"url": item["stream_url"], "checked_at": "2026-11-13T01:00:00Z", "http_status": 404}
        M.apply_health([item], [fail, live])
        self.assertEqual(item["health"]["status"], "unavailable")

    def test_two_nearby_osm_nodes_are_candidates_not_identity(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE surveillance_nodes(osm_node_id,lat,lon,operator,name,direction)")
        db.executemany("INSERT INTO surveillance_nodes VALUES(?,?,?,?,?,?)", [
            (10, 38.5, -121.5, "Caltrans", "North", "N"),
            (11, 38.5001, -121.5, "Another operator", "South", "S"),
            (12, 39, -121.5, "Caltrans", "Far", "S")])
        item = M.normalize_caltrans(self.camera(), 3, "now")
        candidates = M.candidate_matches(db, item, 100)
        self.assertEqual({x["osm_node_id"] for x in candidates}, {10, 11})
        self.assertTrue(all(x["match_status"] == "geographic_candidate_only" and not x["identity_confirmed"] for x in candidates))
        self.assertEqual(db.execute("SELECT count(*) FROM surveillance_nodes").fetchone()[0], 3)
        db.close()


if __name__ == "__main__":
    unittest.main()
