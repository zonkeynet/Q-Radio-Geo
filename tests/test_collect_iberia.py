"""scripts/collect_iberia.py on saved, trimmed fixtures: parsing, upgrade rules, robots wildcards and the
builder's acceptance of the output. No network: every request goes to a fake client or is never made."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
FIX = Path(__file__).with_name("fixtures") / "collect_iberia"
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M  # noqa: E402
import collect_iberia as C  # noqa: E402
import webcam_fetch as F  # noqa: E402
from snapshot_access import apply_snapshot_access_checks  # noqa: E402

STAMP = "2026-11-14T07:31:20Z"


def fixture(name):
    return (FIX / name).read_bytes()


def confirmed(provider, record_id, url, hosts):
    return {"provider": provider, "record_id": record_id, "url": url, "approved_media_hosts": hosts,
            "checked_at": "2026-11-14T07:45:29Z", "http_status": 206, "bytes_read": 4096, "signature": "JPEG",
            "jpeg_signature": True, "png_signature": False, "redirects": [], "final_url": url,
            "status": "image_signature_confirmed", "inconclusive_reason": None}


class FakeClient(C.StrictClient):
    def __init__(self, responses):
        super().__init__()
        self.responses, self.requested = responses, []

    def _wait(self, host):
        pass

    def _open(self, url, max_bytes, headers=None):
        self.requested.append(url)
        status, body = self.responses.get(url, (404, b""))
        r = {"url": url, "final_url": url, "status": status, "headers": {"Content-Type": "x"}, "body": body[:max_bytes],
             "truncated": len(body) > max_bytes, "redirects": [], "started_at": F.now(), "observed_at": F.now()}
        if url.endswith("/robots.txt") and status == 200:
            base = url[:-len("/robots.txt")]
            self.robots_text[base] = body.decode()
        return r


class RobotsTest(unittest.TestCase):
    def test_wildcard_rules_are_honoured(self):
        text = fixture("fgc_robots.txt").decode()
        base = "https://dadesobertes.fgc.cat"
        self.assertFalse(C.robots_allows(text, base + "/explore/dataset/webcams-actives-tim/download/?format=json"))
        self.assertFalse(C.robots_allows(text, base + "/api/explore/v2.1/catalog/datasets/webcams-actives-tim/exports/json"))
        self.assertTrue(C.robots_allows(text, base + "/explore/dataset/webcams-actives-tim/"))
        self.assertTrue(C.robots_allows("User-agent: *\nDisallow: /a/\nAllow: /a/b$\n", "https://h/a/b"))
        self.assertFalse(C.robots_allows("User-agent: *\nDisallow: /a/\nAllow: /a/b$\n", "https://h/a/bc"))
        self.assertTrue(C.robots_allows("User-agent: q-globe\nDisallow:\n\nUser-agent: *\nDisallow: /\n", "https://h/x"))

    def test_strict_client_never_requests_a_wildcard_disallowed_list(self):
        c = FakeClient({"https://dadesobertes.fgc.cat/robots.txt": (200, fixture("fgc_robots.txt"))})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(F.Refused):
                C.fetch_fgc_tourism_webcams(c, Path(tmp))
            self.assertEqual(c.requested, ["https://dadesobertes.fgc.cat/robots.txt"])
            note = json.loads((Path(tmp) / "fgc_tourism_webcams" / "robots_check.json").read_text())
            self.assertFalse(any(note["robots_allowed_rfc9309"].values()))


class ParseTest(unittest.TestCase):
    def test_madrid_keeps_the_official_five_digit_ids(self):
        rows = C.parse_madrid_kml(fixture("madrid_cctv.kml"))
        self.assertEqual([r["provider_id"] for r in rows][:2], ["06303", "01301"])
        self.assertTrue(rows[0]["image"].startswith("https://informo.madrid.es/cameras/Camara06303.jpg?v="))
        items, skipped = C.madrid_items(rows, STAMP, True, C.MADRID_DATASET_PAGE, "https://datos.gob.es/x")
        self.assertEqual([i["id"] for i in items], ["madrid_traffic:06303", "madrid_traffic:01301", "madrid_traffic:99999"])
        self.assertEqual([i["format"] for i in items], ["snapshot", "snapshot", "official_page"])
        self.assertEqual(len(skipped), 1)  # no Numero
        items, _ = C.madrid_items(rows, STAMP, False, C.MADRID_DATASET_PAGE, "https://datos.gob.es/x")
        self.assertEqual({i["format"] for i in items}, {"official_page"})
        self.assertTrue(all(i["reference_url"] for i in items))

    def test_calle30_builds_https_urls_and_stable_ids(self):
        self.assertEqual(C.calle30_image("www.mc30.es/xml-data/imagenes_camaras/A1.jpg", "A1.jpg"),
                         "https://mc30.es/xml-data/imagenes_camaras/A1.jpg")
        self.assertIsNone(C.calle30_image("www.mc30.es/xml-data/imagenes_camaras/A1.jpg", "B1.jpg"))
        self.assertIsNone(C.calle30_image("evil.example/xml-data/imagenes_camaras/A1.jpg", "A1.jpg"))
        self.assertEqual(C.calle30_id("M30-PK10+900C(M.ALVARO)"), "M30-PK10_900C_M.ALVARO")
        rows = C.parse_calle30_xml(fixture("calle30_camaras.xml"))
        items, skipped = C.calle30_items(rows, STAMP, None, C.CALLE30_NAP_PAGE)
        ids = [i["provider_id"] for i in items]
        self.assertEqual(sorted(ids), ["09NC39TV01", "15RR64TV01", "M30-PK10_900C_M.ALVARO"])
        self.assertEqual(sorted(s["reason"].split(" (")[0] for s in skipped), ["listed twice", "no id, image or plausible coordinates"])
        special = next(i for i in items if i["provider_id"].startswith("M30"))
        self.assertEqual(special["snapshot_url"], "https://mc30.es/xml-data/imagenes_camaras/M30-PK10+900C(M.ALVARO).jpg")

    def test_malaga_needs_an_https_image_on_the_reviewed_host(self):
        rows = C.parse_malaga_csv(fixture("malaga.csv"))
        self.assertEqual(len(rows), 3)
        items, skipped = C.malaga_items(rows, STAMP)
        self.assertEqual([i["provider_id"] for i in items], ["21611", "75066"])
        self.assertEqual([s["provider_id"] for s in skipped], ["75067"])
        self.assertTrue(items[0]["official_page"].startswith("https://movilidad.malaga.eu/") and
                        items[0]["official_page"].endswith("/index.html"))
        self.assertAlmostEqual(items[0]["lat"], 36.724, places=2)

    def test_euskadi_split_keeps_every_existing_record(self):
        cams = C.parse_euskadi_pages([("https://api.euskadi.eus/traffic/v1.0/cameras?_page=1", fixture("euskadi_page_001.json"))])
        licensed = {g["URLCAM"] for g in C.parse_jsonp(fixture("euskadi_gv.json"))}
        items, skipped = C.euskadi_items(cams, licensed, STAMP, True)
        got = {i["provider_id"]: i["format"] for i in items}
        self.assertEqual(got, {"1.1": "snapshot", "5.4": "official_page", "7.1": "official_page"})
        reasons = {s["provider_id"]: s["reason"] for s in skipped}
        self.assertIn("127 .jpg", reasons["1.126"])  # a space in the published path: not a URL
        self.assertIn("implausible", reasons["1.128"])
        self.assertTrue(reasons["2.77"].startswith("listed under bizkaia"))
        self.assertTrue(reasons["7.9"].startswith("no usable image URL"))
        bilbao = next(i for i in items if i["provider_id"] == "5.4")
        self.assertTrue(bilbao["official_page"].startswith("https://www.bilbao.eus/") and bilbao["reference_url"])
        items, _ = C.euskadi_items(cams, licensed, STAMP, False)
        self.assertEqual({i["format"] for i in items}, {"official_page"})
        with self.assertRaises(ValueError):
            page = json.loads(fixture("euskadi_page_001.json"))
            page["totalItems"] = 99
            C.parse_euskadi_pages([("u", json.dumps(page))])

    def test_bizkaia_http_rows_only_with_a_verified_rewrite(self):
        rows = C.parse_bizkaia_dump(fixture("bizkaia_dump.json"))
        items, skipped = C.bizkaia_items(rows, STAMP, True, False)
        self.assertEqual({i["provider_id"]: i["format"] for i in items}, {"2": "snapshot", "23": "official_page"})
        self.assertEqual([s["provider_id"] for s in skipped], ["9999"])
        items, _ = C.bizkaia_items(rows, STAMP, True, True)
        http_row = next(i for i in items if i["provider_id"] == "23")
        self.assertEqual(http_row["snapshot_url"], "https://www.bizkaimove.eus/camaras/cam86.jpg")
        self.assertIn("snapshot_url_note", http_row)

    def test_andorra_page_has_no_camera_coordinates(self):
        self.assertEqual(C.parse_andorra_page(fixture("andorra_page.html"))["coordinates"], [])

    def test_check_and_page_evidence(self):
        self.assertTrue(C.check_ok(confirmed("p", "p:1", "https://h/x.jpg", ["h"])))
        self.assertFalse(C.check_ok({"status": "inconclusive", "http_status": None}))
        self.assertFalse(C.check_ok(None))
        self.assertTrue(C.page_ok({"status": 200, "content_type": "text/html; charset=utf-8"}))
        self.assertFalse(C.page_ok({"status": 404, "content_type": "text/html"}))


class BuilderAcceptanceTest(unittest.TestCase):
    """The collector's items and policy fragments go through the real normalization, exactly as
    tools/validate_input.py does (fragments injected into build_webcams.PROVIDER_POLICIES)."""

    def setUp(self):
        self.saved = (copy.deepcopy(M.PROVIDER_POLICIES), set(M.EXTRA_CATALOG_PROVIDERS))

    def tearDown(self):
        M.PROVIDER_POLICIES.clear()
        M.PROVIDER_POLICIES.update(self.saved[0])
        M.EXTRA_CATALOG_PROVIDERS.clear()
        M.EXTRA_CATALOG_PROVIDERS.update(self.saved[1])

    def accept(self, pid, policy, items, event=None):
        policy = dict(policy, media_hosts=set(policy["media_hosts"]))
        M.PROVIDER_POLICIES[pid] = policy
        M.EXTRA_CATALOG_PROVIDERS.add(pid)
        out = [M.normalize_extra_item(dict(i), STAMP, []) for i in items]
        self.assertEqual(M.media_page_records(out), [])
        if event:
            audit = apply_snapshot_access_checks(out, [event], M.PROVIDER_POLICIES)
            self.assertEqual(audit["rejected_events"], [])
            self.assertEqual(audit["status_counts"], {"image_reachable": 1})
        return out

    def test_every_viewable_source_passes_the_builder(self):
        rows = C.parse_madrid_kml(fixture("madrid_cctv.kml"))
        items, _ = C.madrid_items(rows[:2], STAMP, True, C.MADRID_DATASET_PAGE, "https://datos.gob.es/es/catalogo/l01280796-trafico-camaras1")
        out = self.accept("madrid_traffic", C.madrid_policy(items, C.MADRID_DATASET_PAGE), items,
                          confirmed("madrid_traffic", items[0]["id"], items[0]["snapshot_url"], ["informo.madrid.es"]))
        self.assertEqual({o["rights_status"] for o in out}, {"official_public_feed"})

        items, _ = C.calle30_items(C.parse_calle30_xml(fixture("calle30_camaras.xml")), STAMP, None, C.CALLE30_NAP_PAGE)
        self.accept("madrid_calle30_cameras", C.calle30_policy(items, C.CALLE30_NAP_PAGE), items,
                    confirmed("madrid_calle30_cameras", items[1]["id"], items[1]["snapshot_url"], ["mc30.es"]))

        items, _ = C.malaga_items(C.parse_malaga_csv(fixture("malaga.csv")), STAMP)
        self.accept("malaga_traffic", C.malaga_policy(items), items,
                    confirmed("malaga_traffic", items[0]["id"], items[0]["snapshot_url"], ["ctraficomovilidad.malaga.eu"]))

        cams = C.parse_euskadi_pages([("https://api.euskadi.eus/traffic/v1.0/cameras?_page=1", fixture("euskadi_page_001.json"))])
        licensed = {g["URLCAM"] for g in C.parse_jsonp(fixture("euskadi_gv.json"))}
        items, _ = C.euskadi_items(cams, licensed, STAMP, True)
        out = self.accept("euskadi_traffic", C.euskadi_policy(items), items,
                          confirmed("euskadi_traffic", "euskadi_traffic:1.1", items[0]["snapshot_url"], ["www.trafikoa.eus"]))
        self.assertEqual(sorted(o["format"] for o in out), ["official_page", "official_page", "snapshot"])

        items, _ = C.bizkaia_items(C.parse_bizkaia_dump(fixture("bizkaia_dump.json")), STAMP, True, True)
        self.accept("bizkaia", C.bizkaia_policy(items), items,
                    confirmed("bizkaia", "bizkaia:23", "https://www.bizkaimove.eus/camaras/cam86.jpg", ["www.bizkaimove.eus"]))

    def test_media_outside_the_reviewed_host_is_refused(self):
        items, _ = C.malaga_items(C.parse_malaga_csv(fixture("malaga.csv")), STAMP)
        policy = C.malaga_policy(items)
        bad = dict(items[0], snapshot_url="https://example.org/TV-87.jpg")
        with self.assertRaises(ValueError):
            self.accept("malaga_traffic", policy, [bad])


class BuildTest(unittest.TestCase):
    """build() on a raw folder made of fixtures: upgrades only with a confirmed sample; held fragments."""

    def raw_folder(self, tmp):
        raw = Path(tmp) / "raw"
        files = {"madrid_traffic/trafico-camaras.kml": ("madrid_cctv.kml", C.MADRID_KML),
                 "madrid_calle30_cameras/camaras.xml": ("calle30_camaras.xml", C.CALLE30_XML),
                 "malaga_traffic/da_camarasTrafico-4326.csv": ("malaga.csv", C.MALAGA_CSV),
                 "bizkaia/camaras-trafico.json": ("bizkaia_dump.json", C.BIZKAIA_JSON),
                 "euskadi_traffic/cameras_page_001.json": ("euskadi_page_001.json", C.EUSKADI_API.format(page=1)),
                 "euskadi_traffic/camaras-trafico.json": ("euskadi_gv.json", C.EUSKADI_GV_JSON),
                 "andorra_mobilitat/totes-les-cameres.html": ("andorra_page.html", C.ANDORRA_PAGE)}
        for rel, (name, url) in files.items():
            body = fixture(name)
            F.save_raw((raw / rel).parent, Path(rel).name, {"url": url, "final_url": url, "status": 200,
                                                            "observed_at": STAMP, "body": body,
                                                            "headers": {"Content-Type": "x"}})
        return raw

    def test_build_writes_inputs_policies_and_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            parsed = C.parse_raw(self.raw_folder(tmp))
            (out / "checks").mkdir()
            targets = C.sample_targets(parsed)
            self.assertTrue(targets["madrid_calle30_cameras"][0].endswith("M30-PK10_900C_M.ALVARO"))
            self.assertEqual(targets["bizkaia"][0], "bizkaia:23")  # an http row: the rewrite is what is sampled
            for provider, (rid, url, hosts) in targets.items():
                if provider != "euskadi_traffic":  # no answer from the Basque image host
                    (out / "checks" / f"{provider}.snapshot.json").write_text(json.dumps([confirmed(provider, rid, url, hosts)]))
            report = C.build(out, parsed)
            self.assertEqual(report["euskadi_traffic"]["status"], "unchanged")
            self.assertFalse((out / "euskadi_traffic.json").exists())
            self.assertFalse((out / "policies" / "euskadi_traffic.json").exists(), "an existing policy is never held")
            for held in ("dgt_nap_cameras", "fgc_tourism_webcams", "valencia_traffic", "andorra_mobilitat"):
                frag = json.loads((out / "policies" / f"{held}.json").read_text(encoding="utf-8"))[held]
                self.assertEqual(frag["status"], "held")
                self.assertTrue(frag["held_reason"] and frag["held_until"] and frag["source"]["url"])
            madrid = json.loads((out / "madrid_traffic.json").read_text(encoding="utf-8"))
            self.assertEqual(madrid["supersedes"], ["madrid_traffic"])
            self.assertEqual(report["bizkaia"]["viewable"], 2)
            self.assertEqual(report["malaga_traffic"]["viewable"], 2)
            self.assertNotIn("supersedes", json.loads((out / "malaga_traffic.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
