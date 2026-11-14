"""Offline tests for scripts/collect_italy.py: saved, trimmed fixtures only, no network."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
SPEC = importlib.util.spec_from_file_location("collect_italy", ROOT / "scripts" / "collect_italy.py")
I = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(I)
from test_collect_europe_central import normalize, stage  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "collect_italy"
ETNA = "c6c70a03-e711-4eed-9835-1d02f5a5ec58"
EOLIE = "8790a7a8-211c-4794-bcb2-41e24cd2e322"


def fixture(name):
    return (FIX / name).read_bytes()


class ParserTests(unittest.TestCase):
    def test_garr(self):
        self.assertEqual([v["name"] for v in I.parse_garr_channel(fixture("garr_channel.json"))], ["Etna", "Eolie"])
        video = I.parse_garr_video(fixture(f"garr_video_{ETNA}.json"))
        self.assertEqual((video["licence"], video["privacy"]), ("CC BY 4.0", "Public"))
        self.assertEqual(video["playlist"], f"https://garr.tv/static/streaming-playlists/hls/{ETNA}/master.m3u8")

    def test_venezia_pairs_image_and_title(self):
        rows = I.parse_venezia(fixture("venezia_webcam.html"))
        self.assertEqual(rows[0]["code"], "smarcoweb1")
        self.assertEqual(rows[0]["label"], "S.Marco Torre dell'Orologio (vista1)")
        self.assertEqual(rows[-1]["code"], "saluteweb2")

    def test_ras_markers_skip_malformed_link(self):
        body = fixture("ras_webcams.html")
        rows = I.parse_ras(body)
        self.assertEqual([r["slug"] for r in rows], ["alpe-di-siusi", "anterselva"])
        self.assertEqual(body.decode().count("detailPage:"), 3)  # the Fleres marker has a doubled path

    def test_infoviaggiando_roads(self):
        rows = I.parse_infoviaggiando(fixture("infoviaggiando_webcam.html"))
        self.assertEqual([r["road"] for r in rows], ["A23", "A28", "A28", "A28"])

    def test_small_pages(self):
        self.assertEqual([r["code"] for r in I.parse_genova(fixture("genova_node.html"))], ["calata", "corsoitalia", "f_begato"])
        self.assertEqual([r["slug"] for r in I.parse_meteotrentino(fixture("meteotrentino_index.html"))],
                         ["trento-laste", "passo-costalunga"])
        self.assertEqual(I.parse_a22(fixture("a22_webcam.html"))["images"], ["km1", "km68", "km77"])


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingv_hls(self):
        stage(self.out, "ingv_oe_tv_channels", "channel_live_videos.json", fixture("garr_channel.json"), I.GARR_CHANNEL)
        for uuid in (ETNA, EOLIE):
            stage(self.out, "ingv_oe_tv_channels", f"video_{uuid}.json", fixture(f"garr_video_{uuid}.json"))
        result = I.build_ingv_oe_tv_channels(self.out)
        self.assertEqual([x["format"] for x in result["items"]], ["hls", "hls"])
        self.assertEqual(result["policy"]["media_hosts"], ["garr.tv"])
        kept, _ = normalize(result)
        self.assertEqual(kept[0]["stream_url"], f"https://garr.tv/static/streaming-playlists/hls/{ETNA}/master.m3u8")
        self.assertEqual(kept[0]["official_page"], "https://www.ct.ingv.it/sezioniesterne/StreamingEtna.php")

    def test_ingv_skips_a_video_without_open_licence(self):
        video = json.loads(fixture(f"garr_video_{EOLIE}.json"))
        video["licence"] = {"id": 7, "label": "Attribution - Non Commercial"}
        stage(self.out, "ingv_oe_tv_channels", "channel_live_videos.json", fixture("garr_channel.json"))
        stage(self.out, "ingv_oe_tv_channels", f"video_{ETNA}.json", fixture(f"garr_video_{ETNA}.json"))
        stage(self.out, "ingv_oe_tv_channels", f"video_{EOLIE}.json", json.dumps(video).encode())
        self.assertEqual(len(I.build_ingv_oe_tv_channels(self.out)["items"]), 1)

    def test_venezia_snapshots(self):
        stage(self.out, "venezia_cpsm_webcams", "webcam-0.html", fixture("venezia_webcam.html"), I.VENEZIA_PAGE)
        result = I.build_venezia_cpsm_webcams(self.out)
        self.assertEqual(result["policy"]["source"]["minimum_refresh_seconds"], 1200)
        kept, _ = normalize(result)
        self.assertEqual({x["format"] for x in kept}, {"snapshot"})
        self.assertEqual(kept[0]["snapshot_url"], "https://www.comune.venezia.it/sites/default/files/publicCPSM2/webcam/smarcoweb1.jpg")

    def test_page_only_sources(self):
        cases = [("ras_suedtirol_webcams", "webcams.html", "ras_webcams.html", I.build_ras_suedtirol_webcams, 2),
                 ("infoviaggiando_webcams", "webcam.html", "infoviaggiando_webcam.html", I.build_infoviaggiando_webcams, 2),
                 ("genova_comune_webcams", "node-30486.html", "genova_node.html", I.build_genova_comune_webcams, 3),
                 ("meteotrentino_webcams", "webcam-index.html", "meteotrentino_index.html", I.build_meteotrentino_webcams, 2),
                 ("a22_autobrennero", "webcam.html", "a22_webcam.html", I.build_a22_autobrennero, 1)]
        for source, name, fix, build, count in cases:
            with self.subTest(source=source):
                stage(self.out, source, name, fixture(fix))
                result = build(self.out)
                kept, removed = normalize(result)
                self.assertEqual(len(kept), count, removed)
                self.assertTrue(all(x["format"] == "official_page" for x in kept))

    def test_infoviaggiando_one_record_per_road(self):
        stage(self.out, "infoviaggiando_webcams", "webcam.html", fixture("infoviaggiando_webcam.html"))
        items = I.build_infoviaggiando_webcams(self.out)["items"]
        self.assertEqual([(x["provider_id"], x["camera_count"]) for x in items], [("A23", 1), ("A28", 3)])
        self.assertEqual({x["official_page"] for x in items}, {I.INFOVIAGGIANDO_PAGE})

    def test_a22_single_record_away_from_camera_positions(self):
        stage(self.out, "a22_autobrennero", "webcam.html", fixture("a22_webcam.html"))
        items = I.build_a22_autobrennero(self.out)["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["official_page"], I.A22_PAGE)
        self.assertEqual(items[0]["coordinate_role"], "associated_feature")

    def test_held_sources(self):
        stage(self.out, "arpae_camera_coastal", "cameras.json", fixture("arpae_cameras_redacted.json"))
        for road, (_, url) in I.ASTM_PAGES.items():
            stage(self.out, "astm_group_webcams", f"webcam-{road.lower()}.html", b"<html>410 Gone</html>", url, status=410)
        arpae = I.build_arpae_camera_coastal(self.out)
        self.assertIn("url null on 2 rows", arpae["policy"]["held_reason"])
        astm = I.build_astm_group_webcams(self.out)
        self.assertEqual(astm["status"], "held")
        self.assertEqual(len(astm["refused_hosts"]), 7)
        for build in (I.build_arpa_fvg_webcam_directory, I.build_arpav_webcams, I.SOURCES["aspi_webcams"]["build"]):
            with self.subTest(build=build):
                result = build(self.out)
                self.assertEqual(result["policy"]["status"], "held")
                self.assertTrue(result["policy"]["held_reason"])

    def test_arpae_fixture_has_no_device_config(self):
        self.assertNotIn(b'"config"', fixture("arpae_cameras_redacted.json"))
        self.assertNotIn(b"10.9.", fixture("arpae_cameras_redacted.json"))


if __name__ == "__main__":
    unittest.main()
