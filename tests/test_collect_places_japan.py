"""Japanese road cameras placed from their names: parsing, gazetteer lookups and the placement rules (offline)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import collect_places_japan as C  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "collect_places_japan"


def gazetteers():
    isj = C.Isj.from_zip_bytes([(FX / "isj_fixture.zip").read_bytes()])
    import json
    joints = C.Joints(json.loads((FX / "n06_joints.geojson").read_text(encoding="utf-8"))["features"])
    return {"isj": isj, "joints": joints, "osm": None}


def cam(label, prefs=("25",), office="shiga", route=None, **extra):
    return {"source": "mlit_kinki_road_cameras", "office_key": office, "label": label, "prefs": list(prefs),
            "route": route, **extra}


class ParsingTest(unittest.TestCase):
    def test_shiga_list_uses_the_label_text_and_route(self):
        office = C.office_by_key("shiga")
        rows = C.office_cameras(office, (FX / "shiga_list.html").read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["id"], "C00154")
        self.assertEqual((rows[0]["label"], rows[0]["route"]), ("逢坂3", "1"))
        self.assertIn(("C00136", "鈴鹿TN"), [(r["id"], r["label"]) for r in rows])
        self.assertTrue(all(r["page"] == office["url"] for r in rows))

    def test_fukuchiyama_labels_precede_the_image(self):
        rows = C.office_cameras(C.office_by_key("fukuchiyama"), (FX / "fukuchiyama_list.html").read_text(encoding="utf-8"))
        self.assertEqual([(r["id"], r["label"], r["route"]) for r in rows][:2],
                         [("C03485", "福知山市 夜久野町小倉", "9"), ("C04113", "福知山市 夜久野町日置", "9")])

    def test_nexco_cameras_skip_commented_out_ones(self):
        rows = C.nexco_cameras((FX / "nexco_tohoku.html").read_text(encoding="utf-8"), "tohoku")
        self.assertEqual([r["code"] for r in rows], ["TN001", "TN002", "TN005"])
        self.assertEqual((rows[0]["road"], rows[0]["section"], rows[0]["name"]), ("E4 東北道", "黒石IC ～ 浪岡IC", "浪岡IC"))
        self.assertEqual(C.section_ends(rows[1]["section"]), ["大鰐弘前IC", "黒石IC"])

    def test_labels_reduce_to_the_named_thing(self):
        self.assertEqual(C.strip_tail("春来トンネル鳥取側"), "春来トンネル")
        self.assertEqual(C.strip_tail("石部大橋北詰"), "石部大橋")
        self.assertEqual(C.strip_tail("千原1"), "千原")
        self.assertEqual(C.strip_tail("渋川伊香保IC(下)"), "渋川伊香保IC")
        self.assertEqual(C.feature_of("瀬田川大橋"), ("橋", "瀬田川大橋"))
        self.assertEqual(C.feature_of("長岡南越路スマートIC"), ("SIC", "長岡南越路"))
        self.assertIsNone(C.feature_of("手原"))
        parsed = C.parse_label("国道２号 淀川大橋", "1")
        self.assertEqual(parsed["routes"], ["1", "2"])


class GazetteerTest(unittest.TestCase):
    def setUp(self):
        self.g = gazetteers()

    def test_chome_are_grouped_and_former_town_names_found(self):
        places = self.g["isj"].find("手原", ["25"])
        self.assertEqual(len(places), 1)
        self.assertGreater(places[0]["points"], 1)
        self.assertGreaterEqual(places[0]["uncertainty_m"], 500)
        self.assertEqual(self.g["isj"].find("木之本", ["25"])[0]["name"], "木之本町木之本")
        self.assertEqual(self.g["isj"].find("夜久野町日置", ["26"], "福知山市")[0]["muni"], "福知山市")

    def test_n06_names_and_duplicates(self):
        self.assertTrue(self.g["joints"].find("浪岡IC"))
        self.assertTrue(self.g["joints"].find("和田山JCT"))
        cands = C.candidate_features("浪岡", "IC", {"prefs": ["02"]}, self.g)
        self.assertEqual(len(cands), 1)   # two N06 records of one interchange merge


class PlacementTest(unittest.TestCase):
    def setUp(self):
        self.g = gazetteers()

    def test_a_named_place_is_its_centre_and_a_feature_without_data_is_held(self):
        cams = C.resolve([cam("手原"), cam("瀬田川大橋", route="1")], self.g)
        self.assertEqual(cams[0]["_pick"]["role"], "place_centre")
        self.assertTrue(cams[0]["_pick"]["source"].startswith("mlit-isj:25208/"))
        self.assertIsNone(cams[1]["_pick"])
        self.assertIn("OpenStreetMap lookup unavailable", cams[1]["_held"])

    def test_an_interchange_is_the_official_joint(self):
        nexco = {"source": "nexco_east_driveplaza", "office_key": "tohoku", "label": "浪岡IC", "prefs": ["02"],
                 "expressway": True}
        pick = C.resolve([nexco], self.g)[0]["_pick"]
        self.assertEqual((pick["role"], pick["licence"]), ("named_feature", C.N06_LICENCE))

    def test_a_section_alone_is_never_placed(self):
        nexco = {"source": "nexco_east_driveplaza", "office_key": "tohoku", "label": "アクアブリッジ", "prefs": ["02"],
                 "expressway": True}
        self.assertIsNone(C.resolve([nexco], self.g)[0]["_pick"])

    def test_a_feature_named_after_a_place_needs_a_neighbour(self):
        alone = C.resolve([cam("木之本トンネル")], self.g)[0]
        self.assertIsNone(alone["_pick"])
        self.assertIn("not confirmed", alone["_held"])
        pair = C.resolve([cam("木之本トンネル"), cam("木之本")], self.g)
        self.assertEqual(pair[0]["_pick"]["role"], "place_centre")
        self.assertGreaterEqual(pair[0]["_pick"]["uncertainty_m"], C.NAMED_AFTER_PLACE_M)

    def test_placed_items_carry_every_placement_field(self):
        office = C.office_by_key("shiga")
        c = C.resolve([cam("手原")], self.g)[0]
        base = C.bureau_item({"id": "C03853", "label": "手原", "page": office["url"], "routes": ["1"]}, office, "2026-11-14T00:00:00Z")
        item = C.placed_item(base, c["_pick"], "2026-11-14T00:00:00Z")
        for key in ("coordinate_source", "coordinate_source_licence", "coordinate_feature", "coordinate_uncertainty_m"):
            self.assertTrue(item[key])
        self.assertIs(item["identity_confirmed"], False)
        self.assertEqual(item["snapshot_url"], "https://www.seishiga.kkr.mlit.go.jp/shiga/pic/C03853.jpg")
        self.assertIn("出典：国土交通省", item["provider_notice"])


if __name__ == "__main__":
    unittest.main()
