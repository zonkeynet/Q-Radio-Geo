"""Offline tests for scripts/collect_us_federal.py on small saved fixtures (no network)."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_us_federal", ROOT / "scripts" / "collect_us_federal.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "collect_us_federal"
OBSERVED = "2026-11-14T08:31:00Z"
NOW = dt.datetime(2026, 11, 14, 8, 31, tzinfo=dt.timezone.utc)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def normalized(items, provider):
    """Run items through the real builder with this collector's policy, as validate_input.py does."""
    policy = dict(M.policies()[provider])
    policy["media_hosts"] = set(policy["media_hosts"])
    saved = B.PROVIDER_POLICIES.get(provider)
    B.PROVIDER_POLICIES[provider] = policy
    B.EXTRA_CATALOG_PROVIDERS.add(provider)
    try:
        return [B.normalize_extra_item(dict(i), OBSERVED) for i in items]
    finally:
        if saved is None:
            B.PROVIDER_POLICIES.pop(provider, None)
            B.EXTRA_CATALOG_PROVIDERS.discard(provider)
        else:
            B.PROVIDER_POLICIES[provider] = saved


class NimsTest(unittest.TestCase):
    def setUp(self):
        self.items, self.excluded = M.parse_nims(load("nims_cameras.json"), OBSERVED, NOW)
        self.by_id = {i["provider_id"]: i for i in self.items}

    def test_image_url_from_newest_time(self):
        cam = self.by_id["IL_Lick_Creek_near_Woodside"]
        self.assertEqual(cam["snapshot_url"], "https://usgs-nims-images.s3.amazonaws.com/720/IL_Lick_Creek_near_Woodside/"
                                              "IL_Lick_Creek_near_Woodside___2026-11-14T07-45-01Z.jpg")
        self.assertTrue(cam["requires_catalog_refresh"])
        self.assertEqual(cam["image_observed_at"], "2026-11-14T07:45:01Z")
        self.assertEqual(cam["official_page"], "https://apps.usgs.gov/hivis/camera/IL_Lick_Creek_near_Woodside")
        self.assertEqual((cam["country"], cam["region"]), ("US", "IL"))

    def test_partner_hidden_test_and_stale_cameras_left_out(self):
        self.assertNotIn("WI_KD1_FIELD", self.by_id)          # "Discovery Farms Partner Monitoring"
        self.assertNotIn("AC_JOHN", self.by_id)               # hidden
        self.assertNotIn("GU_Adelup_Point_CAMERA_1", self.by_id)  # last image 2024
        self.assertFalse(any("test" in k.lower() for k in self.by_id))
        for reason in ("partner_or_non_usgs_operator", "hidden", "image_older_than_30_days"):
            self.assertIn(reason, self.excluded)
        shown = [dict(r, hideCam=False) for r in load("nims_cameras.json") if "test" in r["camId"].lower()]
        self.assertEqual(M.parse_nims(shown, OBSERVED, NOW), ([], {"test_camera": 1}))

    def test_territory_country_and_safe_id(self):
        self.assertEqual(self.by_id["PR_Isla_Verde_Camera_1"]["country"], "PR")
        row = dict(next(r for r in load("nims_cameras.json") if r["camId"] == "IL_Lick_Creek_near_Woodside"))
        row["camId"] = "NM_EAGLE_LAKE_(SOUTH_12)"
        row["smallDir"] = "https://usgs-nims-images.s3.amazonaws.com/720/NM_EAGLE_LAKE_(SOUTH_12)/"
        (item,), _ = M.parse_nims([row], OBSERVED, NOW)
        self.assertEqual(item["provider_id"], "NM_EAGLE_LAKE__SOUTH_12_")
        self.assertEqual(item["snapshot_url"], "https://usgs-nims-images.s3.amazonaws.com/720/NM_EAGLE_LAKE_%28SOUTH_12%29/"
                                               "NM_EAGLE_LAKE_%28SOUTH_12%29___2026-11-14T07-45-01Z.jpg")
        for item in self.items:
            self.assertRegex(item["provider_id"], r"^[A-Za-z0-9][A-Za-z0-9:_.-]*$")
            self.assertNotIn("(", item["snapshot_url"])

    def test_builder_accepts_records(self):
        out = normalized(self.items, "usgs_hivis_nims")
        self.assertEqual(len(out), len(self.items))
        self.assertTrue(all(x["rights_status"] == "official_public_feed" and x["format"] == "snapshot" for x in out))


class VolcViewTest(unittest.TestCase):
    def setUp(self):
        self.items, self.excluded = M.parse_volcview(load("volcview_webcams.json"), OBSERVED, NOW)
        self.by_id = {i["provider_id"]: i for i in self.items}

    def test_usgs_hosted_cameras_are_snapshots(self):
        dome = self.by_id["msh-dome"]
        self.assertEqual(dome["format"], "snapshot")
        self.assertTrue(dome["snapshot_url"].startswith("https://volcview.wr.usgs.gov/"))
        self.assertEqual(dome["official_page"], "https://volcview.wr.usgs.gov/ashcam-gui/webcam.html?webcam=msh-dome")
        hvo = self.by_id["kilauea-kw-cam"]
        self.assertEqual(hvo["official_page"], "https://volcanoes.usgs.gov/observatories/hvo/cams/panorama.php?cam=KWcam")
        self.assertEqual(hvo["region"], "HI")

    def test_owner_not_stated_is_a_link(self):
        akutan = self.by_id["akutan_aksd"]
        self.assertEqual((akutan["format"], akutan["rights_status"]), ("official_page", "official_page_only"))
        self.assertIsNone(akutan["snapshot_url"])
        self.assertEqual(akutan["region"], "AK")

    def test_faa_nps_third_party_and_placeholders_left_out(self):
        for code in ("anchorage-S", "rainier-mora-east", "shasta-snowcrest", "kilauea-b1-cam", "korovin_kowe", "akunIsland-N"):
            self.assertNotIn(code, self.by_id)
        for reason in ("faa_weathercam_left_to_livetraf_faa_links", "nps_camera_left_to_nps_source",
                       "third_party_camera", "no_coordinates_or_bad_id", "test_or_placeholder"):
            self.assertIn(reason, self.excluded)

    def test_builder_accepts_records(self):
        out = normalized(self.items, "usgs_volcview_ashcam")
        self.assertEqual({x["format"] for x in out}, {"snapshot", "official_page"})
        self.assertFalse(B.media_page_records(out))


class NdbcTest(unittest.TestCase):
    def test_snapshot_and_page_records(self):
        items, _ = M.parse_ndbc(load("buoycams.json"), OBSERVED)
        by_id = {i["provider_id"]: i for i in items}
        self.assertEqual(by_id["41004"]["snapshot_url"], "https://www.ndbc.noaa.gov/buoycam.php?station=41004")
        self.assertEqual(by_id["41004"]["image_observed_at"], "2026-11-14T07:10:00Z")
        self.assertEqual(by_id["41013"]["format"], "official_page")
        self.assertEqual(by_id["41013"]["official_page"], "https://www.ndbc.noaa.gov/station_page.php?station=41013")
        self.assertTrue(all(i["country"] == "US" and i["coordinate_role"] == "station_location" for i in items))
        out = normalized(items, "noaa_ndbc_buoycams")
        self.assertEqual(len(out), len(items))


class GlerlTest(unittest.TestCase):
    def test_station_page_positions(self):
        apn = M.parse_glerl_station(text("glerl_station_apn.html"))
        self.assertEqual((apn["lat"], apn["lng"], apn["ndbc_id"]), (45.059722, -83.423611, "APNM4"))
        chi = M.parse_glerl_station(text("glerl_station_chi.html"))
        self.assertIsNone(chi["lat"])
        self.assertEqual(chi["ndbc_id"], "CHII2")
        srl = M.parse_glerl_station(text("glerl_recon_srl.html"))
        self.assertEqual((srl["lat"], srl["lng"]), (45.7732, -84.1367))

    def test_cameras_with_official_positions_only(self):
        pages = {"https://www.glerl.noaa.gov/metdata/apn/": text("glerl_station_apn.html"),
                 "https://www.glerl.noaa.gov/metdata/chi/": text("glerl_station_chi.html"),
                 "https://www.glerl.noaa.gov/res/recon/station-srl.html": text("glerl_recon_srl.html")}
        items, excluded = M.parse_glerl(text("glerl_metdata.html"), pages, OBSERVED, NOW)
        by_id = {i["provider_id"]: i for i in items}
        self.assertEqual(len([k for k in by_id if k.startswith("apn")]), 5)
        self.assertEqual(by_id["chi01"]["coordinate_source"], M.GLERL_INDEX + " (station map on the page)")
        self.assertEqual((by_id["chi01"]["lat"], by_id["chi01"]["region"]), (41.916516, "IL"))
        self.assertEqual(by_id["srl01"]["official_page"], "https://www.glerl.noaa.gov/res/recon/station-srl.html")
        self.assertEqual(by_id["apn01"]["snapshot_url"], "https://www.glerl.noaa.gov/metdata/cams/apn01.jpg")
        self.assertNotIn("mkg01", by_id)        # 2013 image
        self.assertNotIn("mkg08", by_id)        # no station position in the fixture
        self.assertEqual(excluded, {"image_older_than_30_days": 6, "no_station_coordinates": 1})
        self.assertEqual(len(normalized(items, "noaa_glerl_metcams")), len(items))


class PolicyTest(unittest.TestCase):
    def test_policies_are_reviewed_and_hosts_consistent(self):
        for pid, policy in M.policies().items():
            source = policy["source"]
            self.assertEqual(source["id"], pid)
            self.assertEqual(source["reviewed_at"], "2026-11-14")
            self.assertTrue(source["terms_url"].startswith("https://") and source["attribution"])
            self.assertEqual(sorted(source["allowed_hosts"]), sorted(policy["media_hosts"]))
            self.assertIn("snapshot", policy["formats"])


if __name__ == "__main__":
    unittest.main()
