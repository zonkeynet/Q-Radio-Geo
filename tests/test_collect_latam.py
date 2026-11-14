"""Offline tests for scripts/collect_latam.py on small saved fixtures (no network)."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("collect_latam", ROOT / "scripts" / "collect_latam.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
import build_webcams as B  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "collect_latam"
OBSERVED = "2026-11-14T08:31:00Z"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def normalized(items, provider):
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


class EsoTest(unittest.TestCase):
    def setUp(self):
        self.paranal = M.eso_map_point(text("eso_travel_paranal.html"), "Very+Large+Telescope")
        self.armazones = M.eso_map_point(text("eso_travel_elt.html"), "Cerro+Armazones")
        self.items, self.skipped = M.parse_eso(text("eso_webcams.html"), self.paranal, self.armazones, OBSERVED)
        self.by_id = {i["provider_id"]: i for i in self.items}

    def test_site_positions_from_eso_pages(self):
        self.assertEqual(self.paranal, (-24.627308, -70.403996))
        self.assertEqual(self.armazones, (-24.534631, -70.19577))

    def test_views_kept_and_skipped(self):
        self.assertEqual(sorted(self.by_id), [
            "archive_webcams.armazonespanosouth.public.pano_PV_960x", "archives.static.allsky.latest.preset_101",
            "archives.static.pano.latest.POI.preset_1", "archives.static.pano.latest.POI.preset_3",
            "archives.static.pano.latest.POI.preset_7", "archives.static.pano.latest.pano_PV_960x"])
        reasons = dict(self.skipped)
        self.assertIn("not operational", reasons["Views from the ELT (West camera)"])
        self.assertIn("Views from ALMA", reasons)
        self.assertIn("View from the Headquarters", reasons)

    def test_record_fields(self):
        pano = self.by_id["archives.static.pano.latest.pano_PV_960x"]
        self.assertEqual(pano["snapshot_url"], "https://www.eso.org/public/archives/static/pano/latest/pano_PV_960x.jpg")
        self.assertEqual((pano["lat"], pano["coordinate_role"]), (-24.627308, "associated_feature"))
        self.assertEqual(pano["image_timestamp_source"], "http_last_modified")
        k0 = self.by_id["archives.static.pano.latest.POI.preset_3"]
        self.assertEqual(k0["name"], "ESO Paranal (VLT) — K0 station")
        self.assertEqual(self.by_id["archives.static.pano.latest.POI.preset_7"]["name"], "ESO Paranal (VLT) — view 7")
        south = self.by_id["archive_webcams.armazonespanosouth.public.pano_PV_960x"]
        self.assertEqual((south["coordinate_role"], south["name"]),
                         ("approximate", "ESO Cerro Armazones (ELT) — South camera, 360° panorama"))
        out = normalized(self.items, "eso_chile_webcams")
        self.assertEqual(len(out), len(self.items))
        self.assertFalse(B.media_page_records(out))

    def test_no_position_no_record(self):
        items, skipped = M.parse_eso(text("eso_webcams.html"), self.paranal, None, OBSERVED)
        self.assertTrue(all(i["provider_id"].startswith("archives.static") for i in items))
        self.assertIn("no ESO-published position for the site", dict(skipped).values())


class PraiaGrandeTest(unittest.TestCase):
    def test_links_to_the_city_map(self):
        rows = json.loads(text("praiagrande_api.json"))
        items, excluded = M.parse_praia_grande(rows, OBSERVED)
        self.assertEqual(excluded, {"childrens_venue": 1, "no_coordinates": 1})
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["official_page"], "https://cameras.praiagrande.sp.gov.br/aovivo/")
        self.assertNotIn("(Briefcam)", first["name"])
        self.assertEqual((first["format"], first["rights_status"]), ("official_page", "official_page_only"))
        self.assertEqual(len(normalized(items, "brazil_praia_grande_aovivo")), 2)


class HeldTest(unittest.TestCase):
    def test_el_salvador_camera_is_a_youtube_embed(self):
        kind, url = M.snet_camera(text("snet_home.html"))
        self.assertEqual(kind, "youtube")
        self.assertTrue(url.startswith("https://www.youtube.com/embed/"))

    def test_held_entries_complete(self):
        for sid, entry in M.HELD.items():
            self.assertEqual(entry["status"], "held")
            self.assertEqual(entry["source"]["id"], sid)
            self.assertTrue(entry["held_reason"] and entry["held_until"] and entry["evidence"])


if __name__ == "__main__":
    unittest.main()
