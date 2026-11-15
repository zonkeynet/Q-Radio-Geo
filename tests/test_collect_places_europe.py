"""Offline tests for scripts/collect_places_europe.py: trimmed page fixtures and small Overpass extracts, no network."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as B  # noqa: E402
import collect_places_europe as X  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "collect_places_europe"
STAMP = "2026-11-14T14:10:00Z"

# Natural Earth stand-in: Moldova, Romania west of the Prut, Ukraine to the north/east (rectangles).
GEO = {"features": [
    {"properties": {"ISO_A2_EH": "MD"}, "geometry": {"type": "Polygon", "coordinates": [[[28.0, 45.4], [30.0, 45.4], [30.0, 48.0], [28.0, 48.0], [28.0, 45.4]]]}},
    {"properties": {"ISO_A2_EH": "RO"}, "geometry": {"type": "Polygon", "coordinates": [[[26.0, 45.4], [28.0, 45.4], [28.0, 48.0], [26.0, 48.0], [26.0, 45.4]]]}},
    {"properties": {"ISO_A2_EH": "UA"}, "geometry": {"type": "Polygon", "coordinates": [[[26.0, 48.0], [30.0, 48.0], [30.0, 49.0], [26.0, 49.0], [26.0, 48.0]]]}}]}


def fixture(name):
    return (FIX / name).read_bytes()


def stage(out, source, name, body, url="https://example.invalid/list"):
    folder = Path(out) / "raw" / source
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(body)
    receipt = {"file": name, "url": url, "final_url": url, "status": 200, "observed_at": STAMP, "bytes": len(body),
               "sha256": hashlib.sha256(body).hexdigest(), "content_type": None, "user_agent": "test"}
    (folder / (name + ".receipt.json")).write_text(json.dumps(receipt), encoding="utf-8")


def normalize(policy, items):
    """Every item through the real builder with the fragment's policy, as validate_input.py does."""
    provider = policy["source"]["id"]
    saved = B.PROVIDER_POLICIES.get(provider)
    B.PROVIDER_POLICIES[provider] = dict(policy, media_hosts=set(policy["media_hosts"]))
    B.EXTRA_CATALOG_PROVIDERS.add(provider)
    try:
        rules = B.load_exclusions()["rules"]
        kept, removed = B.apply_exclusions([B.normalize_extra_item(B.repair_raw(x, rules), STAMP, []) for x in items], rules)
        assert not B.media_page_records(kept)
        return kept, removed
    finally:
        if saved is None:
            B.PROVIDER_POLICIES.pop(provider, None)
        else:
            B.PROVIDER_POLICIES[provider] = saved


class ParserTests(unittest.TestCase):
    def test_md_table_columns_and_borders(self):
        rows = X.md_crossings(fixture("md_camere_web.html"))
        got = [(r["border"], r["md_place"], [(c["slug"], c["column"]) for c in r["cameras"]]) for r in rows]
        self.assertEqual(got, [
            ("RO", "Giurgiulești", [("giurgiulesti-intrare", "intrare"), ("giurgiulesti-iesire", "iesire")]),
            ("RO", "Leova", [("leova", "intrare"), ("bumbata", "iesire")]),
            ("UA", "Otaci", [("otaci-iesire", "iesire")]),
            ("UA", "Palanca", [("palanca-intrare", "intrare"), ("palanca-iesire", "iesire")])])

    def test_page_lists(self):
        plzen = X.plzen_cameras(fixture("plzen_webkamery.html"))
        self.assertEqual([c["camera"] for c in plzen], [8, 12, 1, 2, 3, 4, 5, 6])  # the commented-out zoo block is not read
        venues, others = X.pkl_venues(fixture("pkl_kamery_online.html"))
        self.assertEqual([v["slug"] for v in venues], ["kasprowy-wierch", "gubalowka", "jaworzyna-krynicka", "palenica", "gora-zar",
                                                       "mosorny-gron", "solina"])
        self.assertEqual((venues[0]["cameras"], [o["name"] for o in others]), (6, ["Góra Parkowa"]))
        self.assertEqual([c["slug"] for c in X.bansko_cameras(fixture("bansko_home.html"))],
                         ["bansko", "chalin", "bunderitsa", "shiligarnik", "platoto", "todorka"])
        helsinki = X.helsinki_cameras(fixture("helsinki_cameras.html"))
        self.assertEqual(len(helsinki), 6)
        self.assertEqual(helsinki[0]["label"], "South Harbour")
        streams = X.visitfinland_streams(fixture("visitfinland_headers.txt"))
        self.assertEqual([(s["headline"].split(" ")[0], s["operator"]) for s in streams],
                         [("Rovaniemi", "City of Rovaniemi"), ("Koli", "Koli Ski"), ("Levi", "Levi Ski Resort"), ("Kilpisjärvi", "Starlapland")])
        self.assertEqual(X.kiel_cameras(fixture("kiel_webcam.html")), ["Kieler Förde", "Schwedenkai", "Hafenhaus"])
        self.assertEqual([c[0] for c in X.oresund_cameras(fixture("oresund_pylonkamera.html"))], ["pyloneast", "pylonwest"])

    def test_fold(self):
        self.assertEqual(X.fold("Giurgiulești"), X.fold("Giurgiuleşti"))
        self.assertEqual(X.fold("Gubałówka"), "gubalowka")

    def test_spellings_meet_across_scripts(self):
        self.assertTrue(X.tokens_match(X.tokens('ПП "Могилів-Подільський"'), X.tokens("Moghilev-Podolsk")))
        self.assertTrue(X.tokens_match(X.tokens("КПП Россошани"), X.tokens("Rossoșanî")))
        self.assertTrue(X.tokens_match(X.tokens("Патарина Романовце"), X.tokens("Romanovce")))
        self.assertFalse(X.tokens_match(X.tokens("Удобне"), X.tokens("Leova")))


class MoldovaTests(unittest.TestCase):
    def setUp(self):
        self.countries = X.P.Countries(GEO)
        self.elements = json.loads(fixture("overpass_md.json"))["elements"]
        self.crossings = X.md_crossings(fixture("md_camere_web.html"))

    def plan(self, place):
        crossing = next(c for c in self.crossings if c["md_place"] == place)
        return X.md_options(crossing, self.crossings, self.elements, self.countries)

    def test_post_by_name_or_by_the_partner_post_across_the_border(self):
        options, match = self.plan("Giurgiulești")
        self.assertEqual((match["chosen"], options[0]["placement"]["role"]), ("osm:way/21", "named_feature"))
        options, match = self.plan("Leova")
        self.assertEqual(match["chosen"], "osm:way/11")  # the Romanian post 12 is 1.2 km away
        self.assertEqual(options[-1]["placement"]["role"], "place_centre")  # the town centre stays as the fallback

    def test_post_far_from_the_partners_named_post_is_not_used(self):
        options, match = self.plan("Otaci")
        self.assertIsNone(match["chosen"])
        self.assertEqual([o["placement"]["source"] for o in options], ["osm:node/3"])

    def test_two_candidate_posts_leave_the_village_centre(self):
        options, match = self.plan("Palanca")
        self.assertIsNone(match["chosen"])
        self.assertEqual(options[0]["placement"]["role"], "place_centre")
        self.assertGreaterEqual(options[0]["placement"]["uncertainty_m"], 4500)  # covers both posts and the border

    def test_builder_records_pass_the_real_builder(self):
        with tempfile.TemporaryDirectory() as out:
            stage(out, "md_border_police_webcams", "camere-web.html", fixture("md_camere_web.html"))
            result = X.build_md_border_police_webcams(out, {"bb": {"elements": self.elements}}, self.countries)
            items = result["outcome"].items
            self.assertEqual(sorted((x["provider_id"], x["coordinate_source"]) for x in items), [
                ("bumbata", "osm:way/11"), ("giurgiulesti-iesire", "osm:way/21"), ("giurgiulesti-intrare", "osm:way/21"),
                ("leova", "osm:way/11"), ("otaci-iesire", "osm:node/3"), ("palanca-iesire", "osm:node/4"),
                ("palanca-intrare", "osm:node/4")])
            kept, removed = normalize(result["policy"], items)
            self.assertEqual((len(kept), removed), (7, []))
            self.assertTrue(all(x["identity_confirmed"] is False and x["coordinate_source_licence"] == "ODbL 1.0" for x in kept))
            self.assertNotIn("force_coordinate_role", result["policy"])


class FeatureTests(unittest.TestCase):
    def test_one_feature_or_none(self):
        booth = [{"type": "node", "id": 1, "lat": 42.11, "lon": 21.699, "tags": {"barrier": "toll_booth", "name": "Патарина Романовце"}},
                 {"type": "node", "id": 2, "lat": 42.1101, "lon": 21.6992, "tags": {"barrier": "toll_booth", "name": "Патарина Романовце"}},
                 {"type": "node", "id": 3, "lat": 41.98, "lon": 21.64, "tags": {"barrier": "toll_booth", "name": "Патарина Миладиновци"}}]
        rows = X.find(booth, name="romanovce", tag={"barrier": "toll_booth"})
        found, n = X.one(rows)
        self.assertEqual((n, found[0]["id"] in (1, 2)), (1, True))
        self.assertEqual(X.one(X.find(booth, tag={"barrier": "toll_booth"}))[1], 2)  # two plazas: ambiguous

    def test_junction_needs_one_shared_node_near_the_landmark(self):
        def way(wid, name, pts):
            return {"type": "way", "id": wid, "tags": {"name": name}, "nodes": [p[0] for p in pts],
                    "geometry": [{"lat": p[1], "lon": p[2]} for p in pts]}
        ways = [way(1, "Folmavská", [(10, 49.72, 13.35), (11, 49.725, 13.355)]),
                way(2, "Domažlická", [(11, 49.725, 13.355), (12, 49.73, 13.36)])]
        self.assertEqual(X.junction(ways, "folmavska", ("domazlicka",), (49.726, 13.356)), (11, 49.725, 13.355))
        self.assertIsNone(X.junction(ways, "folmavska", ("domazlicka",), (49.80, 13.40)))

    def test_boundary_side(self):
        line = [{"geometry": [{"lat": 55.50, "lon": 12.80}, {"lat": 55.60, "lon": 12.82}]}]
        self.assertEqual(X.side_of_boundary(line, (55.55, 12.85)), "east")
        self.assertEqual(X.side_of_boundary(line, (55.55, 12.79)), "west")
        self.assertIsNone(X.side_of_boundary(line, (55.70, 12.85)))


if __name__ == "__main__":
    unittest.main()
