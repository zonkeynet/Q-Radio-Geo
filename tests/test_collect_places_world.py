"""Offline tests for scripts/collect_places_world.py (placement round) on small saved fixtures (no network)."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_places_world", ROOT / "scripts" / "collect_places_world.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402
import webcam_places as P  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "collect_places_world"
OBSERVED = "2026-11-14T14:00:00Z"
# Square stand-ins for Natural Earth: Hong Kong, Kenya, Macau (sea everywhere else).
GEO = {"features": [
    {"properties": {"ISO_A2_EH": "HK"}, "geometry": {"type": "Polygon", "coordinates": [[[113.8, 22.15], [114.4, 22.15], [114.4, 22.6], [113.8, 22.6], [113.8, 22.15]]]}},
    {"properties": {"ISO_A2_EH": "KE"}, "geometry": {"type": "Polygon", "coordinates": [[[34, -4.6], [41.9, -4.6], [41.9, 4.6], [34, 4.6], [34, -4.6]]]}},
    {"properties": {"ISO_A2_EH": "MO"}, "geometry": {"type": "Polygon", "coordinates": [[[113.52, 22.10], [113.61, 22.10], [113.61, 22.22], [113.52, 22.22], [113.52, 22.10]]]}}]}
COUNTRIES = P.Countries(GEO)
NO_RULES = []


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def normalized(item):
    provider = item["provider"]
    saved = B.PROVIDER_POLICIES.get(provider)
    policy = copy.deepcopy(M.policies()[provider])
    policy["media_hosts"] = set(policy["media_hosts"])
    B.PROVIDER_POLICIES[provider] = policy
    B.EXTRA_CATALOG_PROVIDERS.add(provider)
    try:
        return B.normalize_world_item(dict(item), OBSERVED)
    finally:
        if saved is None:
            B.PROVIDER_POLICIES.pop(provider, None)
        else:
            B.PROVIDER_POLICIES[provider] = saved


def hk_lookups():
    return M.Lookups(areas={"hongkong": json.loads(text("overpass_hongkong_subset.json"))["elements"]})


class ParserTest(unittest.TestCase):
    def test_kenya_camera_page_location_and_airstrip(self):
        page = M.parse_acea_page(text("acea_lewahouse1.html"))
        self.assertIn("Lewa House Safari Lodge", page["location"])
        self.assertIn("3.3 km from camera", page["airstrip"])
        self.assertIn("Nyambene", page["notes"])

    def test_dsat_index_areas_and_per_camera_pages(self):
        cams = M.parse_dsat_index(text("dsat_index_trimmed.html"))
        by_id = {c["cam_id"]: c for c in cams}
        self.assertEqual(by_id["122"]["area"], "澳門區")
        self.assertEqual(by_id["60"]["area"], "路氹區")
        self.assertEqual(by_id["63"]["area"], "跨海大橋")
        self.assertEqual(by_id["122"]["page"], "https://www.dsat.gov.mo/realtime_core4.aspx?lang=tc&cam_id=122")
        page = M.parse_dsat_camera(text("dsat_camera_122.html"))
        self.assertTrue(page["player"])

    def test_macau_rule_three(self):
        self.assertEqual(M.macau_feature("西灣大橋澳門方向"), "西灣大橋")
        self.assertEqual(M.macau_feature("友誼大橋近氹仔端之橋峰望氹仔方向"), "友誼大橋")
        self.assertEqual(M.macau_feature("偉龍馬路與飛機場圓形地交界"), "飛機場圓形地")  # a road meeting a roundabout
        self.assertEqual(M.macau_feature("青茂口岸-B"), "青茂口岸")
        self.assertIsNone(M.macau_feature("友誼橋大馬路(向氹仔方向)"))  # the avenue, not the bridge
        self.assertEqual(M.macau_district({"area": "路氹區", "sub_area": "路氹區", "name": "x"}), "cotai")
        self.assertEqual(M.macau_district({"area": "路氹區", "sub_area": "北安區", "name": "x"}), "taipa")
        self.assertIsNone(M.macau_district({"area": "跨海大橋", "sub_area": "跨海大橋", "name": "西灣大橋澳門方向"}))
        # street corners, plain streets and 'near X' never name a feature (never guess a corner)
        for name in ("提督馬路與高士德大馬路交界", "勞動節大馬路", "火船頭街近11號碼頭（向巴素打爾古街方向)"):
            self.assertIsNone(M.macau_feature(name), name)

    def test_nova_scotia_list_and_rules(self):
        cams = {c["id"]: c for c in M.parse_ns_list(text("ns_list_trimmed.html"))}
        self.assertEqual(cams["Bridgewater"]["detail"], "Exit 13, Hwy 103")
        self.assertEqual(M.ns_rule(cams["Bridgewater"]), ("junction", "13", "103", "Bridgewater"))
        self.assertEqual(M.ns_rule(cams["Mt Uniacke"]), ("junction", "3", "101", "Mount Uniacke"))
        self.assertEqual(M.ns_rule(cams["Amherst"]), ("place", "Amherst"))      # 'Near Exit 3': not one feature
        self.assertEqual(M.ns_rule(cams["Kingston"]), ("place", "Kingston"))    # 'Hwy 101 @ road': a corner
        self.assertEqual(M.ns_rule(cams["Pubnico"]), ("place", "Pubnico"))
        self.assertEqual(M.ns_rule(cams["Canso Causeway"]), ("feature", "Canso Causeway"))
        self.assertTrue(M.NS_FEATURES["Canso Causeway"]["check"]["allow_sea"])  # a causeway across open water
        self.assertTrue(cams["Seal Island - West"]["page"].endswith("cameradetails.asp?id=Seal%20Island%20-%20West"))

    def test_ovsicori_and_kotel_pages(self):
        cams = M.parse_ovsicori_index(text("ovsicori_index_trimmed.html"))
        self.assertEqual(len(cams), 8)
        self.assertIn("camara-crater-v-poas", {c["slug"] for c in cams})
        self.assertEqual(M.parse_kotel_live(text("kotel_live_block.txt") + " Virtual Services"),
                         ["The Western Wall", "Prayer Plaza", "Wilson's Arch"])


class PlacementTest(unittest.TestCase):
    def item(self, provider="hong_kong_observatory_weather_photos", pid="X", country="HK"):
        return M.page_record(provider, pid, "test", country, "r", "https://www.hko.gov.hk/en/wxinfo/ts/webcam/X_photo.htm",
                             OBSERVED, source_page="https://www.hko.gov.hk/en/wxinfo/ts/index_webcam.htm")

    def test_named_feature_and_place_centre_carry_their_fields(self):
        lk = hk_lookups()
        placed, why = M.apply_placement(self.item(pid="ELC"), M.HK_SPECS["ELC"], lk, COUNTRIES, NO_RULES)
        self.assertIsNone(why)
        self.assertEqual((placed["coordinate_role"], placed["coordinate_source"], placed["coordinate_source_licence"],
                          placed["identity_confirmed"]), ("named_feature", "osm:way/233262091", "ODbL 1.0", False))
        placed, why = M.apply_placement(self.item(pid="CS1"), M.HK_SPECS["CS1"], lk, COUNTRIES, NO_RULES)
        self.assertEqual((placed["coordinate_role"], placed["coordinate_uncertainty_m"]), ("place_centre", 1500))

    def test_ambiguous_names_and_sea_stay_out(self):
        lk = hk_lookups()
        placed, why = M.apply_placement(self.item(pid="GSI"), M.HK_SPECS["GSI"], lk, COUNTRIES, NO_RULES)
        self.assertIsNone(placed)
        self.assertIn("ambiguous", why)
        sea = dict(M.HK_SPECS["CS1"], check={"centre": (22.3, 114.17), "max_km": 40})
        lk.areas["hongkong"] = [dict(e, lat=22.05, lon=113.9) if e.get("type") == "node" else e for e in lk.areas["hongkong"]]
        placed, why = M.apply_placement(self.item(pid="CS1"), sea, lk, COUNTRIES, NO_RULES)
        self.assertIsNone(placed)
        self.assertIn("outside every country polygon", why)

    def test_hierarchy_falls_back_from_osm_to_ourairports(self):
        lk = M.Lookups(areas={"kenya": []}, airports={"KE-0052": (0.195157, 37.470289, "Lewa Airstrip")})
        site = next(s for s in M.KENYA_SITES if "lewahouse1" in s["folders"])
        item = M.page_record("kenya_aeroclub_webcams", "lewahouse1", "Lewa E", "KE", "Mt. Kenya",
                             "https://webcams.aeroclubea.com/MtKenya/mtkenya_LewaE.html", OBSERVED,
                             source_page="https://webcams.aeroclubea.com/")
        placed, why = M.first_placement(item, site["specs"], lk, COUNTRIES, {"centre": site["ref"][0], "max_km": site["ref"][1]})
        self.assertIsNone(why)
        self.assertEqual((placed["coordinate_source"], placed["coordinate_source_licence"], placed["coordinate_uncertainty_m"]),
                         ("ourairports:KE-0052", "Public Domain (OurAirports)", 3500))

    def test_bridge_spans_merge_into_one_feature(self):
        spans = [{"type": "way", "id": 1, "tags": {"name": "西灣大橋", "bridge": "yes"},
                  "bounds": {"minlat": 22.17, "minlon": 113.54, "maxlat": 22.18, "maxlon": 113.545}},
                 {"type": "way", "id": 2, "tags": {"name": "西灣大橋", "bridge": "yes"},
                  "bounds": {"minlat": 22.18, "minlon": 113.545, "maxlat": 22.19, "maxlon": 113.55}}]
        el, why = M.merged(spans, 3000)
        self.assertIsNone(why)
        lat, lng, extent = M.feature_point(el)
        self.assertAlmostEqual(lat, 22.18)
        self.assertGreater(extent, 1000)
        self.assertIsNotNone(M.merged(spans, 500)[1])

    def test_builder_accepts_placed_records_and_policies_have_no_forced_role(self):
        placed, _ = M.apply_placement(self.item(pid="ELC"), M.HK_SPECS["ELC"], hk_lookups(), COUNTRIES, NO_RULES)
        out = normalized(placed)
        self.assertEqual((out["coordinate_role"], out["rights_status"]), ("named_feature", "official_page_only"))
        pols = M.policies()
        self.assertFalse(any("force_coordinate_role" in p for p in pols.values()))
        self.assertIn("imamhussain.org", pols["iraq_karbala_shrine_live"]["page_hosts"])
        self.assertIn("www.mayapur.tv", pols["india_temple_live_darshan_round2"]["page_hosts"])
        self.assertTrue(all("status" not in p for p in pols.values()))


if __name__ == "__main__":
    unittest.main()
