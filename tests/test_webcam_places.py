"""Positions placed by QGlobe: labelled, checked, and kept out of position matching."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M
import webcam_places as P

# Two square "countries" side by side and sea around them (a stand-in for Natural Earth).
GEO = {"features": [
    {"properties": {"ISO_A2_EH": "MD"}, "geometry": {"type": "Polygon", "coordinates": [[[26, 45], [30, 45], [30, 49], [26, 49], [26, 45]]]}},
    {"properties": {"ISO_A2_EH": "UA"}, "geometry": {"type": "Polygon", "coordinates": [[[30, 45], [35, 45], [35, 49], [30, 49], [30, 45]]]}}]}


def border_page(**changes):
    item = {"provider": "osm_webcams", "provider_id": "node-1-aaaaaaaaaaaa", "id": "osm_webcams:node-1-aaaaaaaaaaaa",
            "name": "Leova", "lat": 0.0, "lng": 0.0, "country": "MD", "format": "official_page",
            "rights_status": "official_page_only", "official_page": "https://www.example.md/camere-web",
            "source_page": "https://www.openstreetmap.org/node/1"}
    item.update(changes)
    return item


class PlaceTest(unittest.TestCase):
    def setUp(self):
        self.countries = P.Countries(GEO)

    def test_a_placed_record_carries_its_source_licence_and_uncertainty(self):
        item = P.place(border_page(), role="named_feature", lat=46.48, lng=28.25, source="osm:node/123",
                       feature="Leova–Bumbăta border crossing (Moldovan post)", uncertainty_m=150)
        self.assertEqual((item["coordinate_role"], item["coordinate_source_licence"], item["identity_confirmed"]),
                         ("named_feature", "ODbL 1.0", False))
        self.assertEqual(P.place(border_page(), role="place_centre", lat=1, lng=1, source="wikidata:Q42", feature="x",
                                 uncertainty_m=3000)["coordinate_source_licence"], "CC0 1.0")
        with self.assertRaises(ValueError):
            P.place(border_page(), role="camera_location", lat=1, lng=1, source="osm:node/1", feature="x", uncertainty_m=10)

    def test_checks_country_sea_distance_and_exclusions(self):
        ok = P.place(border_page(), role="named_feature", lat=46.48, lng=28.25, source="osm:node/1", feature="post", uncertainty_m=100)
        self.assertEqual(P.check(ok, self.countries, centre=(46.48, 28.24), max_km=5), [])
        other_side = dict(ok, lat=46.48, lng=30.5)
        self.assertIn("Natural Earth country UA, source country MD", P.check(other_side, self.countries))
        sea = dict(ok, lat=44.0, lng=28.0)
        self.assertTrue(P.check(sea, self.countries))
        self.assertEqual(P.check(sea, self.countries, allow_sea=True, expected_country="MD"), [])
        self.assertTrue(any("km from the named place" in p for p in P.check(ok, self.countries, centre=(48.0, 28.0), max_km=10)))
        crimea = dict(ok, lat=44.6, lng=33.52, country="UA")
        self.assertTrue(any("ua-martial-law" in p for p in P.check(crimea, P.Countries({"features": []}), allow_sea=True)))


class BuilderTest(unittest.TestCase):
    def placed(self):
        return P.place(border_page(), role="named_feature", lat=46.48, lng=28.25, source="osm:node/123",
                       feature="Leova border crossing", uncertainty_m=150)

    def test_the_builder_needs_every_placement_field(self):
        item = M.normalize_extra_item(self.placed(), "now")
        self.assertEqual(item["coordinate_role"], "named_feature")
        for missing in ("coordinate_source", "coordinate_feature", "coordinate_uncertainty_m"):
            raw = self.placed()
            raw.pop(missing)
            with self.assertRaises(ValueError):
                M.normalize_extra_item(raw, "now")
        with self.assertRaises(ValueError):
            M.normalize_extra_item(dict(self.placed(), identity_confirmed=True), "now")

    def test_placed_records_never_join_position_matching_or_the_duplicate_rule(self):
        item = M.normalize_extra_item(self.placed(), "now")
        with tempfile.TemporaryDirectory() as folder:
            db = sqlite3.connect(Path(folder) / "osm.sqlite")
            db.execute("CREATE TABLE surveillance_nodes(osm_node_id,lat,lon,operator,name,direction)")
            db.execute("INSERT INTO surveillance_nodes VALUES(1,46.48,28.25,'x','y','N')")
            self.assertEqual(M.candidate_matches(db, item), [])
            db.close()
        official = {"id": "border:1", "provider": "border", "lat": 46.48, "lng": 28.25, "format": "official_page",
                    "official_page": item["official_page"], "name": "Leova", "source_page": None}
        official.update({f: None for f in ("stream_url", "snapshot_url", *M.REFERENCE_FIELDS)})
        community = dict(item, id="osm_webcams:node-2-aaaaaaaaaaaa")
        kept, log = M.drop_duplicates([official, community], 100)
        self.assertEqual(log, [], "a placed position proves nothing about which camera it is")


if __name__ == "__main__":
    unittest.main()
