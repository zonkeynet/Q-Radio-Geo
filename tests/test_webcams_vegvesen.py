"""Small offline fixtures for official identity, media and collection completeness."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("collect_vegvesen", Path(__file__).parents[1] / "scripts/collect_vegvesen.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
STAMP = "2026-11-13T17:09:20.213570+00:00"


def camera(camera_id="3000061_1", video=True):
    props = {"cameraId": camera_id, "description": "Fjøsangerveien", "orientationDescription": "sentrum",
             "countyNumber": 46, "stillImageUrl": f"https://kamera.atlas.vegvesen.no/api/images/{camera_id}",
             "videoEncodingStandard": "hls" if video else "", "videoServiceLevel": 1,
             "status.stillImageAvailability": "videoOrImagesAvailable"}
    if video:
        props["videoUrl"] = f"https://kamera.vegvesen.no/public/{camera_id}/manifest.m3u8"
    return {"type": "Feature", "id": "temporary-feature-id", "geometry": {"type": "Point", "coordinates": [5.339726, 60.37364]}, "properties": props}


def page(features, total=None, following=None):
    return {"type": "FeatureCollection", "features": features,
            "numberMatched": len(features) if total is None else total, "numberReturned": len(features),
            "links": [{"rel": "next", "href": following}] if following else []}


def receipt(body, index=0, url=M.CATALOG_URL):
    return {"file": M.page_name(index), "url": url, "final_url": url, "status": 200,
            "retrieved_at": STAMP, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def fixture_page(data, index=0, url=M.CATALOG_URL):
    body = json.dumps(data).encode()
    return receipt(body, index, url), data, body


class VegvesenCollectionTest(unittest.TestCase):
    def test_geojson_order_stable_official_id_and_no_health_from_provider(self):
        feature = camera()
        first = M.normalize_feature(feature, STAMP)
        feature["id"] = "new-feature-id"
        feature["properties"]["description"] = "Renamed location"
        other = M.normalize_feature(feature, STAMP)
        self.assertEqual(first["id"], "vegvesen:3000061_1")
        self.assertEqual(first["id"], other["id"])
        self.assertEqual((first["lat"], first["lng"]), (60.37364, 5.339726))
        self.assertTrue(first["provider_in_service"])
        self.assertEqual(first["health"], {"status": "unverified"})
        self.assertEqual(first["observed_at"], STAMP)
        feature["geometry"]["coordinates"].reverse()
        with self.assertRaisesRegex(ValueError, "Coordinates"):
            M.normalize_feature(feature, STAMP)

    def test_only_published_explicit_hls_is_video_and_origins_are_fixed(self):
        self.assertEqual(M.normalize_feature(camera(), STAMP)["format"], "hls")
        for feature in (camera(video=False), camera()):
            feature["properties"]["videoEncodingStandard"] = ""
            item = M.normalize_feature(feature, STAMP)
            self.assertEqual(item["format"], "snapshot")
            self.assertIsNone(item["stream_url"])
        for bad_url in ("http://kamera.vegvesen.no/a.m3u8", "https://user:pass@kamera.vegvesen.no/a.m3u8",
                        "https://kamera.vegvesen.no.evil.example/a.m3u8", "https://127.0.0.1/a.m3u8"):
            with self.subTest(url=bad_url):
                feature = camera()
                feature["properties"]["videoUrl"] = bad_url
                with self.assertRaises(ValueError):
                    M.normalize_feature(feature, STAMP)
        redirect = M.CatalogRedirect()
        req = M.request.Request(M.CATALOG_URL)
        for target in ("http://" + M.CATALOG_HOST + M.CATALOG_PATH,
                       "https://evil.example" + M.CATALOG_PATH,
                       "https://" + M.CATALOG_HOST + "/other"):
            with self.subTest(redirect=target), self.assertRaises(ValueError):
                redirect.redirect_request(req, None, 302, "Found", {}, target)

    def test_pagination_complete_missing_page_changed_total_and_duplicate_id(self):
        next_url = M.CATALOG_URL + "&startIndex=1"
        first = fixture_page(page([camera()], total=2, following=next_url))
        second = fixture_page(page([camera("3000062_1")], total=2), 1, next_url)
        self.assertEqual(len(M.normalize([first, second])["items"]), 2)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            M.normalize([first])
        damaged = copy.deepcopy(second)
        damaged[1]["numberMatched"] = 3
        with self.assertRaisesRegex(ValueError, "size changed"):
            M.normalize([first, damaged])
        duplicate = fixture_page(page([camera()], total=2), 1, next_url)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            M.normalize([first, duplicate])
        bad_count = fixture_page(page([camera()], total=2))
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            M.normalize([bad_count])

    def test_legacy_offline_receipt_hash_and_utc_time_are_preserved(self):
        entry, data, body = fixture_page(page([camera(), camera("3000062_1", video=False)]))
        entry.pop("file")  # Actual first collection uses a single legacy receipt.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / M.RAW_NAME).write_bytes(body)
            (root / M.RECEIPT_NAME).write_text(json.dumps(entry))
            output = root / "normalizzato.json"
            with mock.patch.object(M.request, "build_opener", side_effect=AssertionError("Offline must not access the network")):
                M.main(["--source-dir", str(root), "--out", str(output)])
            normalized = json.loads(output.read_text())
            self.assertEqual(len(normalized["items"]), 2)
            self.assertEqual(normalized["source_fetches"][0]["sha256"], entry["sha256"])
            self.assertTrue(all(i["observed_at"] == STAMP for i in normalized["items"]))
            (root / M.RAW_NAME).write_bytes(body + b" ")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                M.load_pages(root)
            (root / M.RAW_NAME).write_bytes(body)
            entry["retrieved_at"] = "2026-11-13T17:09:20"
            (root / M.RECEIPT_NAME).write_text(json.dumps(entry))
            with self.assertRaisesRegex(ValueError, "UTC"):
                M.load_pages(root)


if __name__ == "__main__":
    unittest.main()
