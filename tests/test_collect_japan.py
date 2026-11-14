"""Offline tests for scripts/collect_japan.py on small trimmed fixtures (no network)."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "collect_japan"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_japan", ROOT / "scripts" / "collect_japan.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402
STAMP = "2026-11-14T07:45:00Z"


def fixture(name):
    return M.text_of((FIX / name).read_bytes())


def normalize(item):
    """Run one record through the real builder with this collector's policy injected."""
    provider = item["provider"]
    saved = B.PROVIDER_POLICIES.get(provider)
    policy = copy.deepcopy(M.POLICIES[provider])
    policy["media_hosts"] = set(policy["media_hosts"])
    B.PROVIDER_POLICIES[provider] = policy
    try:
        return B.normalize_world_item(item, STAMP)
    finally:
        if saved is None:
            B.PROVIDER_POLICIES.pop(provider, None)
        else:
            B.PROVIDER_POLICIES[provider] = saved


class JmaTest(unittest.TestCase):
    def setUp(self):
        self.index = M.parse_jma_index(fixture("jma_index.html"))
        self.positions = M.parse_jma_positions(fixture("jma_camicon.geojson"))
        self.page = M.parse_jma_camera_page(fixture("jma_camera_page.html"))

    def test_index_regions_and_positions_from_the_official_map(self):
        self.assertEqual([vc for vc, _, _ in self.index], ["10401", "10402", "20201", "20301"])
        self.assertEqual(self.index[2][2], "東北地方")
        lat, lng, _ = self.positions["10401"]
        self.assertEqual((lat, lng), (43.638, 144.465))  # GeoJSON lon,lat order turned around

    def test_newest_dated_frame_is_the_snapshot_and_is_marked_dated(self):
        self.assertEqual(self.page["dir"], "104_82002710")
        self.assertEqual(self.page["frames"][-1], "20261114164001")
        items, left_out = M.jma_items(self.index, self.positions, {"10401": self.page}, STAMP)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["id"], "jma_volcano_cameras:10401")
        self.assertEqual(item["snapshot_url"],
                         "https://www.data.jma.go.jp/vois/data/obs/camera/104_82002710/20261114164001.jpg")
        self.assertEqual(item["image_observed_at"], "2026-11-14T07:40:01Z")  # JST -> UTC
        self.assertTrue(item["requires_catalog_refresh"])
        self.assertIn("出典：気象庁ホームページ", item["provider_notice"])
        self.assertIn("VC=10401", item["provider_notice"])
        reasons = {x["provider_id"]: x["reason"] for x in left_out}
        self.assertIn("10402", reasons)  # page not fetched / no frame: never invented
        self.assertIn("20301", reasons)  # no position on the official map

    def test_stopped_camera_is_left_out(self):
        page = M.parse_jma_camera_page(fixture("jma_camera_page_stopped.html"))
        items, left_out = M.jma_items(self.index[:1], self.positions, {"10401": page}, STAMP)
        self.assertEqual(items, [])
        self.assertEqual(left_out[0]["provider_id"], "10401")

    def test_positions_outside_japan_or_swapped_axes_fail(self):
        bad = json.loads(fixture("jma_camicon.geojson"))
        bad["features"][0]["geometry"]["coordinates"].reverse()
        with self.assertRaisesRegex(ValueError, "outside Japan"):
            M.parse_jma_positions(json.dumps(bad))

    def test_record_passes_the_builder(self):
        items, _ = M.jma_items(self.index, self.positions, {"10401": self.page}, STAMP)
        out = normalize(M.as_camera_pages(items)[0])
        self.assertEqual(out["format"], "official_page")
        self.assertEqual(out["rights_status"], "official_page_only")
        self.assertEqual(out["official_page"], "https://www.data.jma.go.jp/vois/data/obs/volcam/volcam.php?VC=10401")
        self.assertEqual(out["coordinate_role"], "camera_location")


class KantoTest(unittest.TestCase):
    def test_tonejo_dms_variants_and_viewer_image_choice(self):
        items, left_out = M.tonejo_items(fixture("tonejo_cameradb.json"), STAMP)
        self.assertEqual(left_out, [])
        by_id = {x["provider_id"]: x for x in items}
        cam1 = by_id["tonejo-cam1"]  # 36°15'53" 139°11'52" = river.go.jp 八斗島 position
        self.assertAlmostEqual(cam1["lat"], 36.264722, places=5)
        self.assertAlmostEqual(cam1["lng"], 139.197778, places=5)
        cam3 = by_id["tonejo-cam3"]  # seconds given as '35.74' with fraction '0'
        self.assertAlmostEqual(cam3["lat"], 36 + 8 / 60 + 35.74 / 3600, places=6)
        self.assertEqual(by_id["tonejo-cam26"]["snapshot_url"],
                         "https://www.ktr.mlit.go.jp/tonejo/cctv/cameraimage/cam26_640.jpg")  # url[0] when url[2] empty
        self.assertTrue(cam1["official_page"].endswith("camview.htm?stname=cam1"))
        self.assertIn("出典：関東地方整備局ウェブサイト", cam1["provider_notice"])

    def test_kitasyuto_kml_https_media_shared_sites_and_duplicates(self):
        items, left_out = M.kitasyuto_items(fixture("kitasyuto.kml"), STAMP)
        self.assertEqual(left_out, [])
        by_id = {x["provider_id"]: x for x in items}
        self.assertEqual(sorted(by_id), ["C01754", "C01755", "C01770", "C05012", "C05013"])  # C05012 listed twice
        single = by_id["C01770"]  # tab between <img and src in the official KML
        self.assertEqual(single["snapshot_url"], "https://www.ktr.mlit.go.jp/river/cctv/C01770.jpg")
        self.assertEqual(single["coordinate_role"], "camera_location")
        self.assertEqual((single["lat"], single["lng"]), (35.80338, 139.62092))
        self.assertEqual(by_id["C01754"]["coordinate_role"], "station_location")
        self.assertEqual(by_id["C01754"]["direction"], "上り")
        self.assertTrue(by_id["C01754"]["official_page"].startswith("https://www.ktr.mlit.go.jp/kitasyuto/public/CAM_"))

    def test_records_pass_the_builder(self):
        items, _ = M.kitasyuto_items(fixture("kitasyuto.kml"), STAMP)
        tonejo, _ = M.tonejo_items(fixture("tonejo_cameradb.json"), STAMP)
        for item in items + tonejo:
            self.assertEqual(normalize(item)["snapshot_url"], item["snapshot_url"])

    def test_directory_counting_uses_main_content_only(self):
        page = ('<ul id="nav"><a href="/kasumi/kasumi00999.html">nav</a></ul><div id="main_content">'
                '<a href="/kasumi/kasumi00832.html">1</a><a href="/kasumi/kasumi00831.html">2</a>'
                '<a href="/kasumi/kasumi00001.html">self</a></div><li class="related_info">'
                '<a href="/kasumi/kasumi00777.html">x</a>')
        pattern = dict((k, p) for k, _, _, p in M.KANTO_UNPLACED)["kasumi"]
        self.assertEqual(M.count_listed(page, pattern), ["kasumi00831", "kasumi00832"])
        self.assertIsNone(M.count_listed(page, None))


class PolicyTest(unittest.TestCase):
    def test_policies_and_held_fragments(self):
        existing = json.loads((ROOT / "scripts" / "webcam_source_policies.json").read_text(encoding="utf-8"))
        for pid, policy in M.POLICIES.items():
            self.assertEqual(policy["source"]["id"], pid)
            self.assertIn("出典", policy["source"]["attribution"])
            if pid == "jma_volcano_cameras":  # dated frames expire: camera pages only
                self.assertEqual((policy["formats"], policy["media_hosts"]), (["official_page"], []))
            else:
                self.assertEqual(policy["source"]["review_status"], "reviewed_for_snapshot_and_reference_use")
                self.assertTrue(policy["media_hosts"] and set(policy["media_hosts"]) <= set(policy["source"]["allowed_hosts"]))
            # Merged into the repository registry exactly as the collector writes it.
            self.assertEqual(existing.get(pid), policy)
        held = dict(M.HELD)
        held.update(M.held("mlit_kyushu_road_cameras", "n", "https://www.qsr.mlit.go.jp/", "r", "u", []))
        for pid, policy in held.items():
            self.assertEqual(policy["status"], "held")
            self.assertTrue(policy["held_reason"] and policy["held_until"])
            self.assertNotEqual(existing.get(pid, {}).get("status", "held"), None,
                                "a held fragment must never replace an existing integrated policy")


if __name__ == "__main__":
    unittest.main()


class JmaPagesTest(unittest.TestCase):
    def test_jma_cameras_are_listed_as_their_pages_not_dated_frames(self):
        item = {"id": "jma_volcano_cameras:1", "format": "snapshot", "rights_status": "official_public_feed",
                "snapshot_url": "https://www.data.jma.go.jp/vois/data/obs/camera/1/20261114164001.jpg",
                "official_page": "https://www.data.jma.go.jp/vois/data/obs/volcam/volcam.php?VC=1",
                "requires_catalog_refresh": True, "image_observed_at": "2026-11-14T07:40:01Z"}
        [page] = M.as_camera_pages([item])
        self.assertEqual((page["format"], page["rights_status"], page["snapshot_url"]), ("official_page", "official_page_only", None))
        self.assertNotIn("requires_catalog_refresh", page)
        self.assertEqual(page["official_page"], item["official_page"])
