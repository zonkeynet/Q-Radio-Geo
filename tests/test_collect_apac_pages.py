"""Offline tests for scripts/collect_apac_pages.py on small trimmed fixtures (no network)."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "collect_apac_pages"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_apac_pages", ROOT / "scripts" / "collect_apac_pages.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402
STAMP = "2026-11-14T07:50:00Z"


def fixture(name):
    return M.text_of((FIX / name).read_bytes())


def normalize(item):
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


class HkoTest(unittest.TestCase):
    TITLES = {"LFS": "Photo at Lau Fau Shan (looking towards the west)",
              "CCE": "Photo at Cheung Chau Sacred Heart School, looking towards the east",
              "HK2": "Photo at the Hong Kong Observatory Headquarters, looking towards the west",
              "TM2": "Photo at Tai Mo Shan (looking towards the southwest)"}

    def build(self):
        return M.hko_items(fixture("hko_index.htm"), fixture("hko_stn.htm"), fixture("hko_wxphoto_e.js"),
                           self.TITLES, STAMP)

    def test_station_list_parsing(self):
        stations = M.parse_hko_stations(fixture("hko_stn.htm"))
        name, lat, lng, is_open = stations["HKO"][0]
        self.assertEqual(name, "Hong Kong Observatory")
        self.assertAlmostEqual(lat, 22 + 18 / 60 + 7 / 3600, places=6)
        self.assertAlmostEqual(lng, 114 + 10 / 60 + 27 / 3600, places=6)
        self.assertTrue(is_open)
        self.assertFalse(stations["WCN"][0][3])  # closed station never used
        self.assertAlmostEqual(M.dms_value("22°18'"), 22.3)  # minutes-only rows exist

    def test_hko_own_camera_to_station_map(self):
        aws = M.parse_hko_aws_map(fixture("hko_wxphoto_e.js"))
        self.assertEqual(aws["HK2"], "HKO")
        self.assertEqual(aws["CCE"], "CCB")
        self.assertNotIn("IC1", aws)

    def test_placement_rules_and_left_out(self):
        items, left_out = self.build()
        by_id = {x["provider_id"]: x for x in items}
        self.assertEqual(by_id["HK2"]["station_code"], "HKO")  # via HKO's page script
        self.assertEqual(by_id["LFS"]["station_code"], "LFS")  # same code
        self.assertEqual(by_id["TM2"]["station_code"], "TMS")  # identical site name
        self.assertEqual(by_id["LFS"]["coordinate_role"], "station_location")
        self.assertEqual(by_id["CCE"]["coordinate_role"], "associated_feature")  # page names another site
        self.assertEqual([x["provider_id"] for x in left_out], ["IC1"])
        self.assertEqual(by_id["LFS"]["official_page"], "https://www.hko.gov.hk/en/wxinfo/ts/webcam/LFS_photo.htm")
        for item in items:
            self.assertIsNone(item["snapshot_url"])
            self.assertNotIn("/wxinfo/aws/", json.dumps(item))  # never the robots-disallowed image path
            out = normalize(item)
            self.assertEqual(out["rights_status"], "official_page_only")
            self.assertEqual(out["coordinate_role"], item["coordinate_role"])


class AadTest(unittest.TestCase):
    def test_station_positions_vessel_and_aquarium_left_out(self):
        stations = {"casey": fixture("aad_station_casey.html"), "mawson": fixture("aad_station_mawson.html")}
        items, left_out = M.aad_items(fixture("aad_webcams_index.html"), fixture("aad_stations_index.html"),
                                      stations, STAMP)
        by_id = {x["provider_id"]: x for x in items}
        self.assertEqual(sorted(by_id), ["casey", "mawson"])
        self.assertEqual((by_id["casey"]["lat"], by_id["casey"]["lng"]), (-66.2822, 110.5266))  # U+2212 minus
        self.assertEqual((by_id["mawson"]["lat"], by_id["mawson"]["lng"]), (-67.6027, 62.873))  # degree signs
        self.assertEqual(by_id["casey"]["name"], "Casey webcam (Australian Antarctic Division)")
        reasons = {x["provider_id"]: x["reason"] for x in left_out}
        self.assertIn("moving vessel", reasons["rsv-nuyina"])
        self.assertIn("krill", reasons)
        self.assertIn("davis", reasons)  # station page not supplied: not placed
        for item in items:
            self.assertEqual(normalize(item)["country"], "AQ")


class SaaoTest(unittest.TestCase):
    def test_existing_ids_kept_http_clips_dropped_allsky_added(self):
        items = M.saao_items(fixture("saao_live.html"), fixture("saao_sutherland.html"),
                             fixture("saao_suthweather.html"), STAMP)
        ids = [x["provider_id"] for x in items]
        self.assertEqual(ids[:4], ["lcogt", "domecam330", "domecam190", "solaris"])
        self.assertEqual(ids[4:], ["allsky-seeing-monitor", "allsky-lco"])
        by_id = {x["provider_id"]: x for x in items}
        self.assertTrue(by_id["lcogt"]["reported_clip_url"].startswith("https://"))
        self.assertNotIn("reported_clip_url", by_id["domecam330"])  # page links it over http only
        self.assertAlmostEqual(by_id["lcogt"]["lat"], -32.379444, places=5)
        self.assertAlmostEqual(by_id["lcogt"]["lng"], 20.810694, places=5)
        self.assertEqual(by_id["allsky-lco"]["official_page"], "https://suthweather.saao.ac.za/")
        for item in items:
            self.assertEqual(normalize(item)["coordinate_role"], "station_location")


class PolicyTest(unittest.TestCase):
    def test_policy_shapes(self):
        existing = json.loads((ROOT / "scripts" / "webcam_source_policies.json").read_text(encoding="utf-8"))
        for pid, policy in M.POLICIES.items():
            self.assertEqual(policy["source"]["id"], pid)
            self.assertEqual(policy["media_hosts"], [])
            self.assertEqual(policy["formats"], ["official_page"])
            self.assertEqual(policy["source"]["review_status"], "reviewed_for_external_references_only")
        # The upgrade adds the all-sky page host and is merged into the registry as written.
        self.assertIn("suthweather.saao.ac.za", M.POLICIES["south_africa_saao"]["page_hosts"])
        for pid, policy in M.POLICIES.items():
            self.assertEqual(existing.get(pid), policy, pid)
        for pid, policy in M.HELD.items():
            self.assertEqual(policy["status"], "held")
            self.assertEqual(existing.get(pid, policy).get("status"), "held", "a hold never replaces an integrated policy")
        self.assertNotIn("nsw_transport", M.HELD)


if __name__ == "__main__":
    unittest.main()
