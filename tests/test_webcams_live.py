"""The viewable-webcam file the globe loads first: same rows as the full view, fewer bytes."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M


def expand(live):
    return M.expand_live_catalog(live)["items"]


def view_row(provider, ident, fmt, **extra):
    row = {"id": f"{provider}:{ident}", "provider": provider, "name": f"Camera {ident}", "lat": 0.0, "lng": 12.5,
           "country": "NO", "format": fmt, "rights_status": "official_page_only" if fmt == "official_page" else "official_public_feed",
           "source_page": "https://www.example.no/cameras", "observed_at": "2026-11-14T00:00:00Z",
           "coordinate_role": "camera_location", "health": {"status": "unverified"}}
    row.update(extra)
    return row


class LiveCatalogTest(unittest.TestCase):
    def view(self):
        return {"schema_version": 2, "generated_at": "2026-11-14T00:00:00Z", "payload_kind": "viewer_projection",
                "sources": [{"id": "vegvesen", "name": "Roads", "attribution": "NLOD", "terms_url": "https://example.no/terms",
                             "raw_files": [{"url": "https://example.no/raw.json"}], "rights_note": "long text"},
                            {"id": "osm_webcams", "name": "OSM", "provenance_type": "community_directory"}],
                "items": [view_row("vegvesen", "1", "hls", stream_url="https://kamera.example.no/1/index.m3u8",
                                   snapshot_url="https://kamera.example.no/1.jpg",
                                   reference_links=[{"url": "https://kamera.example.no/1-alt.jpg", "purpose": "snapshot_reference_only"}]),
                          view_row("vegvesen", "2", "snapshot", snapshot_url="https://kamera.example.no/2.jpg",
                                   health={"status": "live_confirmed", "checked_at": "2026-11-13T00:00:00Z"},
                                   minimum_refresh_seconds=60, provider_in_service=False),
                          view_row("vegvesen", "3", "hls"),  # no admitted stream: not viewable
                          view_row("osm_webcams", "node-1", "official_page", official_page="https://www.example.org/cam")]}

    def test_only_viewable_rows_round_trip_exactly(self):
        view = self.view()
        live = M.live_view_catalog(view)
        self.assertEqual((live["schema_version"], live["payload_kind"]), (3, "viewer_live"))
        self.assertEqual(live["full_catalog"], {"url": "data/webcams.json", "records": 4,
                                                "note": "Every record, web links included; loaded on request."})
        self.assertEqual(expand(live), view["items"][:2])
        self.assertEqual(live["values"]["provider"], [None, "vegvesen"])
        self.assertEqual(live["values"]["provider_in_service"], [None, False])
        self.assertEqual([r[live["fields"].index("lat")] for r in live["rows"]], [0.0, 0.0], "a zero latitude is a value, not absence")

    def test_sources_keep_only_what_the_viewer_reads(self):
        live = M.live_view_catalog(self.view())
        self.assertEqual(live["sources"], [{"id": "vegvesen", "name": "Roads", "terms_url": "https://example.no/terms",
                                            "attribution": "NLOD"}])

    def test_live_output_needs_the_compact_view(self):
        argv = ["build_webcams.py", "--source-dir", "x", "--osm-db", "y", "--live-out", "z.json"]
        with mock.patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            M.main()


class PublishedLiveCatalogTest(unittest.TestCase):
    def test_committed_live_file_matches_the_full_view(self):
        live_path, full_path = ROOT / "data" / "webcams-live.json", ROOT / "data" / "webcams.json"
        if not live_path.exists() or not full_path.exists():
            self.skipTest("no published webcam catalog in this checkout")
        live = json.loads(live_path.read_text(encoding="utf-8"))
        full = json.loads(full_path.read_text(encoding="utf-8"))
        viewable = [row for row in full["items"] if M.viewable(row)]
        self.assertEqual(expand(live), viewable)
        self.assertEqual(live["full_catalog"]["records"], len(full["items"]))
        self.assertEqual({f for f in ("hls", "snapshot")}, {row["format"] for row in viewable})


if __name__ == "__main__":
    unittest.main()
