"""Offline tests for scripts/collect_world2.py on small saved fixtures (no network)."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_world2", ROOT / "scripts" / "collect_world2.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "collect_world2"
OBSERVED = "2026-11-14T14:00:00Z"


def load(name):
    return (FIX / name).read_bytes()


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


class NoaaTest(unittest.TestCase):
    def setUp(self):
        self.sites = M.parse_gml_sites(load("gml_sites_rows.html"), ["MLO", "SPO", "BRW", "MCM", "PSA"])
        pages = {"MLO": (M.GML_PAGES["MLO"], load("gml_mlo_livecam.html")),
                 "SPO": (M.GML_PAGES["SPO"], load("gml_spo_livecamera.html")),
                 "BRW": (M.GML_PAGES["BRW"], load("gml_brw_livecamera.html"))}
        self.items, self.left = M.gml_items(pages, self.sites, {k: OBSERVED for k in pages})

    def test_site_table_positions(self):
        self.assertEqual(self.sites["MLO"][:2], (19.536, -155.576))
        self.assertEqual(self.sites["SPO"][:2], (-89.98, -24.8))
        self.assertEqual(self.sites["MCM"][:2], (-77.83, 166.6))
        self.assertEqual(self.sites["PSA"][:2], (-64.774, -64.053))

    def test_commented_cameras_skipped_and_mkcam_left_out(self):
        ids = [i["provider_id"] for i in self.items]
        self.assertEqual(ids, ["mlo:northcam", "mlo:swcam", "mlo:deckcam", "mlo:gatecam", "spo:cmdlfullsize",
                               "brw:archive", "brw:town", "brw:tower", "brw:solar_rad", "brw:albedo_rack"])
        self.assertEqual([x["provider_id"] for x in self.left], ["mlo:mkcam"])
        self.assertEqual({i["country"] for i in self.items}, {"US", "AQ"})

    def test_robots_blocked_images_are_tap_only(self):
        self.assertTrue(all(i["snapshot_url"].startswith("https://gml.noaa.gov/webdata/") for i in self.items))
        self.assertTrue(all(i["media_fetch"] == "viewer_on_tap_only" for i in self.items))
        self.assertIn("/webdata/", M.policies()["noaa_gml_observatory_webcams"]["source"]["robots_note"])
        out = normalized(self.items, "noaa_gml_observatory_webcams")
        self.assertEqual({x["rights_status"] for x in out}, {"official_public_feed"})


class GeminiTest(unittest.TestCase):
    def test_positions_and_records(self):
        sites = M.parse_gemini_sites(load("gemini_sites_excerpt.html"))
        self.assertEqual(sites["South"], (-30.24075, -70.736693))
        self.assertEqual(sites["North"], (19.823806, -155.46906))
        gn, gs = M.gemini_items(load("gemini_GN_Instrument_excerpt.html"), load("gemini_GS_Instrument_excerpt.html"),
                                load("gemini_allsky_excerpt.html"), sites, {"gn": OBSERVED, "gs": OBSERVED, "allsky": OBSERVED})
        self.assertEqual([i["provider_id"] for i in gn], ["east", "south", "west", "north", "up"])
        self.assertTrue(gn[0]["snapshot_url"].endswith("/currentstill_Hilo.png"))
        self.assertIn("East Cloud Camera", gn[0]["name"])
        # The status page's all-sky image is commented out: it comes from the All Sky Camera page only.
        self.assertEqual([i["provider_id"] for i in gs], ["northeast", "southwest", "allsky"])
        self.assertEqual(gs[2]["official_page"], M.GEMINI_GS_ALLSKY)
        self.assertEqual(len(normalized(gn, "gemini_north_webcams")), 5)
        self.assertEqual(len(normalized(gs, "gemini_south_cloud_cameras")), 3)


class CfhtTest(unittest.TestCase):
    def test_nanaao_still_with_gfdl_notice(self):
        nanaao = M.parse_cfht_nanaao(load("cfht_nanaao_excerpt.html"))
        self.assertEqual(nanaao["image_url"], "https://software.cfht.hawaii.edu/webloop/nanaao.jpg")
        self.assertTrue(nanaao["night_only"])
        self.assertIn("GNU Free Documentation License", nanaao["notice"])
        position = M.parse_cfht_position(load("cfht_manual_excerpt.html"))
        self.assertEqual(position, (19.828294, -155.471667))
        items = M.cfht_items(nanaao, M.parse_cfht_starcam(load("cfht_starcam_excerpt.html")), position,
                             {"nanaao": OBSERVED, "starcam": OBSERVED})
        self.assertEqual([i["format"] for i in items], ["snapshot", "official_page"])
        source = M.policies()["cfht_maunakea_webcams"]["source"]
        self.assertIn("GNU Free Documentation License, Version 1.3", source["provider_notice"])
        self.assertEqual(source["license_url"], "https://www.gnu.org/licenses/fdl-1.3.html")
        self.assertEqual(len(normalized(items, "cfht_maunakea_webcams")), 2)

    def test_missing_notice_refused(self):
        page = load("cfht_nanaao_excerpt.html").replace(b"GNU Free Documentation", b"Some other")
        with self.assertRaises(ValueError):
            M.parse_cfht_nanaao(page)


class KenyaTest(unittest.TestCase):
    def test_cards_matched_to_club_map(self):
        cards = M.parse_acea_index(load("aeroclub_index_excerpt.html"))
        self.assertNotIn("oldcam", [c["folder"] for c in cards])  # commented-out card
        items, left = M.acea_items(cards, M.parse_kml_points(load("aeroclub_sites_excerpt.kml")), OBSERVED)
        by_id = {i["provider_id"]: i for i in items}
        self.assertEqual(set(by_id), {"wilsoncam", "tatu2", "nanyuk1", "kanzi33", "satao"})
        self.assertEqual((by_id["wilsoncam"]["lat"], by_id["wilsoncam"]["lng"]), (-1.322499, 36.809137))
        self.assertEqual(by_id["tatu2"]["official_page"], "https://webcams.aeroclubea.com/Nairobi/nbo_tatu_west.html")
        self.assertEqual(by_id["tatu2"]["coordinate_source"], M.ACEA_KML)  # card prints an invalid 36°65'
        self.assertEqual((by_id["nanyuk1"]["lat"], by_id["nanyuk1"]["lng"]), (-0.138056, 37.073889))
        self.assertEqual(by_id["kanzi33"]["coordinate_role"], "approximate")
        self.assertEqual({x["provider_id"] for x in left}, {"lewahouse1", "nyeri1"})
        self.assertEqual(len(normalized(items, "kenya_aeroclub_webcams")), 5)


class ReunionTest(unittest.TestCase):
    def test_map_pins_joined_to_pages(self):
        items, left = M.reunion_items(M.parse_reunion_index(load("reunion_index_excerpt.html")), OBSERVED)
        self.assertEqual([i["provider_id"] for i in items], ["webcam-volcan-piton-de-la-fournaise", "webcam-plage-de-boucan-canot"])
        self.assertEqual((items[1]["lat"], items[1]["lng"]), (-21.027754, 55.225874))
        self.assertIn("82440", {x["provider_id"] for x in left})  # 4 bacs Sainte-Rose: pin without a page
        self.assertEqual(len(normalized(items, "reunion_irt_viewsurf_webcams")), 2)


class HandPlacedTest(unittest.TestCase):
    def test_positions_from_operator_pages(self):
        self.assertEqual(M.maps_embed_center(load("ambaji_contact_excerpt.html"), "Gabbar")[0], (24.338495, 72.823583))
        self.assertEqual(M.maps_embed_center(load("mahalaxmi_reach_excerpt.html"), "Mahalakshmi")[0], (18.9778, 72.8094))
        self.assertEqual(M.dalada_position(load("dalada_contact_excerpt.html")), (7.2939, 80.6386))
        self.assertEqual(M.vue_map_center(load("alkafeel_contact_excerpt.js")), (32.617298, 44.036298))
        self.assertEqual(M.vue_route(load("alkafeel_app_excerpt.js"), "live"), "/stream")
        self.assertEqual(M.maps_place(load("nwr_resort_excerpt.html"), "Okaukuejo"), (-19.178749, 15.918988))
        self.assertEqual(M.youtube_embed(load("nwr_article_excerpt.html")), "f4HkXO3513w")
        self.assertEqual(M.youtube_embed(load("ambaji_live_excerpt.html")), "P2-zdM-p9o4")
        with self.assertRaises(ValueError):
            M.maps_embed_center(load("ambaji_contact_excerpt.html"), "Somnath")

    def test_page_records_pass_the_builder(self):
        mkwc = M.item("maunakea_mkwc_other_observatory_cams", "summit-cams", "Maunakea summit webcams", 19.823806,
                      -155.46906, "US", "Hawaii", "approximate", "official_page", OBSERVED, page=M.MKWC_INDEX,
                      source_page=M.MKWC_INDEX, catalog=M.MKWC_INDEX, coordinate_source=M.GEMINI_SITES, crs="WGS84")
        self.assertEqual(normalized([mkwc], "maunakea_mkwc_other_observatory_cams")[0]["official_page"], M.MKWC_INDEX)
        usap = M.item("usap_antarctic_webcams", "palmer", "Palmer Station webcams", -64.774, -64.053, "AQ", "Antarctica",
                      "station_location", "official_page", OBSERVED, page=M.USAP_PAGES["palmer"][0],
                      source_page=M.USAP_INDEX, catalog=M.USAP_INDEX, coordinate_source=M.GML_SITES)
        self.assertEqual(len(normalized([usap], "usap_antarctic_webcams")), 1)


class PolicyTest(unittest.TestCase):
    def test_policies_and_holds(self):
        pols = M.policies()
        for sid, policy in pols.items():
            self.assertEqual(policy["source"]["id"], sid)
            self.assertTrue(policy["source"]["attribution"] and policy["source"]["evidence"])
        self.assertFalse(set(pols) & set(M.HELD))
        for sid, entry in M.HELD.items():
            self.assertEqual((entry["status"], entry["source"]["id"]), ("held", sid))
            self.assertTrue(entry["held_reason"] and entry["held_until"] and entry["evidence"])
        self.assertEqual(pols["gemini_north_webcams"]["source"]["license"], "CC-BY-4.0")
        self.assertEqual(pols["noaa_gml_observatory_webcams"]["media_hosts"], ["gml.noaa.gov"])


if __name__ == "__main__":
    unittest.main()
