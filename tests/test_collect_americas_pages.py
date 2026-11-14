"""Offline tests for scripts/collect_americas_pages.py on small saved fixtures (no network)."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_americas_pages", ROOT / "scripts" / "collect_americas_pages.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "collect_americas_pages"
OBSERVED = "2026-11-14T08:31:00Z"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def normalized(items, provider):
    policy = dict(M.policies()[provider])
    policy["media_hosts"] = set(policy["media_hosts"])
    B.PROVIDER_POLICIES[provider] = policy
    B.EXTRA_CATALOG_PROVIDERS.add(provider)
    try:
        return [B.normalize_extra_item(dict(i), OBSERVED) for i in items]
    finally:
        B.PROVIDER_POLICIES.pop(provider, None)
        B.EXTRA_CATALOG_PROVIDERS.discard(provider)


class NcdotTest(unittest.TestCase):
    def test_active_cameras_link_drivenc(self):
        items, excluded = M.parse_ncdot(load("ncdot_cameras.json"), OBSERVED)
        self.assertEqual(excluded, {"not_active": 1})
        self.assertEqual([i["provider_id"] for i in items], ["5135", "5136"])
        self.assertTrue(all(i["official_page"] == "https://www.drivenc.gov/cctv" and i["snapshot_url"] is None for i in items))
        self.assertEqual(items[0]["road"], "I-485")
        out = normalized(items, "drivenc_ncdot")
        self.assertEqual({x["rights_status"] for x in out}, {"official_page_only"})

    def test_incomplete_list_is_refused(self):
        with self.assertRaises(ValueError):
            M.parse_ncdot({"features": [], "exceededTransferLimit": True}, OBSERVED)
        with self.assertRaises(ValueError):
            M.parse_ncdot({"error": {"code": 400}}, OBSERVED)


class LincolnTest(unittest.TestCase):
    def test_city_viewer_pages(self):
        items, _ = M.parse_lincoln(load("lincoln_cameras.json"), OBSERVED)
        self.assertEqual(items[0]["official_page"], "https://ticcamvw02.lincoln.ne.gov/video.html?1E45N")
        self.assertEqual(items[0]["name"], "1st St. & Superior St.")
        self.assertEqual(len(normalized(items, "lincoln_ne_traffic")), len(items))

    def test_vms_path_not_used(self):
        doc = load("lincoln_cameras.json")
        doc["features"][0]["attributes"]["LiveSDURL"] = doc["features"][0]["attributes"]["PhotoURL"]
        doc["features"][0]["attributes"]["LiveHDURL"] = None
        items, excluded = M.parse_lincoln(doc, OBSERVED)
        self.assertEqual(excluded, {"no_city_viewer_page": 1})
        self.assertEqual(len(items), 1)


class IdahoTest(unittest.TestCase):
    def test_gis_sites_link_511_idaho(self):
        items, _ = M.parse_idaho(load("itd_cctv.json"), OBSERVED)
        self.assertEqual(items[0]["provider_id"], "5b2bb350-cd17-4d68-af8a-578a85cf744e")
        self.assertEqual((items[0]["lat"], items[0]["lng"]), (46.732318, -117.037444))
        self.assertEqual(items[0]["official_page"], "https://511.idaho.gov/cctv")
        self.assertEqual(len(normalized(items, "idaho_511_itd")), len(items))


class HeldTest(unittest.TestCase):
    def test_held_entries_complete(self):
        self.assertIn("nyc_dot_tmc", M.HELD)
        for sid, entry in M.HELD.items():
            self.assertEqual((entry["status"], entry["source"]["id"]), ("held", sid))
            self.assertTrue(entry["held_reason"] and entry["held_until"] and entry["evidence"])


if __name__ == "__main__":
    unittest.main()
