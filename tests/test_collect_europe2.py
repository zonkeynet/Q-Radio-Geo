"""Offline tests for scripts/collect_europe2.py: saved, trimmed fixtures only, no network."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_europe2", ROOT / "scripts" / "collect_europe2.py")
E = importlib.util.module_from_spec(SPEC)
sys.modules["collect_europe2"] = E
SPEC.loader.exec_module(E)
import build_webcams as B  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "collect_europe2"
STAMP = "2026-11-14T14:10:00Z"


def fixture(name):
    return (FIX / name).read_bytes()


def stage(out, source, name, body, url="https://example.invalid/list", observed_at=STAMP):
    """Lay a fixture out as a saved raw response with its receipt, as webcam_fetch.save_raw does."""
    folder = E.raw_dir(out, source)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(body)
    receipt = {"file": name, "url": url, "final_url": url, "status": 200, "observed_at": observed_at, "bytes": len(body),
               "sha256": hashlib.sha256(body).hexdigest(), "content_type": None, "user_agent": "test"}
    (folder / (name + ".receipt.json")).write_text(json.dumps(receipt), encoding="utf-8")


def normalize(result):
    """Every item through the real builder with the fragment's policy, as validate_input.py does."""
    provider = result["policy"]["source"]["id"]
    policy = dict(result["policy"], media_hosts=set(result["policy"]["media_hosts"]))
    saved = B.PROVIDER_POLICIES.get(provider)
    B.PROVIDER_POLICIES[provider] = policy
    B.EXTRA_CATALOG_PROVIDERS.add(provider)
    try:
        rules = B.load_exclusions()["rules"]
        items = [B.normalize_extra_item(B.repair_raw(x, rules), STAMP, []) for x in result["items"]]
        kept, removed = B.apply_exclusions(items, rules)
        assert not B.media_page_records(kept), B.media_page_records(kept)
        return kept, removed
    finally:
        if saved is None:
            B.PROVIDER_POLICIES.pop(provider, None)
        else:
            B.PROVIDER_POLICIES[provider] = saved


class ParserTests(unittest.TestCase):
    def test_ooe_layer_skips_asfinag(self):
        self.assertTrue(E.ooe_layer_url(fixture("ooe_webmap.json")).endswith(
            "/596e2315fad741a7b83c81f58c1fdb88/rest/services/AON/aon_Layer/MapServer/0"))

    def test_ooe_released_views_join(self):
        rows, unjoined = E.ooe_rows(fixture("ooe_webcam_list.json"), fixture("ooe_layer0_query.json"))
        self.assertEqual(unjoined, [614])
        self.assertEqual(sorted((r["station"], r["camera"]) for r in rows), [(32, 1), (32, 2), (32, 3), (32, 4), (73, 1), (73, 2)])
        gaflenz = next(r for r in rows if r["station"] == 73)
        self.assertAlmostEqual(gaflenz["lat"], 47.9025, places=3)
        bad = json.loads(fixture("ooe_layer0_query.json"))
        bad["spatialReference"] = {"wkid": 31255}
        with self.assertRaises(ValueError):
            E.ooe_rows(fixture("ooe_webcam_list.json"), json.dumps(bad))

    def test_oulu_city_cameras_fresh_presets(self):
        rows, stale = E.oulu_rows(fixture("oulu_cameras.json"), STAMP)
        self.assertEqual({r["camera"] for r in rows}, {"CT2757057035"})
        self.assertEqual([r["preset"] for r in rows], ["P3471244775", "P2238719322"])
        self.assertEqual(len(stale), 3)
        self.assertTrue(all(r["image"].startswith("https://d2gakb5f3pwfh0.cloudfront.net/") for r in rows))

    def test_dwd_views_and_station_table(self):
        self.assertEqual(len(E.dwd_views(fixture("dwd_webcam_dir.html"))), 9)
        st = E.dwd_stations(fixture("dwd_stations.txt"))
        self.assertEqual(st["Hohenpeißenberg"]["id"], "02290")
        self.assertEqual(st["Rostock-Warnemünde"]["id"], "04271")
        self.assertEqual(st["Ueckermünde"]["id"], "05142")  # the register's id for Warnemünde is another station
        self.assertEqual(st["Lindenberg"]["state"], "Brandenburg")

    def test_dhmz_and_wien(self):
        rows = E.parse_dhmz(fixture("dhmz_webkam.html"))
        self.assertEqual([r["key"] for r in rows], ["zggric", "split", "zav"])
        self.assertTrue(all(r["image"].startswith("https://vrijeme.hr/") and r["caption_found"] for r in rows))
        presets, licensed = E.parse_wien(fixture("wien_rathausturm.html"))
        self.assertTrue(licensed)
        self.assertEqual(presets[0]["image"], "https://www.wien.gv.at/webcam-rturm/rturm1.jpeg")
        self.assertFalse(E.parse_wien(fixture("wien_unlicensed.html"))[1])

    def test_mk_marker_join(self):
        rows, unplaced = E.mk_rows(fixture("mk_page.json"), fixture("mk_posts.json"))
        self.assertEqual([(r["post"], r["marker"]) for r in rows], [(16055, 16055), (12757, 12757)])
        self.assertEqual(rows[0]["kind"], "border_crossing")
        self.assertEqual(unplaced, ["Toll Plaza “Stobi”"])

    def test_station_tables(self):
        isd = E.isd_rows(fixture("isd_history.csv"), {"064470", "118130"})
        self.assertEqual(isd["064470"]["name"], "UCCLE")
        self.assertAlmostEqual(isd["118130"]["lat"], 48.167)
        self.assertIsNone(E.isd_place(isd, "118130", "MOCHOVCE"))
        pages = E.rmi_pages(fixture("rmi_webcams.html"))
        self.assertEqual({p["station"] for p in pages}, {"uccle", "wideumont", "mont-rigi"})
        self.assertEqual({c["camera"] for c in E.shmu_cameras(fixture("shmu_webkamery.html"))}, {"hdcam01", "hdcam12", "hdcam04"})

    def test_tirol_station_positions(self):
        cams = E.parse_tirol_livebilder(fixture("tirol_livebilder.html"))
        self.assertEqual([c["station_slug"] for c in cams], ["innsbruck-nordkette", "oeav-patscherkofel", "schwaz-koglmoos", "vomp-raststaette-a12"])
        vomp = E.tirol_station(fixture("tirol_station_vomp-raststaette-a12.html"))
        self.assertAlmostEqual(vomp["lat"], 47 + 20 / 60 + 55.59 / 3600, places=6)
        self.assertAlmostEqual(vomp["lng"], 11 + 41 / 60 + 31.30 / 3600, places=6)
        self.assertIsNone(E.tirol_station(fixture("tirol_station_oeav-patscherkofel.html"))["lat"])

    def test_smaller_lists(self):
        self.assertEqual([r["code"] for r in E.omirl_rows(fixture("omirl_webcam.json"))], ["AIROL", "PANES"])
        lat, lng = E.smartbay_point(fixture("smartbay_dataset.html"))
        self.assertAlmostEqual(lat, 53.2273, places=3)
        self.assertAlmostEqual(lng, -9.2663, places=3)
        self.assertEqual(E.md_pages(fixture("md_camere_web.html")),
                         ["bumbata", "giurgiulesti-intrare", "leuseni-iesire", "otaci-iesire", "sculeni-intrare"])


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ooe_items_pass_the_builder(self):
        stage(self.out, "ooe_land_webcams", "webcam_list.json", fixture("ooe_webcam_list.json"))
        stage(self.out, "ooe_land_webcams", "layer0_query.json", fixture("ooe_layer0_query.json"))
        result = E.build_ooe_land_webcams(self.out)
        kept, removed = normalize(result)
        self.assertEqual((len(kept), removed), (6, []))
        ids = {x["id"]: x for x in kept}
        x = ids["ooe_land_webcams:32-KAM2"]
        self.assertEqual(x["snapshot_url"], "https://www.land-oberoesterreich.gv.at/webcam/a/32/KAM2")
        self.assertEqual(x["official_page"], "https://www.land-oberoesterreich.gv.at/192995.htm?stationsadresse=32")
        self.assertEqual(x["attribution"], "Quelle: Land Oberösterreich")
        # An OSM row giving the same image (with a cache-buster) as its page has the same link key.
        self.assertEqual(B.link_key("https://www.land-oberoesterreich.gv.at/webcam/a/32/KAM2?1676214323"),
                         B.link_key(x["snapshot_url"]))

    def test_oulu_and_dwd_items(self):
        stage(self.out, "oulu_kelikamerat", "cameras.json", fixture("oulu_cameras.json"))
        kept, _ = normalize(E.build_oulu_kelikamerat(self.out))
        self.assertEqual({x["format"] for x in kept}, {"snapshot"})
        self.assertEqual(len(kept), 2)
        stage(self.out, "dwd_webcams", "webcam_dir.html", fixture("dwd_webcam_dir.html"))
        stage(self.out, "dwd_webcams", "KL_Tageswerte_Beschreibung_Stationen.txt", fixture("dwd_stations.txt"))
        result = E.build_dwd_webcams(self.out)
        kept, _ = normalize(result)
        self.assertEqual(sorted(x["provider_id"] for x in kept),
                         ["Hohenpeissenberg-S", "Lindenberg-NNE", "Warnemuende-NW"])
        self.assertTrue(any("Hamburg-SO" in c for c in result["changes"]))
        self.assertTrue(str(E.policy_path(self.out, "dwd_webcams")).endswith("dwd_webcams.round2.json"))
        self.assertEqual(E.raw_dir(self.out, "dwd_webcams").name, "round2")

    def test_hand_placed_viewables_and_pages(self):
        stage(self.out, "dhmz_webcams", "webkam.html", fixture("dhmz_webkam.html"))
        stage(self.out, "wien_stadt_webcams", "webcam-rathausturm.html", fixture("wien_rathausturm.html"))
        stage(self.out, "wien_stadt_webcams", "webcam-wasserturm.html", fixture("wien_unlicensed.html"))
        for build, n in ((E.build_dhmz_webcams, 3), (E.build_wien_stadt_webcams, 1)):
            result = build(self.out)
            kept, _ = normalize(result)
            self.assertEqual(len(kept), n)
            self.assertTrue(all(x["coordinate_role"] == "approximate" and x["coordinate_source"] for x in kept))
        stage(self.out, "mk_state_roads_video_kameri", "page_video_kameri.json", fixture("mk_page.json"))
        stage(self.out, "mk_state_roads_video_kameri", "video_kamera_posts.json", fixture("mk_posts.json"))
        stage(self.out, E.REFERENCE, "isd-history.csv", fixture("isd_history.csv"))
        stage(self.out, "be_rmi_kmi_webcams", "webcams.html", fixture("rmi_webcams.html"))
        stage(self.out, "shmu_webcams", "webkamery.html", fixture("shmu_webkamery.html"))
        stage(self.out, "tirol_luft_livebilder", "livebilder.html", fixture("tirol_livebilder.html"))
        for slug in ("vomp-raststaette-a12", "oeav-patscherkofel"):
            stage(self.out, "tirol_luft_livebilder", f"station-{slug}.html", fixture(f"tirol_station_{slug}.html"))
        expected = {E.build_mk_state_roads_video_kameri: 2, E.build_be_rmi_kmi_webcams: 4, E.build_shmu_webcams: 2,
                    E.build_tirol_luft_livebilder: 1}
        for build, n in expected.items():
            result = build(self.out)
            kept, _ = normalize(result)
            self.assertEqual(len(kept), n, build.__name__)
            self.assertTrue(all(x["format"] == "official_page" and x["coordinate_source"] for x in kept))

    def test_holds(self):
        stage(self.out, "md_border_police_webcams", "camere-web.html", fixture("md_camere_web.html"))
        ro = E.build_md_border_police_webcams(self.out)["policy"]
        ua = E.build_md_border_police_webcams_ukraine_facing(self.out)["policy"]
        self.assertEqual((ro["status"], ro["pages"]), ("held", ["bumbata", "leuseni-iesire", "sculeni-intrare"]))
        self.assertEqual(ua["pages"], ["giurgiulesti-intrare", "otaci-iesire"])
        fvg = E.build_arpa_fvg_webcam_directory(self.out)
        self.assertEqual((fvg["policy"]["status"], fvg["refused_hosts"][0]["host"]), ("held", "www.meteo.fvg.it"))
        self.assertTrue(str(E.policy_path(self.out, "arpa_fvg_webcam_directory")).endswith(".round2.json"))
        plzen = E.SOURCES["plzen_city_webcams"]["build"](self.out)["policy"]
        self.assertEqual(plzen["status"], "held")
        ids = {row[0] for row in E.REGISTER_HELD}
        self.assertIn("ru_gazprom_polyana_webcams", ids)
        self.assertIn("me_mup_border_cameras", ids)
        self.assertFalse(ids & set(E.REPO_HELD))


if __name__ == "__main__":
    unittest.main()
