"""Offline tests for scripts/collect_europe_central.py: saved, trimmed fixtures only, no network."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_europe_central", ROOT / "scripts" / "collect_europe_central.py")
C = importlib.util.module_from_spec(SPEC)
sys.modules["collect_europe_central"] = C
SPEC.loader.exec_module(C)
import build_webcams as B  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "collect_europe_central"
STAMP = "2026-11-14T07:34:00Z"


def fixture(name):
    return (FIX / name).read_bytes()


def stage(out, source, name, body, url="https://example.invalid/list", status=200):
    """Lay a fixture out as a saved raw response with its receipt, as webcam_fetch.save_raw does."""
    folder = Path(out) / "raw" / source
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(body)
    receipt = {"file": name, "url": url, "final_url": url, "status": status, "observed_at": STAMP, "bytes": len(body),
               "sha256": hashlib.sha256(body).hexdigest(), "content_type": None, "user_agent": "test"}
    (folder / (name + ".receipt.json")).write_text(json.dumps(receipt), encoding="utf-8")


def normalize(result):
    """Run every item through the real builder with the fragment's policy, as validate_input.py does."""
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
    def test_lv95_reference_point(self):
        lat, lng = C.lv95_to_wgs84(2600000, 1200000)  # Bern, old observatory
        self.assertAlmostEqual(lat, 46.95108, places=4)
        self.assertAlmostEqual(lng, 7.43864, places=4)

    def test_chmi_rows(self):
        rows = C.parse_chmi(fixture("chmi_webcams.json"))
        self.assertEqual((len(rows), rows[0]["file"], rows[1]["file"]), (3, "cheb", "dylen"))
        self.assertTrue(all(r["branch"] for r in rows))
        self.assertIsInstance(rows[0]["lat"], float)

    def test_sitg_requires_wgs84(self):
        rows = C.parse_sitg(fixture("sitg_infomob_camera.json"))
        self.assertEqual(rows[0]["objectid"], 1)
        self.assertTrue(rows[0]["image_aller"].startswith("https://app2.ge.ch/tercameras/"))
        bad = json.loads(fixture("sitg_infomob_camera.json"))
        bad["spatialReference"] = {"wkid": 2056}
        with self.assertRaises(ValueError):
            C.parse_sitg(json.dumps(bad))

    def test_meteoswiss_rows(self):
        rows = C.parse_meteoswiss(fixture("meteoswiss_webcams.json"))
        self.assertEqual(rows[0]["station"], "CHD")
        self.assertEqual(rows[0]["owner"], "MeteoSwiss")
        self.assertAlmostEqual(rows[0]["lat"], 46.4798, places=3)
        self.assertTrue(rows[0]["image"].startswith("https://backend.roundshot.com/cams/"))
        self.assertIn("station=CHD", rows[0]["page"])

    def test_cita_skips_commented_placemarks(self):
        rows = C.parse_cita_kml(fixture("cita_cameras.kml"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["page"], "https://www.cita.lu/webcam/map/3")
        self.assertEqual(rows[0]["road"], "A6")

    def test_foto_webcam_filters(self):
        rows, skipped = C.parse_foto_webcam(fixture("foto_webcam_metadata.json"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["page"].startswith("https://www.foto-webcam.eu/webcam/") for r in rows))
        self.assertEqual(skipped, {"page_not_on_foto_webcam_eu": 1, "hidden_or_offline": 2, "country_outside_scope": 1})

    def test_landsverk_views(self):
        views = C.parse_landsverk(fixture("landsverk_vevmyndatol.html"))
        self.assertEqual(views[0], {"area": "Norðoyggjar", "link": "/default.aspx?id=447", "code": "F-40",
                                    "caption": "Viðareiðisvegurin"})
        self.assertTrue(all(v["link"] in C.LANDSVERK_PLACES for v in views))

    def test_dirce_array(self):
        rows = C.parse_dirce(fixture("dirce_index.html"))
        self.assertEqual(rows[0]["camera"], "4")
        self.assertEqual(rows[0]["road"], "A77")
        with self.assertRaises(ValueError):
            C.parse_dirce(b"<html></html>")

    def test_small_pages(self):
        self.assertEqual(C.parse_wales_roads(fixture("wales_road_cameras.html")), [("a44", "A44"), ("m4", "M4"), ("m48", "M48")])
        topr = C.parse_topr(fixture("topr_index.html"))
        self.assertEqual(topr[0]["page"], "https://new.pogoda.topr.pl/morskie-oko/")
        self.assertEqual(len(C.parse_aodos(fixture("aodos_live.html"))), 6)
        self.assertEqual(C.parse_bretten(fixture("bretten_webcams.html"))["views"], ["Mark", "Pfeif"])
        self.assertEqual(C.parse_sitemap_cams(fixture("bukovel_sitemap.xml")),
                         ["https://bukovel.com/cams/vitiag-5", "https://bukovel.com/cams/voda-club"])

    def test_robots_reading(self):
        self.assertTrue(C.robots_allow(fixture("backend.roundshot.com.robots.txt"), C.ROUNDSHOT_SAMPLES["backend.roundshot.com"]))
        self.assertFalse(C.robots_allow(fixture("storage2.roundshot.com.robots.txt"), C.ROUNDSHOT_SAMPLES["storage2.roundshot.com"]))

    def test_iri_link(self):
        self.assertEqual(C.iri("https://www.landsverk.fo/fo-fo/borgari/vevmyndatol/norðoyggjar/fugloy"),
                         "https://www.landsverk.fo/fo-fo/borgari/vevmyndatol/nor%C3%B0oyggjar/fugloy")


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_chmi_upgrade_is_viewable_and_supersedes(self):
        stage(self.out, "chmi", "webcams.json", fixture("chmi_webcams.json"), C.CHMI_LIST)
        result = C.build_chmi(self.out)
        self.assertEqual(result["supersedes"], ["chmi"])
        first = result["items"][0]
        self.assertEqual(first["id"], "chmi:cheb")
        self.assertEqual(first["snapshot_url"], "https://produkty.chmi.cz/webkamery/input_data/kam/cheb.jpg")
        self.assertEqual(first["official_page"], "https://produkty.chmi.cz/webkamery/webcamDetail.php?cam=cheb")
        kept, _ = normalize(result)
        self.assertEqual({x["format"] for x in kept}, {"snapshot"})
        self.assertEqual(kept[0]["rights_status"], "official_public_feed")

    def test_geneva_keeps_objectid_and_notice(self):
        stage(self.out, "geneva_sitg", "infomob_camera.json", fixture("sitg_infomob_camera.json"), C.SITG_QUERY)
        result = C.build_geneva_sitg(self.out)
        self.assertEqual([x["provider_id"] for x in result["items"]], ["1", "2"])
        self.assertIn("temps réel", result["policy"]["source"]["provider_notice"])
        self.assertEqual(result["policy"]["media_hosts"], ["app2.ge.ch"])
        kept, _ = normalize(result)
        self.assertEqual(len(kept), 2)

    def test_meteoswiss_page_only_when_image_host_disallows(self):
        stage(self.out, "meteoswiss_weathercams", "messnetz-webcams_en.json", fixture("meteoswiss_webcams.json"))
        stage(self.out, "meteoswiss_weathercams", "backend.roundshot.com.robots.txt", fixture("backend.roundshot.com.robots.txt"))
        stage(self.out, "meteoswiss_weathercams", "storage2.roundshot.com.robots.txt", fixture("storage2.roundshot.com.robots.txt"))
        stage(self.out, "meteoswiss_weathercams", "opendata-terms-of-use.html", fixture("meteoswiss_terms_excerpt.html"))
        result = C.build_meteoswiss_weathercams(self.out)
        self.assertEqual(result["policy"]["formats"], ["official_page"])
        self.assertEqual(result["policy"]["media_hosts"], [])
        self.assertTrue(all(x["format"] == "official_page" and x["snapshot_url"] is None for x in result["items"]))
        kept, _ = normalize(result)
        self.assertEqual(len(kept), 2)
        # With an image host that allows the path, the same layer would be viewable.
        stage(self.out, "meteoswiss_weathercams", "storage2.roundshot.com.robots.txt", b"User-agent: *\nDisallow:\n")
        self.assertTrue(C.meteoswiss_viewable(self.out)[0])

    def test_page_only_sources_normalize(self):
        cases = [("cita_luxembourg", "cameras.kml", "cita_cameras.kml", C.build_cita_luxembourg, 2),
                 ("foto_webcam_eu", "metadata.json", "foto_webcam_metadata.json", C.build_foto_webcam_eu, 2),
                 ("faroe_landsverk", "vevmyndatol.html", "landsverk_vevmyndatol.html", C.build_faroe_landsverk, 4),
                 ("dir_centre_est_webcams", "index.html", "dirce_index.html", C.build_dir_centre_est_webcams, 3),
                 ("traffic_wales_cctv", "road-cameras.html", "wales_road_cameras.html", C.build_traffic_wales_cctv, 3),
                 ("topr_pogoda_cams", "index.html", "topr_index.html", C.build_topr_pogoda_cams, 2),
                 ("attiki_odos_live", "live-streaming.html", "aodos_live.html", C.build_attiki_odos_live, 6),
                 ("bretten_webcams", "webcams.html", "bretten_webcams.html", C.build_bretten_webcams, 2),
                 ("ua_bukovel_cams", "sitemap.xml", "bukovel_sitemap.xml", C.build_ua_bukovel_cams, 2)]
        for source, name, fix, build, count in cases:
            with self.subTest(source=source):
                stage(self.out, source, name, fixture(fix))
                result = build(self.out)
                self.assertEqual(result["status"], "integrated")
                self.assertEqual(len(result["items"]), count)
                kept, removed = normalize(result)
                self.assertEqual(len(kept), count, removed)
                self.assertTrue(all(x["format"] == "official_page" and x["rights_status"] == "official_page_only" for x in kept))

    def test_landsverk_groups_views_per_page(self):
        stage(self.out, "faroe_landsverk", "vevmyndatol.html", fixture("landsverk_vevmyndatol.html"))
        items = C.build_faroe_landsverk(self.out)["items"]
        first = items[0]
        self.assertEqual(first["provider_id"], "page-447")
        self.assertEqual(first["view_count"], 2)
        self.assertEqual(first["coordinate_role"], "approximate")
        self.assertIn("%C3%B0", items[2]["official_page"])

    def test_bukovel_kept_by_ukraine_rule(self):
        stage(self.out, "ua_bukovel_cams", "sitemap.xml", fixture("bukovel_sitemap.xml"))
        kept, removed = normalize(C.build_ua_bukovel_cams(self.out))
        self.assertEqual((len(kept), removed), (2, []))

    def test_held_sources(self):
        stage(self.out, "hamburg_verkehrskameras", "items.json", fixture("hamburg_items.json"))
        for build in (C.build_arso_webcams, C.build_dwd_webcams, C.build_hamburg_verkehrskameras,
                      C.build_orleans_metropole_webcams, C.build_loire_atlantique_bridge_ferry_cams, C.build_tfl_jamcam,
                      C.build_trafikverket_cameras, C.SOURCES["promet_si_cameras"]["build"]):
            with self.subTest(build=build):
                result = build(self.out)
                self.assertEqual(result["status"], "held")
                pol = result["policy"]
                self.assertEqual(pol["status"], "held")
                self.assertTrue(pol["held_reason"] and pol["held_until"] and pol["evidence"])
                self.assertEqual(set(pol["source"]), {"id", "name", "url"})
        self.assertIn("lage", C.build_hamburg_verkehrskameras(self.out)["policy"]["held_reason"])

    def test_every_source_has_a_builder(self):
        for sid, entry in C.SOURCES.items():
            self.assertTrue(callable(entry["build"]), sid)


if __name__ == "__main__":
    unittest.main()
