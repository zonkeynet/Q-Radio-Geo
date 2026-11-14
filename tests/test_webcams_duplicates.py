"""Duplicates: community links already carried by an official record, and same-camera page records."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M

HIVIS = "https://apps.usgs.gov/hivis/camera/NY_Panther_Kill_at_Woodland_Valley_Road_near_Phoenicia"


def rec(provider, rid, lat, lng, fmt="official_page", **extra):
    base = {"id": f"{provider}:{rid}", "provider": provider, "name": rid, "lat": lat, "lng": lng, "format": fmt,
            "official_page": None, "source_page": None, "stream_url": None, "snapshot_url": None}
    base.update({f: None for f in M.REFERENCE_FIELDS})
    base.update(extra)
    return base


def official_gauge(lat=42.0729579, lng=-74.3356901):
    return rec("usgs_hivis_nims", "NY_Panther", lat, lng, "snapshot", official_page=HIVIS, source_page="https://apps.usgs.gov/hivis/",
               snapshot_url="https://usgs-nims-images.s3.amazonaws.com/720/NY_Panther/x.jpg")


class CommunityDuplicateTest(unittest.TestCase):
    def test_a_community_link_carried_by_a_nearby_official_record_goes(self):
        osm = rec("osm_webcams", "node-1-a", 42.0733, -74.3357, official_page=HIVIS + "/",  # ~40 m, trailing slash
                  source_page="https://www.openstreetmap.org/node/1")
        kept, log = M.drop_duplicates([official_gauge(), osm], 100)
        self.assertEqual([x["id"] for x in kept], ["usgs_hivis_nims:NY_Panther"])
        self.assertEqual((log[0]["superseded_by"], log[0]["rule"]), ("usgs_hivis_nims:NY_Panther", "community-duplicate-of-official"))
        self.assertLess(log[0]["distance_m"], 100)

    def test_uncertain_community_links_stay(self):
        far = rec("osm_webcams", "node-2-a", 42.0745, -74.3357, official_page=HIVIS)              # ~170 m
        extra = rec("osm_webcams", "node-3-a", 42.0730, -74.3357, official_page=HIVIS,
                    reference_url="https://www.example.org/our-own-view")                         # one unique link
        other = rec("osm_webcams", "node-4-a", 42.0730, -74.3357,
                    official_page="https://apps.usgs.gov/hivis/camera/NY_Other_Gauge")           # another page, same host
        wiki_near_wiki = rec("wikidata_webcams", "Q1-a", 42.0730, -74.3357, official_page=HIVIS)
        items = [official_gauge(), far, extra, other]
        kept, log = M.drop_duplicates(items, 100)
        self.assertEqual(len(kept), 4); self.assertEqual(log, [])
        kept, log = M.drop_duplicates([far, wiki_near_wiki], 100)
        self.assertEqual(log, [], "community records never supersede each other")


class SameCameraPageTest(unittest.TestCase):
    def kanto(self, name="利根川 八斗島水位"):
        return rec("mlit_kanto_cctv", "tonejo-cam1", 36.2647, 139.1978, "snapshot", name=name,
                   official_page="https://www.ktr.mlit.go.jp/tonejo/cctv/camview.htm?stname=cam1",
                   snapshot_url="https://www.ktr.mlit.go.jp/tonejo/cctv/cam1.jpg")

    def rivers(self, name="八斗島水位（伊勢崎市）", lat=36.26470, lng=139.19778):
        return rec("japan_mlit_rivers", "221259001", lat, lng, name=name,
                   official_page="https://www.river.go.jp/kawabou/pc/tm?scamId=221259001")

    def test_the_page_record_gives_way_and_its_page_stays_as_a_reference(self):
        kanto, rivers = self.kanto(), self.rivers()
        kept, log = M.drop_duplicates([kanto, rivers], 100)
        self.assertEqual([x["id"] for x in kept], [kanto["id"]])
        self.assertEqual(kept[0]["reference_url"], rivers["official_page"])
        self.assertEqual((log[0]["rule"], log[0]["superseded_by"]), ("page-duplicate-of-viewable", kanto["id"]))

    def test_a_viewable_river_record_of_the_same_camera_also_gives_way(self):
        rivers = self.rivers()
        rivers.update(format="snapshot", snapshot_url="https://cam.river.go.jp/cam/now/221259001.jpg")
        kept, log = M.drop_duplicates([self.kanto(), rivers], 100)
        self.assertEqual([x["provider"] for x in kept], ["mlit_kanto_cctv"])

    def test_cache_busters_do_not_hide_a_duplicate(self):
        img = "https://www.land-oberoesterreich.gv.at/webcam/a/32/KAM2"
        official = rec("ooe_land_webcams", "32-2", 48.3, 14.3, "snapshot", snapshot_url=img)
        osm = rec("osm_webcams", "node-9-a", 48.3002, 14.3, official_page="https://www.openstreetmap.org/node/9",
                  reference_url=img + "?1676214323")
        osm["official_page"] = None  # only the image reference, as after the media-as-page repair
        kept, log = M.drop_duplicates([official, osm], 100)
        self.assertEqual([x["id"] for x in kept], ["ooe_land_webcams:32-2"])

    def test_names_must_match_and_only_reviewed_pairs_apply(self):
        self.assertEqual(M.drop_duplicates([self.kanto(), self.rivers(name="烏川合流点")], 100)[1], [])
        surrey = rec("surrey", "1", 49.0, -122.75, name="No 99 Hwy And 8 Ave", official_page="https://www.surrey.ca/cams/1")
        drivebc = rec("drivebc", "2", 49.0, -122.75, "snapshot", name="Hwy 99 at 8 Avenue - N",
                      snapshot_url="https://images.drivebc.ca/bchighwaycam/pub/cameras/2.jpg")
        self.assertEqual(M.drop_duplicates([surrey, drivebc], 100)[1], [], "different operators' cameras stay")


class PublishedDuplicatesTest(unittest.TestCase):
    def test_superseded_records_are_gone_and_their_replacements_published(self):
        ledger_path, catalog_path = ROOT / "reports" / "webcams" / "duplicates.json", ROOT / "data" / "webcams.json"
        if not ledger_path.exists() or not catalog_path.exists():
            self.skipTest("no published catalog in this checkout")
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ids = {x["id"] for x in json.loads(catalog_path.read_text(encoding="utf-8"))["items"]}
        self.assertGreater(ledger["records_removed"], 600)
        for entry in ledger["entries"]:
            self.assertNotIn(entry["id"], ids)
            self.assertIn(entry["superseded_by"], ids)
            self.assertLessEqual(entry["distance_m"], ledger["radius_m"])


if __name__ == "__main__":
    unittest.main()
