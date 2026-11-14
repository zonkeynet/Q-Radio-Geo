"""Reference adapters: published GeoNet axes, identity and image timestamps."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import build_webcams as B
import collect_reference_webcams as C


class GeoNetReferenceTest(unittest.TestCase):
    receipt = {
        "url": "https://www.geonet.org.nz/volcano/cameras/geojson",
        "observed_at": "2026-11-14T02:40:00Z",
        "sha256": "0" * 64,
    }
    source = {
        "id": "geonet_volcano",
        "name": "GeoNet volcano cameras",
        "url": "https://www.geonet.org.nz/data/types/camera",
        "terms_url": "https://www.geonet.org.nz/policy",
        "license_url": "https://creativecommons.org/licenses/by/3.0/nz/",
        "metadata_license": "CC-BY-3.0-NZ",
        "media_rights": "GeoNet image publication under CC BY 3.0 NZ",
        "attribution": "GeoNet and its sponsors",
        "minimum_refresh_seconds": 600,
    }

    def feature(self, camera_id="ngauruhoe", *, coordinates=None, image=None, timestamp=None):
        return {
            "type": "Feature",
            "id": camera_id,
            "geometry": {
                "type": "Point",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "coordinates": [-39.16732, 175.48055] if coordinates is None else coordinates,
            },
            "properties": {
                "title": "Ngauruhoe from West",
                "latest-image-large": image or f"latest/{camera_id}.jpg",
                "latest-timestamp": timestamp or " 3:30 pm (NZDT) 14 Nov 2026",
                "azimuth": 84,
            },
            # Published status claims must not become our measured health.
            "health": {"status": "live_confirmed", "advancing": True},
        }

    def rows(self, *groups):
        return C.geonet_rows(
            [{"type": "FeatureCollection", "features": group} for group in groups],
            self.receipt,
            self.source,
        )

    def test_published_latitude_longitude_axes_are_normalized_without_guessing(self):
        feature = self.feature()
        row = self.rows([feature])[0]
        self.assertEqual((row["lat"], row["lng"]), (-39.16732, 175.48055))
        self.assertEqual(row["source_coordinates"], feature["geometry"]["coordinates"])
        self.assertEqual(row["source_coordinate_axis_order"], "latitude,longitude")
        self.assertEqual(row["coordinate_role"], "station_location")
        self.assertEqual(row["snapshot_url"], "https://images.geonet.org.nz/volcano/cameras/latest/ngauruhoe.jpg")
        self.assertNotIn("health", row)
        with self.assertRaisesRegex(ValueError, "latitude/longitude order"):
            self.rows([self.feature(coordinates=[175.48055, -39.16732])])

    def test_repeated_camera_identity_is_deduplicated_but_shared_location_is_not(self):
        original = self.feature()
        repeated = copy.deepcopy(original)
        second_camera = self.feature("ngauruhoe-other-view")
        rows = self.rows([original], [repeated, second_camera])
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["provider_id"] for r in rows}, {"ngauruhoe", "ngauruhoe-other-view"})
        self.assertEqual({(r["lat"], r["lng"]) for r in rows}, {(-39.16732, 175.48055)})
        self.assertEqual(len({r["snapshot_url"] for r in rows}), 2)

    def test_repeated_id_with_conflicting_position_or_image_is_rejected(self):
        contradictions = [
            self.feature(coordinates=[-39.2, 175.48055]),
            self.feature(image="latest/a-different-camera.jpg"),
        ]
        for conflicting in contradictions:
            with self.subTest(feature=conflicting):
                with self.assertRaisesRegex(ValueError, "Contradictory duplicate GeoNet camera ID"):
                    self.rows([self.feature()], [conflicting])

    def test_only_the_reviewed_image_origin_can_be_enabled(self):
        for image in ("https://images.example.org/latest.jpg", "//images.example.org/latest.jpg",
                      "https://user:password@images.geonet.org.nz/latest.jpg"):
            with self.subTest(image=image):
                with self.assertRaisesRegex(ValueError, "outside the reviewed host"):
                    self.rows([self.feature(image=image)])

    def test_explicit_nzdt_and_nzst_offsets_preserve_utc_and_day_boundaries(self):
        cases = {
            " 3:30 pm (NZDT) 14 Nov 2026": "2026-11-14T02:30:00Z",
            "3:30 pm (NZST) 14 Jul 2026": "2026-07-14T03:30:00Z",
            "12:00 am (NZDT) 1 Jan 2026": "2025-12-31T11:00:00Z",
            "12:00 pm (NZST) 14 Jul 2026": "2026-07-14T00:00:00Z",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(C.geonet_timestamp(raw), expected)

    def test_invalid_local_timestamps_do_not_invent_an_observation_time(self):
        invalid = [None, "", "offline", "3:30 pm (UTC) 14 Nov 2026", "0:30 pm (NZDT) 14 Nov 2026",
                   "13:30 pm (NZDT) 14 Nov 2026", "3:60 pm (NZDT) 14 Nov 2026",
                   "3:30 pm (NZDT) 29 Feb 2025", "3:30 pm (NZDT) 14 Xxx 2026"]
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertIsNone(C.geonet_timestamp(raw))
        row = self.rows([self.feature(timestamp="offline")])[0]
        self.assertIsNone(row["image_observed_at"])
        self.assertEqual(row["provider_image_timestamp"], "offline")

    def test_timestamp_survives_builder_and_serialized_viewer_without_live_promotion(self):
        raw = self.rows([self.feature()])[0]
        raw["health"] = {"status": "live_confirmed", "manifest_ok": True,
                         "segment_ok": True, "advancing": True, "checked_at": self.receipt["observed_at"]}
        policy = {
            "source": self.source,
            "media_hosts": {"images.geonet.org.nz"},
            "page_hosts": ["www.geonet.org.nz"],
            "formats": ["snapshot"],
            "countries": ["NZ"],
            "force_coordinate_role": "station_location",
        }
        with patch.dict(B.PROVIDER_POLICIES, {"geonet_volcano": policy}):
            built = B.normalize_world_item(raw, self.receipt["observed_at"])
        self.assertEqual(built["provider_image_timestamp"], " 3:30 pm (NZDT) 14 Nov 2026")
        projected = B.viewer_catalog({"schema_version": 2, "sources": [self.source], "items": [built]})
        rendered_payload = json.loads(json.dumps(projected))
        row = rendered_payload["items"][0]
        self.assertEqual(row["image_observed_at"], "2026-11-14T02:30:00Z")
        self.assertEqual(row["format"], "snapshot")
        self.assertEqual(row["health"]["status"], "unverified")
        self.assertFalse(row.get("stream_url"))
        self.assertEqual(row["minimum_refresh_seconds"], 600)
        self.assertEqual(row["coordinate_role"], "station_location")


if __name__ == "__main__":
    unittest.main()
