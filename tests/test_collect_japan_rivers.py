"""Offline tests for scripts/collect_japan_rivers.py on small trimmed fixtures (no network)."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "collect_japan_rivers"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_japan_rivers", ROOT / "scripts" / "collect_japan_rivers.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402
STAMP = "2026-11-14T14:30:00Z"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def cameras():
    cams, receipts = [], {}
    for area in ("104", "1201", "1101"):
        cams += M.parse_area_list(text(f"scam_{area}.json"), area)
        receipts[area] = json.loads(text(f"scam_{area}.json.receipt.json"))
    return cams, receipts


def normalize(item, policy):
    """Run one record through the real builder with the given policy injected."""
    provider = item["provider"]
    saved = B.PROVIDER_POLICIES.get(provider)
    policy = copy.deepcopy(policy)
    policy["media_hosts"] = set(policy["media_hosts"])
    B.PROVIDER_POLICIES[provider] = policy
    try:
        return B.normalize_world_item(item, STAMP)
    finally:
        if saved is None:
            B.PROVIDER_POLICIES.pop(provider, None)
        else:
            B.PROVIDER_POLICIES[provider] = saved


class OwnershipTest(unittest.TestCase):
    def test_owner_code_rule(self):
        self.assertTrue(M.is_national(20737))       # 札幌開発建設部
        self.assertTrue(M.is_national(22806))       # 遠賀川河川事務所
        for code in (257, 5121, 7170, 10753, 19602, 701368, 1201222, None, "20737", True):
            self.assertFalse(M.is_national(code), code)
        self.assertEqual([M.owner_class(c) for c in (21279, 513, 5121, 11777, 701368, 1201222)],
                         ["state", "prefecture", "prefecture", "prefecture", "municipality", "municipality"])

    def test_owner_names_that_read_local(self):
        for name in ("北海道", "長野県建設部河川課", "大分県土木建築部河川課", "加古川土木事務所", "南会津郡南会津町", "岩手県",
                     "久留米県土整備事務所", "富山土木センター", "西臼杵支庁", "水資源機構　高山ダム管理所", "七尾市"):
            self.assertTrue(M.owner_conflict(name), name)
        for name in ("札幌開発建設部", "宇都宮国道事務所", "京都国道事務所", "北海道開発局", "蓮ダム管理所", "利根川上流河川事務所", None):
            self.assertFalse(M.owner_conflict(name), name)


class RiverTest(unittest.TestCase):
    def setUp(self):
        self.cams, self.receipts = cameras()
        self.cache = M.load_cache(FIX / "master_cache.jsonl")
        self.items, self.reasons, self.names = M.river_items(self.cams, self.receipts, self.cache)
        self.by_id = {x["provider_id"]: x for x in self.items}

    def test_list_parsing_turns_lon_lat_around(self):
        cam = next(c for c in self.cams if c["id"] == 100081001)
        self.assertEqual((cam["lat"], cam["lng"], cam["own_cd"], cam["sys_id"]), (43.01095, 141.3526472, 20737, 1))

    def test_state_cameras_become_snapshots(self):
        simple, cctv = self.by_id["100081001"], self.by_id["220737001"]
        self.assertEqual((simple["format"], simple["snapshot_url"]),
                         ("snapshot", "https://cam.river.go.jp/cam/now/100081001.jpg"))
        self.assertEqual((cctv["format"], cctv["snapshot_url"]),
                         ("snapshot", "https://cam.river.go.jp/cam/now/cctv_010006_11C03686.jpg"))  # master currProvUrl
        self.assertEqual(cctv["owner_name"], "札幌開発建設部")
        for item in (simple, cctv):
            self.assertEqual(item["minimum_refresh_seconds"], 600)
            # The PDL credit names each camera's page through the source template the viewer fills in.
            self.assertEqual(M.RECORD_NOTICE.replace("{official_page}", item["official_page"]),
                             "出典：国土交通省 川の防災情報ホームページ（" + item["official_page"] + "）を加工して作成")

    def test_others_stay_pages_with_their_reason(self):
        expected = {"220737058": "lookup_missing", "100257001": "third_party_owner", "221279046": "paused",
                    "11201222001": "third_party_owner", "302817010": "third_party_owner"}
        for pid, reason in expected.items():
            item = self.by_id[pid]
            self.assertEqual((item["format"], item["snapshot_url"], item["rights_status"]),
                             ("official_page", None, "official_page_only"), pid)
            self.assertEqual(item["page_only_reason"], reason, pid)
        self.assertEqual(self.by_id["100257001"]["owner_name"], "北海道")  # code 257 = the prefecture
        self.assertEqual(self.reasons["viewable"], 2)

    def test_cached_404_and_owner_mismatch(self):
        cam = next(c for c in self.cams if c["id"] == 220737058)
        self.assertEqual(M.image_for(cam, {"status": 404}, None), (None, "lookup_not_found"))
        entry = copy.deepcopy(self.cache[220737001])
        entry["master"]["obsInfo"]["ownCd"] = 5121
        self.assertEqual(M.image_for(cam, entry, None), (None, "master_owner_not_state"))
        entry["master"]["obsInfo"].update(ownCd=20737, ownName="長野県建設部河川課")
        self.assertEqual(M.image_for(cam, entry, None), (None, "owner_name_reads_local"))
        entry["master"]["obsInfo"].update(ownName="札幌開発建設部", currProvUrl="https://example.org/x.jpg")
        self.assertEqual(M.image_for(cam, entry, None), (None, "no_image_url_in_master"))

    def test_camera_pages_and_ids_match_the_package_records(self):
        self.assertEqual(self.by_id["100081001"]["official_page"],
                         "https://www.river.go.jp/kawabou/pc/tm?zm=15&clat=43.01095&clon=141.3526472&itmkndCd=200"
                         "&scamId=100081001&ownCd=20737&sysCamId=81001&ext=1")
        self.assertEqual(self.by_id["220737001"]["official_page"],
                         "https://www.river.go.jp/kawabou/pc/tm?zm=15&clat=43.3325&clon=141.689441667&itmkndCd=100"
                         "&scamId=220737001&ownCd=20737&sysCamId=20737001&ext=1")
        self.assertEqual(self.by_id["11201222001"]["id"], "japan_mlit_rivers:11201222001")
        self.assertEqual(self.by_id["221279046"]["region"], "千葉県")
        package = [dict(x, official_page=x["official_page"]) for x in self.items]
        self.assertEqual(M.compare_with_package(self.items, package)["package_ids_missing_now_count"], 0)

    def test_records_pass_the_builder(self):
        policy = M.river_policy()
        for item in self.items:
            out = normalize(item, policy)
            self.assertEqual((out["format"], out["snapshot_url"]), (item["format"], item["snapshot_url"]))
            self.assertEqual(out["coordinate_role"], "camera_location")

    def test_lookup_plan_and_cache_resume(self):
        main, extra = M.lookup_plan(self.cams)
        self.assertEqual(main, [220737001, 220737058])  # every State CCTV camera in service, nothing else
        self.assertIn(100081001, extra)  # the owner's simple camera: owner name and image-name derivation
        self.assertTrue({100257001, 11201222001, 302817010} <= set(extra))  # one per third-party owner
        self.assertIn(221279046, extra)  # owner 21279 has only this paused camera here: sampled for its name
        self.assertFalse(set(main) & set(extra))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.jsonl"
            path.write_text(json.dumps({"id": 1, "status": 404}) + "\n" + json.dumps({"id": 1, "status": 200}) + "\n",
                            encoding="utf-8")
            self.assertEqual(M.load_cache(path)[1]["status"], 200)  # the last answer wins

    def test_policy(self):
        policy = M.river_policy()
        self.assertEqual(policy["formats"], ["snapshot", "official_page"])
        self.assertTrue(set(policy["media_hosts"]) <= set(policy["source"]["allowed_hosts"]))
        self.assertEqual(policy["source"]["minimum_refresh_seconds"], 600)
        self.assertIn("出典：国土交通省 川の防災情報ホームページ", policy["source"]["attribution"])
        self.assertEqual(policy["source"]["review_status"], "reviewed_for_snapshot_and_reference_use")


class KantoNoteTest(unittest.TestCase):
    def test_tone_upstream_records_get_the_emergency_note_ids_unchanged(self):
        doc = json.loads(text("mlit_kanto_cctv_round1.json"))
        items, noted = M.kanto_with_tonejo_note(doc)
        self.assertEqual(noted, 1)
        self.assertEqual([x["id"] for x in items], [x["id"] for x in doc["items"]])
        tonejo, other = items
        self.assertIn("映像は非常時等に停止・変更する場合があります", tonejo["provider_notice"])
        self.assertTrue(tonejo["provider_notice"].startswith(doc["items"][0]["provider_notice"]))
        self.assertEqual(other, doc["items"][1])  # the Kita-shuto road office is not concerned
        again, _ = M.kanto_with_tonejo_note({"items": items})
        self.assertEqual(again[0]["provider_notice"].count("非常時"), 1)


class PortalTest(unittest.TestCase):
    def setUp(self):
        self.listed = M.mlit_listed_links(text("LIVEcamera.html"))
        self.stations = M.parse_amedas(text("amedastable.json"))
        ok = {"ok": True, "checked_at": STAMP}
        self.probes = {"aomori": {**ok, "final_url": "https://www.koutsu-aomori.com/Road/livecamera.html"},
                       "ishikawa": {**ok, "final_url": "https://douro.pref.ishikawa.lg.jp/"},
                       "nagoya_city": {"ok": False, "reason": "HTTP 403"}}

    def test_portals_at_jma_stations_only_when_the_https_page_answers(self):
        items, left_out = M.portal_items(self.listed, self.stations, self.probes, STAMP)
        by_id = {x["provider_id"]: x for x in items}
        self.assertEqual(sorted(by_id), ["aomori", "ishikawa"])
        aomori = by_id["aomori"]
        self.assertEqual((aomori["lat"], aomori["lng"]), (round(40 + 49.3 / 60, 5), round(140 + 46.1 / 60, 5)))
        self.assertEqual((aomori["coordinate_role"], aomori["format"]), ("approximate", "official_page"))
        self.assertIn("31312", aomori["coordinate_source"])
        reasons = {x["provider_id"]: x["reason"] for x in left_out}
        self.assertIn("HTTP 403", reasons["nagoya_city"])
        self.assertIn("not checked", reasons["nagano"])  # not on MLIT's page, own page not probed here
        self.assertIn("no longer on MLIT", reasons["gifu"])  # not in the trimmed MLIT page
        policy = M.portal_policy({"www.koutsu-aomori.com", "douro.pref.ishikawa.lg.jp"})
        for item in items:
            self.assertEqual(normalize(item, policy)["official_page"], item["official_page"])

    def test_unreachable_robots_is_not_called_a_disallow(self):
        probes = {"gifu": {"ok": False, "url": "https://douro.pref.gifu.lg.jp/",
                           "reason": "robots.txt disallows https://douro.pref.gifu.lg.jp/"},
                  "x": {"ok": False, "url": "https://a.example.jp/p", "reason": "robots.txt disallows https://a.example.jp/p"}}
        out = M.explain_probes(probes, [{"url": "https://a.example.jp/robots.txt", "status": 200}])
        self.assertTrue(out["gifu"]["reason"].startswith("robots.txt unreachable over HTTPS"))
        self.assertTrue(out["x"]["reason"].startswith("robots.txt disallows"))  # a real rule stays a disallow

    def test_station_name_must_match(self):
        stations = dict(self.stations)
        stations["31312"] = (40.8, 140.7, "八戸")
        with self.assertRaisesRegex(ValueError, "not 青森"):
            M.portal_items(self.listed, stations, self.probes, STAMP)
        self.assertEqual(self.stations["60216"][2], "大津")  # Shiga's Otsu, not Hokkaido's (20631)


class HeldAndNexcoTest(unittest.TestCase):
    def test_nexco_route_page_has_names_but_no_coordinates(self):
        info = M.parse_driveplaza(text("driveplaza_route.html"))
        self.assertEqual((info["cameras"], info["coordinates_found"]), (3, 0))
        self.assertIn("IC", info["examples"][0])

    def test_held_fragments_never_replace_an_integrated_policy(self):
        existing = json.loads((ROOT / "scripts" / "webcam_source_policies.json").read_text(encoding="utf-8"))
        held = M.held_policies({"cameras": 3, "coordinates_found": 0, "route_pages": 41, "page": "x.html"})
        self.assertIn("jcg_mics_livecamera", held)
        self.assertIn("41 route pages", held["nexco_east_driveplaza"]["held_reason"])
        for pid, entry in held.items():
            self.assertEqual(entry["status"], "held")
            self.assertTrue(entry["held_reason"] and entry["held_until"] and entry["source"]["id"] == pid)
            self.assertNotEqual(existing.get(pid, {}).get("status", "held"), None, pid)
        self.assertNotIn(M.SOURCE, held)
        self.assertNotIn(M.PORTALS_SOURCE, held)


class BuildTest(unittest.TestCase):
    def test_offline_build_writes_the_superseding_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            lists = out / "raw" / M.SOURCE / "lists"
            lists.mkdir(parents=True)
            for area in ("104", "1201", "1101"):
                shutil.copy(FIX / f"scam_{area}.json", lists / f"{area}.json")
                shutil.copy(FIX / f"scam_{area}.json.receipt.json", lists / f"{area}.json.receipt.json")
            shutil.copy(FIX / "master_cache.jsonl", out / "raw" / M.SOURCE / "master_cache.jsonl")
            shutil.copy(FIX / "mlit_kanto_cctv_round1.json", out / "mlit_kanto_cctv.json")
            report = M.build(out, package=None)
            rivers = json.loads((out / "japan_mlit_rivers.json").read_text(encoding="utf-8"))
            self.assertEqual((rivers["supersedes"], [s["id"] for s in rivers["sources"]]),
                             (["japan_mlit_rivers"], ["japan_mlit_rivers"]))
            self.assertEqual(len(rivers["items"]), 7)
            kanto = json.loads((out / "mlit_kanto_cctv_tonejo_note.json").read_text(encoding="utf-8"))
            self.assertEqual(kanto["supersedes"], ["mlit_kanto_cctv"])
            self.assertTrue((out / "policies" / "japan_mlit_rivers.json").exists())
            self.assertTrue((out / "policies" / "nexco_east_driveplaza.json").exists())
            source = report["sources"][0]
            self.assertEqual(source["records"], {"viewable": 2, "page_only": 5})


if __name__ == "__main__":
    unittest.main()
