#!/usr/bin/env python3
"""Placement round of 2026-11-14 for the Europe sources (family places_europe, stdlib only).

The operator lists of these sources were read in round 2 by collect_europe2.py (raw files under
webcam-inputs-2026-11/raw/<source>/); they publish no camera position. This collector places each camera at the
exact named feature in an open dataset (OSM ODbL, Wikidata CC0) or, last resort, at the centre of the named place,
through scripts/webcam_places.py, and runs the offline sanity checks (Natural Earth country, sea, distance from the
named place, exclusion rules). Records that fail a check, or whose name does not identify one feature, stay out and
are listed in the report.

  python scripts/collect_places_europe.py --out <dir> lookup   # network: Overpass + Wikidata, cached, PoliteClient
  python scripts/collect_places_europe.py --out <dir> build    # offline: inputs, policy fragments, report

Lookups are cached under <out>/raw/places/places_europe/ (webcam_places.cached_json), so a rebuild never repeats one.
"""
from __future__ import annotations

import collections
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_europe2 as E  # noqa: E402
from collect_europe_central import clean, item, text, write_json  # noqa: E402
import webcam_fetch as F  # noqa: E402
import webcam_places as P  # noqa: E402

FAMILY = "places_europe"
REVIEWED_AT = "2026-11-14"
SCRATCH_OPEN_DATA = Path(__file__).resolve().parents[2] / "open-data"
PLACED_NOTE = "The operator publishes no camera position: QGlobe placed the record at the named feature (or place)."


def cache_dir(out):
    return Path(out) / "raw" / "places" / FAMILY


# ======================================================================================
# Pure parsers of the operator pages read in round 2 (raw/<source>/...)
# ======================================================================================

MD_COLUMNS = {"video-in": ("intrare", "entry into Moldova"), "video-out": ("iesire", "exit from Moldova")}


def md_crossings(body):
    """Rows of the Border Police camera table: crossing label, the border (caption), the camera pages per column."""
    rows = []
    for table in re.findall(r"<table.*?</table>", text(body), re.S):
        cap = re.search(r"<caption[^>]*>(.*?)</caption>", table, re.S)
        caption = clean(cap.group(1)) if cap else ""
        border = "RO" if "Rom" in caption else "UA" if "Ucrain" in caption else None
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            name = re.search(r'headers="view-name-table-column(?:--\d+)?"[^>]*>(.*?)</td>', tr, re.S)
            if not name:
                continue
            label = clean(name.group(1))
            cams = []
            for col, (key, direction) in MD_COLUMNS.items():
                cell = re.search(rf'headers="view-field-{col}-table-column(?:--\d+)?"[^>]*>(.*?)</td>', tr, re.S)
                for slug in re.findall(r'about="/camere-web/([a-z0-9-]+)"', cell.group(1) if cell else ""):
                    cams.append({"slug": slug, "column": key, "direction": direction})
            if cams:
                md_place, _, partner = label.partition(" - ")
                rows.append({"border": border, "caption": caption, "label": label, "md_place": md_place.strip(),
                             "partner": partner.strip(), "cameras": cams})
    return rows


def plzen_cameras(body):
    """Live city cameras (the commented-out zoo block is not published)."""
    page = re.sub(r"<!--.*?-->", " ", text(body), flags=re.S)
    return [{"camera": int(m.group(3)), "label": clean(m.group(1)), "player": m.group(2)}
            for m in re.finditer(r'<div class="kamera">\s*<p>(.*?)</p>\s*<a[^>]+href="(https?://webkamery\.plzen\.eu/kamera(\d+)\.html)"',
                                 page, re.S)]


def pkl_venues(body):
    """Venue camera pages (/{venue}/kamery-online.html) with the camera count; tiles linking elsewhere are returned apart."""
    rows, others = [], []
    for m in re.finditer(r'<a href="(https://www\.pkl\.pl/([a-z0-9-]+/)?kamery(?:-online)?\.html)" class="fadehover">(.*?)</a>',
                         text(body), re.S):
        label = clean(m.group(3))
        mm = re.match(r"(.+?)\s+(\d+)$", label)
        name, count = (mm.group(1), int(mm.group(2))) if mm else (label, None)
        if m.group(2) and m.group(1).endswith("/kamery-online.html"):
            rows.append({"slug": m.group(2).rstrip("/"), "page": m.group(1), "name": name, "cameras": count})
        else:
            others.append({"name": name, "page": m.group(1)})
    return rows, others


def bansko_cameras(body):
    rows = {}
    for m in re.finditer(r'<a href="(https://www\.banskoski\.com/[a-z]{2}/webcam/([a-z0-9-]+))">(.*?)</a>', text(body), re.S):
        rows.setdefault(m.group(2), {"slug": m.group(2), "page": m.group(1), "label": clean(m.group(3))})
    return list(rows.values())


def helsinki_cameras(body):
    rows = {}
    for m in re.finditer(r'<a href="(https://www\.portofhelsinki\.fi/en/about-us/port-of-helsinki/web-camera-([a-z0-9-]+)/)"[^>]*>([^<]*)', text(body)):
        label = clean(m.group(3)).replace("Web Camera:", "").strip()
        if not label or label == "Web Cameras":
            label = m.group(2).replace("-", " ").title()
        rows.setdefault(m.group(2), {"slug": m.group(2), "page": m.group(1), "label": label})
    return list(rows.values())


def visitfinland_streams(body):
    """Section headers of the 'Live from Finland' page with the stream operator each one credits."""
    rows = []
    for m in re.finditer(r'"headline":"([^"]+)","linkTo":[^,]*,"ingress":"((?:[^"\\]|\\.)*)"', text(body)):
        ingress = json.loads('"' + m.group(2) + '"')
        p = re.search(r'provided by <a href="(https://www\.youtube\.com/[^"]+)"[^>]*>([^<]+)</a>', ingress)
        if p:
            rows.append({"headline": clean(m.group(1)), "operator_url": p.group(1), "operator": clean(p.group(2)).rstrip(".")})
    return rows


def kiel_cameras(body):
    page = clean(text(body))
    return [name for name in ("Kieler Förde", "Schwedenkai", "Hafenhaus") if f"Webcam {name}" in page]


def oresund_cameras(body):
    return sorted({(m.group(2), clean(m.group(3))) for m in re.finditer(
        r'href="(https://www\.oresundsbron\.com/cams/(pylon(?:east|west)))">([^<]+)</a>', text(body))})


# ======================================================================================
# OSM helpers (Overpass JSON, out bb / out geom)
# ======================================================================================


def fold(value):
    """Lower case without diacritics (ș/ş, ț/ţ, ă, ł ...), single spaces: for name matching only."""
    value = unicodedata.normalize("NFKD", str(value or "")).replace("ł", "l").replace("Ł", "L")
    return re.sub(r"\s+", " ", "".join(c for c in value if not unicodedata.combining(c))).strip().lower()


def osm(data):
    return [el for el in (data or {}).get("elements", []) if el.get("type") in ("node", "way", "relation")]


def tags(el):
    return el.get("tags") or {}


def names(el):
    t = tags(el)
    return [v for k, v in t.items() if k == "name" or k.startswith(("name:", "alt_name", "official_name", "short_name", "old_name"))]


def named(el, pattern):
    rx = re.compile(pattern, re.I)
    return any(rx.search(fold(n)) for n in names(el))


def el_point(el):
    if el.get("type") == "node":
        return el["lat"], el["lon"]
    b = el.get("bounds")
    if b:
        return (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None


def el_extent_m(el):
    """Half the diagonal of a way's/relation's bounding box (0 for a node)."""
    b = el.get("bounds")
    return P.B.distance_m(b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]) / 2 if b else 0.0


def el_ref(el):
    return f"osm:{el['type']}/{el['id']}"


def dist_km(a, b):
    return P.distance_km(a[0], a[1], b[0], b[1])


def nearest(elements, centre, max_km=None):
    rows = sorted(((dist_km(el_point(el), centre), el) for el in elements if el_point(el)), key=lambda r: (r[0], r[1]["id"]))
    return [(d, el) for d, el in rows if max_km is None or d <= max_km]


def round_up(value, step=50):
    return int(math.ceil(value / step) * step)


def placement(el, feature, *, role="named_feature", minimum=100, extra_m=0.0, point=None, source=None):
    """Placement fields for webcam_places.place: the element's point and an uncertainty covering its extent."""
    lat, lng = point or el_point(el)
    return {"role": role, "lat": lat, "lng": lng, "source": source or el_ref(el), "feature": feature,
            "uncertainty_m": round_up(max(minimum, el_extent_m(el) + extra_m))}


# ======================================================================================
# Overpass lookups: every candidate of every area in two requests (the public server queues each request for
# minutes), matched offline. AREAS keeps one entry per area; the build stage picks an area's elements by its boxes.
# ======================================================================================

MD_STEMS = ("Sculeni|Coste(ș|ş|s)ti|Leu(ș|ş|s)eni|Cahul|Giurgiule(ș|ş|s)ti|Lipcani|Leova|Otaci|S(ă|a)i(ț|ţ|t)i|Briceni|"
            "Grim(ă|a)nc(ă|a)u(ț|ţ|t)i|Larga|Ocni(ț|ţ|t)a|Palanca|Tudora|Criva|Vulc(ă|a)ne(ș|ş|s)ti|Mirnoe")

AREAS = {
    # Moldova: every border-control node/way/area (Moldovan, Romanian and Ukrainian posts) and the border villages.
    "md": {"out": "bb", "boxes": [(45.40, 26.55, 48.55, 30.25)], "selectors": [
        'nwr["barrier"="border_control"]',
        f'node["place"~"^(city|town|village|hamlet)$"]["name"~"^({MD_STEMS})$"]']},
    # North Macedonia: toll plazas, border posts and the named places.
    "mk": {"out": "bb", "boxes": [(40.85, 20.45, 42.37, 23.05)], "selectors": [
        'nwr["barrier"="toll_booth"]', 'nwr["barrier"="border_control"]',
        'node["place"]["name"~"Романовце|Миладиновци|Стоби|Богородица|Градско|Romanovce|Miladinovci|Stobi|Bogorodica",i]']},
    # Finland: Helsinki and Turku harbours/terminals, Market Square, Turku Cathedral, the Visit Finland stream places.
    "helsinki": {"out": "bb", "boxes": [(60.14, 24.88, 60.24, 25.22)], "selectors": [
        'nwr["landuse"="harbour"]', 'nwr["amenity"="ferry_terminal"]',
        'nwr["name"~"satama|terminaali|Kauppatori|Market Square|West Terminal|Harbour",i]']},
    "turku": {"out": "bb", "boxes": [(60.42, 22.18, 60.46, 22.30)], "selectors": [
        'nwr["landuse"="harbour"]', 'nwr["amenity"="ferry_terminal"]', 'nwr["name"~"satama|tuomiokirkko|Cathedral",i]']},
    "rovaniemi": {"out": "bb", "boxes": [(66.53, 25.82, 66.56, 25.87)], "selectors": ['nwr["name"~"Joulupukin|Santa Claus",i]']},
    "koli": {"out": "bb", "boxes": [(63.07, 29.76, 63.12, 29.84)], "selectors": ['node["natural"="peak"]', 'node["place"]']},
    "levi": {"out": "bb", "boxes": [(67.77, 24.75, 67.83, 24.86)], "selectors": ['node["natural"="peak"]', 'node["place"]']},
    "kilpisjarvi": {"out": "bb", "boxes": [(69.00, 20.70, 69.10, 20.90)], "selectors": ['node["place"]']},
    # Kiel: quays, the HafenHaus and the ferry terminals of the inner Förde.
    "kiel": {"out": "bb", "boxes": [(54.30, 10.12, 54.34, 10.16)], "selectors": [
        'nwr["name"~"Schwedenkai|Hafenhaus|Norwegenkai|Seehafen",i]', 'nwr["amenity"="ferry_terminal"]', 'nwr["landuse"="harbour"]']},
    # Italian resorts: Bormio 2000 lift station, Madonna di Campiglio, Breuil-Cervinia.
    "bormio": {"out": "bb", "boxes": [(46.42, 10.33, 46.49, 10.41)], "selectors": [
        'nwr["name"~"Bormio 2000",i]', 'node["place"]["name"="Bormio"]']},
    "campiglio": {"out": "bb", "boxes": [(46.20, 10.80, 46.26, 10.86)], "selectors": ['node["place"]']},
    "cervinia": {"out": "bb", "boxes": [(45.91, 7.60, 45.96, 7.66)], "selectors": ['node["place"]']},
    # Land Tirol air-quality camera sites without a published position.
    "patscherkofel": {"out": "bb", "boxes": [(47.19, 11.43, 47.22, 11.48)], "selectors": [
        'nwr["tourism"~"alpine_hut"]', 'nwr["name"~"Patscherkofel",i]']},
    "koglmoos": {"out": "bb", "boxes": [(47.30, 11.65, 47.40, 11.80)], "selectors": ['nwr["name"~"Ko(g|ge)lmoos",i]']},
    "zettersfeld": {"out": "bb", "boxes": [(46.82, 12.72, 46.89, 12.84)], "selectors": ['nwr["name"~"Zettersfeld",i]']},
    # Belgium: RMI/KMI sites at Jabbeke, Stabroek and Wideumont.
    "be": {"out": "bb", "boxes": [(51.15, 3.03, 51.21, 3.13), (51.30, 4.32, 51.37, 4.41), (49.96, 5.47, 50.01, 5.56)], "selectors": [
        'nwr["man_made"~"tower|monitoring_station|radar|mast"]', 'nwr["operator"~"KMI|IRM|RMI|Meteo",i]',
        'node["place"]["name"~"^(Jabbeke|Stabroek|Wideumont)$"]']},
    # Slovakia: SHMÚ station sites at the six camera places.
    "sk": {"out": "bb", "boxes": [(48.64, 17.17, 48.74, 17.32), (49.37, 18.56, 49.44, 18.68), (48.69, 19.06, 48.79, 19.22),
                                  (48.61, 19.60, 48.68, 19.70), (49.12, 20.25, 49.18, 20.33), (49.26, 21.22, 49.33, 21.33)],
           "selectors": ['nwr["man_made"~"monitoring_station|tower|mast"]', 'nwr["operator"~"SHM|hydrometeorolog",i]',
                         'node["place"]["name"~"^(Senica|Kunov|Turzovka|Banská Bystrica|Lom nad Rimavicou|Stará Lesná|Bardejov)$"]',
                         'nwr["name"~"Kunov",i]']},
    # Belgium (second pass): the RMI/KMI site at Wideumont (the first box missed the village).
    "wideumont": {"out": "bb", "request": "extra", "boxes": [(49.88, 5.44, 49.96, 5.58)], "selectors": [
        'nwr["man_made"~"tower|monitoring_station|radar|mast"]', 'nwr["operator"~"KMI|IRM|RMI",i]',
        'node["place"]["name"="Wideumont"]']},
    # Slovakia (second pass): Senica and the Kunov reservoir (the first box missed them).
    "senica": {"out": "bb", "request": "extra", "boxes": [(48.64, 17.28, 48.74, 17.42)], "selectors": [
        'node["place"]["name"~"^(Senica|Kunov)$"]', 'nwr["name"~"Kunov",i]', 'nwr["man_made"="monitoring_station"]',
        'nwr["operator"~"SHM|hydrometeorolog",i]']},
    # Plzeň: the squares, streets and waterway named by the city, the Makro store and the city node (with geometry).
    "plzen": {"out": "geom", "boxes": [(49.70, 13.28, 49.80, 13.46)], "selectors": [
        'way["name"~"^(náměstí Republiky|sady Pětatřicátníků|Mlýnská strouha|Rokycanská třída|Rokycanská|'
        'náměstí Milady Horákové|Folmavská|Domažlická|Regensburská)$",i]',
        'relation["name"~"^(náměstí Republiky|náměstí Milady Horákové|Mlýnská strouha)$",i]',
        'nwr["name"~"makro",i]', 'node["place"="city"]["name"="Plzeň"]']},
    # PKL: aerial lifts, funiculars, their stations and the named summits around the seven venues.
    "pkl": {"out": "bb", "request": "extra", "boxes": [(49.215, 19.940, 49.285, 20.020), (49.285, 19.915, 49.315, 19.965), (49.390, 20.850, 49.435, 20.930),
                                     (49.405, 20.430, 49.445, 20.500), (49.755, 19.195, 49.795, 19.245), (49.575, 19.505, 49.615, 19.565),
                                     (49.355, 22.420, 49.405, 22.490)],
            "selectors": ['nwr["aerialway"]', 'nwr["railway"="funicular"]', 'nwr["railway"="station"]["station"="funicular"]',
                          'node["natural"="peak"]["name"]']},
    # Bansko: lifts, stations, summits, huts and named localities of the ski area.
    "bansko": {"out": "bb", "request": "extra", "boxes": [(41.76, 23.38, 41.85, 23.50)], "selectors": [
        'nwr["aerialway"]', 'node["natural"="peak"]', 'nwr["tourism"~"alpine_hut|wilderness_hut|viewpoint"]', 'node["place"]',
        'nwr["name"~"Платото|Плато|Шилигарник|Чалин|Бъндери|Тодорка|Banderi|Bunderi|Shiligarnik|Chalin|Plato|Todorka",i]']},
    # Øresund: the bridge, its towers/pylons and the Denmark–Sweden boundary line across the Sound.
    "oresund": {"out": "geom", "boxes": [(55.54, 12.72, 55.63, 12.93)], "selectors": [
        'way["bridge"]', 'nwr["man_made"~"tower|pylon|bridge|mast"]', 'nwr["bridge:support"]',
        'way["boundary"="administrative"]["admin_level"="2"]']},
}


def box_text(box):
    return ",".join(f"{v:g}" for v in box)


# Overpass requests: "bb" (every bounding-box area of the first pass), "extra" (the lift areas and two station areas
# added after the first geometry request failed with HTTP 502) and "geom" (the two areas that need way geometry).
REQUESTS = {"bb": "bb", "extra": "bb", "geom": "geom"}
# Server-side timeout per request: "extra" asks for 180 s on its third attempt (a long declared timeout waits longer
# in the overloaded server's queue); the cached "bb" and "geom" answers keep their query text.
TIMEOUTS = {"bb": 600, "extra": 180, "geom": 600}


def area_request(area):
    return area.get("request", area["out"])


def lookup_query(request):
    """The single Overpass request covering every area assigned to it."""
    lines = [f"  {sel}({box_text(box)});" for key, area in AREAS.items() if area_request(area) == request
             for box in area["boxes"] for sel in area["selectors"]]
    return f"[out:json][timeout:{TIMEOUTS[request]}];\n(\n" + "\n".join(lines) + "\n);\nout " + REQUESTS[request] + ";"


def lookup_stage(out, only=None):
    """Network: the Overpass requests not cached yet, then the Wikidata entities named by OSM wikidata tags."""
    client = F.PoliteClient(timeout=900)
    previous = cached_log(out) or {"requests": [], "lookups": []}
    log = []
    for request in REQUESTS:
        if (only and request not in only) or cached(out, "overpass:" + lookup_query(request)) is not None:
            continue
        try:
            data = P.overpass(client, lookup_query(request), cache_dir(out))
        except (F.Refused, OSError) as e:
            log.append({"lookup": f"overpass:{request}", "error": str(e)[:200], "at": F.now()})
            print(request, "refused:", str(e)[:200], flush=True)
            continue
        remark = data.get("remark") or ""
        if "error" in remark.lower():  # a server-side timeout: never keep a partial answer in the cache
            drop_cached(out, "overpass:" + lookup_query(request))
        log.append({"lookup": f"overpass:{request}", "elements": len(data.get("elements", [])), "remark": remark, "at": F.now()})
        print(request, len(data.get("elements", [])), "elements", remark, flush=True)
    data = load_lookups(out)
    for qid in sorted(wikidata_wanted(data)):
        if cached(out, "wikidata:" + qid) is not None:
            continue
        try:
            coords = P.wikidata_coordinates(client, qid, cache_dir(out))
            log.append({"lookup": f"wikidata:{qid}", "coordinates": coords, "at": F.now()})
        except (F.Refused, OSError, KeyError) as e:
            log.append({"lookup": f"wikidata:{qid}", "error": str(e)[:200], "at": F.now()})
        print(qid, log[-1], flush=True)
    write_json(cache_dir(out) / "lookup_log.json", {"requests": previous["requests"] + client.log,
                                                    "lookups": previous["lookups"] + log})
    return client


def cache_path(out, key):
    import hashlib
    return cache_dir(out) / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")


def drop_cached(out, key):
    if cache_path(out, key).exists():
        cache_path(out, key).unlink()


def cached(out, key):
    path = cache_path(out, key)
    return json.loads(path.read_text(encoding="utf-8"))["data"] if path.exists() else None


def load_lookups(out):
    """The cached Overpass answers by request; None for a request not made yet."""
    return {request: cached(out, "overpass:" + lookup_query(request)) for request in REQUESTS}


def area_elements(lookups, key):
    """The elements of one area: those of its request whose point lies in one of its boxes."""
    area = AREAS[key]
    rows, seen = [], set()
    for el in osm(lookups.get(area_request(area))):
        pt = el_point(el)
        if pt and (el["type"], el["id"]) not in seen and any(b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3] for b in area["boxes"]):
            seen.add((el["type"], el["id"]))
            rows.append(el)
    return rows


# ======================================================================================
# Records, checks and fallbacks
# ======================================================================================

OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright"
WIKIDATA_CC0 = "https://www.wikidata.org/wiki/Wikidata:Licensing"


def option(plc, *, centre, max_km, allow_sea=False, expected_country=None):
    """One candidate placement and the sanity limits it must pass (webcam_places.check)."""
    return {"placement": plc, "centre": centre, "max_km": max_km, "allow_sea": allow_sea, "expected_country": expected_country}


def place_centre(el, feature, uncertainty_m):
    """Last resort: the centre of the named place (an OSM place node), with the place's extent as uncertainty."""
    return placement(el, feature, role="place_centre", minimum=uncertainty_m)


def placed_record(provider, provider_id, name, country, region, plc, *, page, source_page, source_catalog, observed_at, **extra):
    rec = item(provider, provider_id, name, plc["lat"], plc["lng"], country, region, format_="official_page", official_page=page,
               source_page=source_page, source_catalog=source_catalog, observed_at=observed_at, coordinate_role=plc["role"],
               coordinate_crs="EPSG:4326", coordinate_note=PLACED_NOTE, **extra)
    return P.place(rec, role=plc["role"], lat=plc["lat"], lng=plc["lng"], source=plc["source"], feature=plc["feature"],
                   uncertainty_m=plc["uncertainty_m"])


def settle(spec, options, countries, rules=None):
    """The first option whose record passes every check, or a hold listing why each option failed.

    spec: {provider, provider_id, name, country, region, page, source_page, source_catalog, observed_at, extra?}."""
    tried = []
    for opt in options:
        rec = placed_record(spec["provider"], spec["provider_id"], spec["name"], spec["country"], spec["region"], opt["placement"],
                            page=spec["page"], source_page=spec["source_page"], source_catalog=spec["source_catalog"],
                            observed_at=spec["observed_at"], **spec.get("extra", {}))
        problems = P.check(rec, countries, expected_country=opt["expected_country"] or spec["country"], centre=opt["centre"],
                           max_km=opt["max_km"], allow_sea=opt["allow_sea"], rules=rules)
        if not problems:
            return {"item": rec, "tried": tried}
        tried.append({"source": opt["placement"]["source"], "role": opt["placement"]["role"], "problems": problems})
    return {"item": None, "tried": tried}


def hold_row(spec, reason, tried=()):
    return {"id": f"{spec['provider']}:{spec['provider_id']}", "name": spec["name"], "reason": reason, "tried": list(tried)}


class Outcome:
    """Placed items and held records of one source, with the counts the report needs."""

    def __init__(self):
        self.items, self.held, self.fallbacks = [], [], []

    def add(self, spec, options, countries, *, why_none=None):
        if not options:
            self.held.append(hold_row(spec, why_none or "no open-data feature identifies the named place"))
            return None
        result = settle(spec, options, countries)
        if result["item"] is None:
            self.held.append(hold_row(spec, "every placement failed the sanity checks", result["tried"]))
            return None
        if result["tried"]:
            self.fallbacks.append({"id": result["item"]["id"], "used": result["item"]["coordinate_source"],
                                   "role": result["item"]["coordinate_role"], "failed_first": result["tried"]})
        self.items.append(result["item"])
        return result["item"]

    def summary(self):
        by_role = collections.defaultdict(list)
        for x in self.items:
            by_role[x["coordinate_role"]].append(x["coordinate_uncertainty_m"])
        return {role: {"records": len(v), "uncertainty_m_median": sorted(v)[len(v) // 2], "uncertainty_m_range": [min(v), max(v)]}
                for role, v in sorted(by_role.items())}


def placement_source_note(datasets):
    return {"coordinate_placement": ("No camera position is published by the operator: QGlobe placed each record at the named "
                                     "feature in an open dataset, or at the named place's centre, with coordinate_source, "
                                     "coordinate_feature and coordinate_uncertainty_m on every record (identity not confirmed)."),
            "coordinate_datasets": datasets}


def page_only_policy(sid, *, name, url, terms_url, license_, media_rights, attribution, evidence, countries, page_hosts, raw,
                     datasets=("OpenStreetMap (ODbL 1.0)",), catalog_url=None, rights_note=None):
    pol = E.page_policy(sid, name=name, url=url, catalog_url=catalog_url, terms_url=terms_url, license_=license_,
                        media_rights=media_rights, attribution=attribution,
                        evidence=list(evidence) + [OSM_COPYRIGHT if any("OpenStreetMap" in d for d in datasets) else WIKIDATA_CC0],
                        countries=countries, page_hosts=page_hosts, role=None, raw=raw)
    pol["source"].update(placement_source_note(list(datasets)))
    if rights_note:
        pol["source"]["rights_note"] = rights_note
    return pol


# ======================================================================================
# Policies of the sources placed here (from the round-2 register europe-2.json; page links only)
# ======================================================================================

MD_RIGHTS_PAGE = "https://www.border.gov.md/camere-web/leuseni-iesire"
BANSKO_TERMS = "https://www.banskoski.com/en/page/general-terms"

NEW_SOURCES = {
    "md_border_police_webcams": dict(
        country="MD", name="Poliția de Frontieră a Republicii Moldova — camere web la punctele de trecere a frontierei",
        url=E.MD_LIST, terms_url=MD_RIGHTS_PAGE, page_file="camere-web.html",
        license_="All rights reserved ('Copyright 2026 IGPF Poliția de Frontieră / Toate drepturile rezervate')",
        media_rights=("HLS streams on mediaserver.border.gov.md:50793 (non-standard port); the camera pages state all rights "
                      "reserved. Links to the per-crossing camera pages only."),
        attribution="Poliția de Frontieră a Republicii Moldova (border.gov.md)", evidence=[E.MD_LIST, MD_RIGHTS_PAGE],
        page_hosts=["www.border.gov.md"]),
    "plzen_city_webcams": dict(
        country="CZ", name="Statutární město Plzeň — webkamery", url=E.PLZEN_PAGE, terms_url=E.PLZEN_PAGE, page_file="webkamery.html",
        license_="None stated (© 2026 Statutární město Plzeň)",
        media_rights=("Footer copyright of the city; the streams are not archived (GDPR note). The per-camera players are HTTP "
                      "only (webkamery.plzen.eu), so every record links the city's HTTPS webcam page."),
        attribution="Statutární město Plzeň, plzen.eu", evidence=[E.PLZEN_PAGE], page_hosts=["www.plzen.eu"]),
    "pkl_webcams": dict(
        country="PL", name="Polskie Koleje Linowe (PKL) — kamery online", url=E.PKL_LIST, terms_url=E.PKL_LIST,
        page_file="kamery-online.html", license_="None stated",
        media_rights="Streams are served by WebCamera.pl players; no reuse licence on pkl.pl. Links to the venue camera pages only.",
        attribution="Polskie Koleje Linowe, pkl.pl", evidence=[E.PKL_LIST, "https://www.pkl.pl/kasprowy-wierch/kamery-online.html"],
        page_hosts=["www.pkl.pl"]),
    "bansko_ski_webcams": dict(
        country="BG", name="Bansko ski area — webcams (banskoski.com)", url=E.BANSKO_HOME, terms_url=BANSKO_TERMS,
        page_file="home.html", license_="None (© 2018 - 2025 Bansko)",
        media_rights="Copyright notice only; no reuse permission. Links to the webcam pages only.",
        attribution="Bansko ski area, banskoski.com", evidence=[E.BANSKO_HOME, "https://www.banskoski.com/en/webcam/todorka", BANSKO_TERMS],
        page_hosts=["www.banskoski.com"]),
    "port_of_helsinki_webcams": dict(
        country="FI", name="Port of Helsinki — web cameras (South, West and Vuosaari harbours)", url=E.HELSINKI_PORT,
        terms_url=E.HELSINKI_PORT, page_file="web-camera-south-harbour.html", license_="None stated",
        media_rights=("No statement on reuse; the player loads only after marketing-cookie consent (third-party video host). "
                      "Links to the camera pages only."),
        attribution="Port of Helsinki", evidence=[E.HELSINKI_PORT], page_hosts=["www.portofhelsinki.fi"]),
    "visitfinland_live_streams": dict(
        country="FI", name="Visit Finland — 'Live from Finland' webcam streams (operators' YouTube channels)", url=E.VISITFINLAND,
        terms_url=E.VISITFINLAND, page_file="live-from-finland.html", license_="None stated",
        media_rights=("YouTube streams of the operators Visit Finland credits; no rights statement. Links to the operator's channel "
                      "(or Visit Finland's page when the credit links a single video); no embedding."),
        attribution="Stream provided by the named operator (via Visit Finland)", evidence=[E.VISITFINLAND],
        page_hosts=["www.youtube.com", "www.visitfinland.com"]),
    "port_of_kiel_webcams": dict(
        country="DE", name="PORT OF KIEL — webcams Schwedenkai and HafenHaus", url=E.KIEL_PAGE, terms_url="https://www.portofkiel.com/Impressum.html",
        page_file="webcam.html", license_="Not stated",
        media_rights=("No licence read; 'Webcam Kieler Förde' is a feratel stream already in the catalogue and is not listed. "
                      "Links to the port's webcam page only."),
        attribution="PORT OF KIEL (portofkiel.com)", evidence=[E.KIEL_PAGE], page_hosts=["www.portofkiel.com"]),
    "oresundsbron_pylon_cams": dict(
        country="SE", name="Øresundsbron — pylonkameror (east and west pylons)", url=E.ORESUND_PAGE, terms_url=E.ORESUND_PAGE,
        page_file="pylonkamera.html", license_="None stated",
        media_rights="No rights statement on the page. Links to the operator's pylon-camera page only.",
        attribution="Øresundsbron", evidence=[E.ORESUND_PAGE], page_hosts=["www.oresundsbron.com"]),
    "turku_cathedral_tower_cams": dict(
        country="FI", name="Turku Cathedral — tower camera (Turun ja Kaarinan seurakuntayhtymä)", url=E.TURKU_PAGE,
        terms_url=E.TURKU_PAGE, page_file="tower-camera.html", license_="None stated",
        media_rights="No rights statement; third-party viewer. A link to the cathedral's tower-camera page only.",
        attribution="Turun ja Kaarinan seurakuntayhtymä", evidence=[E.TURKU_PAGE], page_hosts=["turunseurakunnat.fi"]),
    "it_ski_bormio": dict(
        country="IT", name="Bormio Ski — webcam page", url=E.BORMIO_PAGE, terms_url="https://www.bormioski.eu/", page_file="webcam-bormio.html",
        license_="All rights reserved (operator/vendor)",
        media_rights="Embedded vendor and operator cameras without reuse rights: one resort-level link.",
        attribution="Bormio Ski - bormioski.eu", evidence=[E.BORMIO_PAGE], page_hosts=["www.bormioski.eu"]),
    "it_ski_campiglio_apt": dict(
        country="IT", name="APT Madonna di Campiglio Pinzolo Val Rendena — webcam page", url=E.CAMPIGLIO_PAGE,
        terms_url="https://www.campigliodolomiti.it/", page_file="webcam.html", license_="All rights reserved (operator/vendor)",
        media_rights="Embedded vendor and lift-company cameras without reuse rights: one resort-level link.",
        attribution="APT Madonna di Campiglio Pinzolo Val Rendena", evidence=[E.CAMPIGLIO_PAGE], page_hosts=["www.campigliodolomiti.it"]),
    "it_ski_cervinia": dict(
        country="IT", name="Cervino S.p.A. — Breuil-Cervinia/Valtournenche webcam page", url=E.CERVINIA_PAGE,
        terms_url="https://www.cervinia.it/", page_file="webcam.html", license_="All rights reserved ('©Cervino S.p.A - 2026')",
        media_rights="Embedded vendor and operator cameras without reuse rights: one resort-level link.",
        attribution="Cervino S.p.A. - cervinia.it", evidence=[E.CERVINIA_PAGE], page_hosts=["www.cervinia.it"]),
}


def new_source_policy(out, sid, countries=None, datasets=("OpenStreetMap (ODbL 1.0)",)):
    m = NEW_SOURCES[sid]
    return page_only_policy(sid, name=m["name"], url=m["url"], terms_url=m["terms_url"], license_=m["license_"],
                            media_rights=m["media_rights"], attribution=m["attribution"], evidence=m["evidence"],
                            countries=countries or [m["country"]], page_hosts=m["page_hosts"],
                            raw=E.raw_files(out, sid, m["page_file"]), datasets=datasets)



# ======================================================================================
# Moldova: the Moldovan-side post (OSM barrier=border_control) of each crossing on the Border Police list
# ======================================================================================

MD_PLACE_UNCERTAINTY = {"city": 5000, "town": 3000, "village": 2000, "hamlet": 1500}
CYRILLIC = dict(pair.split(":") for pair in (
    "а:a б:b в:v г:g ґ:g д:d е:e є:ie ж:zh з:z ѕ:dz и:i і:i й:i ј:j к:k л:l љ:lj м:m н:n њ:nj о:o п:p р:r с:s т:t "
    "у:u ф:f х:h ц:c ч:ch џ:dz ш:sh щ:shch ъ:a ы:y ь: э:e ю:iu я:ia").split())


def loose(value):
    """fold() plus Cyrillic transliteration, without 'h' and with y -> i: Romanian, Russian and Ukrainian spellings
    of a place (Moghilev / Могилів, Rossoșanî / Россошани) meet."""
    s = "".join(CYRILLIC.get(c, c) for c in fold(value))
    return s.replace("h", "").replace("y", "i")


def tokens(value):
    return [t for t in re.split(r"[^a-z]+", loose(value)) if len(t) >= 4]


def tokens_match(found, wanted):
    """Some name token shares its first five letters (or the whole shorter token) with a wanted token."""
    return any(f[:5] == w[:5] if min(len(f), len(w)) >= 5 else f == w for f in found for w in wanted)


def country_distance_km(countries, point, code, radii=(0.5, 1, 2, 3, 4, 6, 8, 10, 12), directions=16):
    """Smallest sampled radius (km) at which a Natural Earth point of `code` lies around `point`; None beyond 12 km."""
    lat, lng = point
    for r in radii:
        for k in range(directions):
            a = 2 * math.pi * k / directions
            dlat = r / 111.2 * math.cos(a)
            dlng = r / (111.2 * math.cos(math.radians(lat))) * math.sin(a)
            if countries.country(lat + dlat, lng + dlng) == code:
                return r
    return None


def clusters(elements, link_km=0.6):
    """Single-link groups of elements closer than link_km (one border post is often mapped as several nodes/ways)."""
    groups = []
    for el in sorted(elements, key=lambda e: (e["type"], e["id"])):
        hits = [g for g in groups if any(dist_km(el_point(el), el_point(o)) <= link_km for o in g)]
        merged = [el] + [o for g in hits for o in g]
        groups = [g for g in groups if all(g is not h for h in hits)] + [merged]
    return groups


def group_feature(group, anchor):
    """The element that stands for a post: a mapped way/area if any, else the node nearest the Moldovan place
    (the Moldovan side of a pair); with the spread of the group in metres."""
    pool = [el for el in group if el["type"] != "node"] or group
    rep = min(pool, key=lambda el: (dist_km(el_point(el), anchor), el["id"]))
    spread_m = max(dist_km(el_point(rep), el_point(el)) for el in group) * 1000
    return rep, spread_m


def crossing_tokens(crossing):
    return tokens(crossing["md_place"]), tokens(crossing["partner"])


def name_role(group, crossing, others):
    """'full' (both places named), 'md', 'partner', 'other' (names another crossing of the list) or None."""
    md_t, partner_t = crossing_tokens(crossing)
    found = [t for el in group for n in names(el) for t in tokens(n)]
    if not found:
        return None
    md, partner = tokens_match(found, md_t), tokens_match(found, partner_t)
    if md and partner:
        return "full"
    if md:
        return "md"
    if partner:
        return "partner"
    if any(tokens_match(found, t) for o in others for t in crossing_tokens(o)):
        return "other"
    return None


def md_anchor(crossing, places, countries):
    """The Moldovan place named first in the crossing label: a Natural Earth Moldovan place node within 12 km of the
    partner country (the nearest to it), else a same-named node that Natural Earth puts across the border but within
    2 km of Moldova (it anchors the search; its centre is never published)."""
    want = fold(crossing["md_place"])
    cands = [el for el in places if fold(tags(el).get("name")) == want]
    rank = {"city": 0, "town": 1, "village": 2, "hamlet": 3}
    inside = []
    for el in cands:
        if countries.country(*el_point(el)) == "MD":
            d = country_distance_km(countries, el_point(el), crossing["border"])
            if d is not None:
                inside.append((d, rank.get(tags(el).get("place"), 9), el["id"], el))
    if inside:
        d, _, _, el = min(inside, key=lambda r: r[:3])
        return el, d, True
    across = [(country_distance_km(countries, el_point(el), "MD", radii=(0.5, 1, 2)), el["id"], el) for el in cands
              if countries.country(*el_point(el)) != "MD"]
    across = [r for r in across if r[0] is not None]
    if across:
        d, _, el = min(across, key=lambda r: r[:2])
        return el, 0.0, False
    return None, None, False


def md_options(crossing, crossings, elements, countries):
    """Placement options for one crossing (post first, then the Moldovan place centre) and notes on the match.

    Candidate posts: groups of Natural Earth-Moldovan border_control elements within 8 km of the anchor place,
    except groups whose names belong to another crossing of the list and, when the partner's own post is named in
    OSM, groups farther than 2 km from it. Strong evidence: the names give this crossing's Moldovan place, or the
    nearest mapped foreign post within 2 km lies in the partner country. Weak evidence: the names give only the
    partner place, or Natural Earth puts the partner country within 3 km. One strong group (or one with the full
    crossing name) -> that post; else one weak group -> that post; else (several or none) -> the place centre."""
    posts = [el for el in elements if tags(el).get("barrier") == "border_control"]
    places = [el for el in elements if el["type"] == "node" and tags(el).get("place")]
    side = {(el["type"], el["id"]): countries.country(*el_point(el)) for el in posts}
    anchor_el, border_km, anchor_inside = md_anchor(crossing, places, countries)
    if anchor_el is None:
        return [], {"anchor": None, "notes": [f"no place node named {crossing['md_place']!r} near the {crossing['border']} border"]}
    anchor = el_point(anchor_el)
    others = [c for c in crossings if c is not crossing]
    md_t, partner_t = crossing_tokens(crossing)
    foreign = [el for el in posts if side[(el["type"], el["id"])] not in ("MD", "ZZ")]
    named_partner = [el for _, el in nearest(foreign, anchor, 8)
                     if tokens_match([t for n in names(el) for t in tokens(n)], partner_t)]
    md_posts = [el for el in posts if side[(el["type"], el["id"])] == "MD" and dist_km(el_point(el), anchor) <= 8]
    strong, weak, notes, near_m = [], [], [], []
    for group in clusters(md_posts):
        rep, spread_m = group_feature(group, anchor)
        role = name_role(group, crossing, others)
        ref = el_ref(rep)
        if role == "other":
            notes.append(f"{ref}: names another crossing of the list")
            continue
        if named_partner and min(dist_km(el_point(rep), el_point(p)) for p in named_partner) > 2:
            notes.append(f"{ref}: more than 2 km from the partner's named post")
            continue
        across = nearest(foreign, el_point(rep), 2)
        mapped = side[(across[0][1]["type"], across[0][1]["id"])] if across else None
        if role in ("full", "md") or mapped == crossing["border"]:
            strong.append((role == "full", rep, spread_m))
        elif role == "partner" or (mapped is None and country_distance_km(countries, el_point(rep), crossing["border"],
                                                                          radii=(0.5, 1, 2, 3)) is not None):
            weak.append((False, rep, spread_m))
        else:
            notes.append(f"{ref}: no evidence it serves this crossing (nearest mapped foreign post {mapped})")
            continue
        near_m.append(dist_km(el_point(rep), anchor) * 1000 + spread_m)
    for el in named_partner:
        near_m.append(dist_km(el_point(el), anchor) * 1000)
    for el in posts:  # the crossing's own named post, wherever Natural Earth puts it
        found = [t for n in names(el) for t in tokens(n)]
        if tokens_match(found, md_t) and tokens_match(found, partner_t) and dist_km(el_point(el), anchor) <= 10:
            near_m.append(dist_km(el_point(el), anchor) * 1000)
    chosen = None
    full = [g for g in strong if g[0]]
    if len(strong) == 1:
        chosen = strong[0]
    elif len(full) == 1:
        chosen = full[0]
    elif not strong and len(weak) == 1:
        chosen = weak[0]
    elif strong or weak:
        notes.append(f"{len(strong)} strong and {len(weak)} weak candidate posts: unclear, place centre only")
    options = []
    if chosen:
        _, rep, spread_m = chosen
        label = tags(rep).get("name") or f"{crossing['label']} border crossing"
        feature = f"{label} — Moldovan border post (OSM barrier=border_control)"
        options.append(option(placement(rep, feature, minimum=150, extra_m=spread_m), centre=anchor, max_km=10,
                              expected_country="MD"))
    if anchor_inside:
        kind = tags(anchor_el).get("place", "village")
        reach = max([MD_PLACE_UNCERTAINTY.get(kind, 2000), (border_km or 0) * 1000 + 1000] + [m + 300 for m in near_m])
        options.append(option(place_centre(anchor_el, f"{tags(anchor_el).get('name')} ({kind}), the Moldovan {kind} of the "
                                                      f"{crossing['label']} crossing", round_up(reach, 500)),
                              centre=anchor, max_km=1, expected_country="MD"))
    else:
        notes.append(f"the place node {el_ref(anchor_el)} lies outside Natural Earth's Moldova: no centre fallback")
    return options, {"anchor": el_ref(anchor_el), "chosen": el_ref(chosen[1]) if chosen else None, "notes": notes}


def build_md_border_police_webcams(out, lookups, countries):
    sid = "md_border_police_webcams"
    body = E.read_raw(out, sid, "camere-web.html")
    if body is None:
        return E.not_fetched(sid, "MD", NEW_SOURCES[sid]["name"], E.MD_LIST, out, [E.MD_LIST])
    when = E.when_of(out, sid, "camere-web.html")
    elements = area_elements(lookups, "md")
    crossings = md_crossings(body)
    plans = {c["label"]: md_options(c, crossings, elements, countries) for c in crossings}
    used = collections.Counter(p[1]["chosen"] for p in plans.values() if p[1]["chosen"])
    outcome = Outcome()
    for crossing in crossings:
        options, match = plans[crossing["label"]]
        if match["chosen"] and used[match["chosen"]] > 1:  # one post for two crossings: neither keeps it
            options = [o for o in options if o["placement"]["source"] != match["chosen"]]
            match["notes"].append(f"{match['chosen']} chosen by two crossings: place centre only")
        for cam in crossing["cameras"]:
            spec = {"provider": sid, "provider_id": cam["slug"], "country": "MD", "region": "Moldova",
                    "name": f"{crossing['label']} border crossing — {cam['direction']} (Moldovan Border Police camera)",
                    "page": f"https://www.border.gov.md/camere-web/{cam['slug']}", "source_page": E.MD_LIST,
                    "source_catalog": E.MD_LIST, "observed_at": when,
                    "extra": {"crossing": crossing["label"], "border_with": crossing["border"], "direction": cam["direction"],
                              "site_type": "border_crossing"}}
            outcome.add(spec, options, countries, why_none="; ".join(match["notes"]) or "no anchor place")
    pol = new_source_policy(out, sid)
    pol["source"]["retires"] = ("md_border_police_webcams_ukraine_facing (held in round 2): its 18 pages are records of this "
                                "source; the user lifted the hold (Moldovan official public pages, Moldovan-side posts)")
    return {"status": "integrated" if outcome.items else "held", "country": "MD", "outcome": outcome, "policy": pol,
            "robots": "www.border.gov.md: /camere-web allowed (list read in round 2)",
            "match_notes": {label: plan[1] for label, plan in plans.items()},
            "changes": ["30 camera pages of 18 crossings (Romania and Ukraine tables); the round-2 Ukraine-facing hold is lifted "
                        "and its fragment md_border_police_webcams_ukraine_facing retired",
                        "the column of the official table gives the direction (entry into / exit from Moldova)"]}

# ======================================================================================
# Integrated round-2 sources: the records left out for lack of an official position are added (existing ids kept)
# ======================================================================================


def extend(result, outcome, datasets, note):
    """The round-2 result with its records kept and the placed ones added to the same input and policy."""
    pol = result["policy"]
    pol["source"].update(placement_source_note(datasets))
    pol["source"]["evidence"] = list(pol["source"]["evidence"]) + [OSM_COPYRIGHT]
    changes = [c for c in result.get("changes", []) if "not placed" not in c and "skipped" not in c]
    return {"status": "integrated", "country": result["country"], "base_items": result["items"], "outcome": outcome,
            "policy": pol, "robots": result.get("robots"), "changes": changes + [note]}


def mk_unplaced(page_body, posts_body):
    """English camera posts whose page has no marker on the official camera map (round 2 left them out)."""
    placed = {r["post"] for r in E.mk_rows(page_body, posts_body)[0]}
    rows = []
    for post in json.loads(text(posts_body)):
        if post.get("lang") == "en" and int(post["id"]) not in placed:
            title = clean(post["title"]["rendered"])
            rows.append({"post": int(post["id"]), "title": title, "page": post["link"],
                         "kind": "border_crossing" if title.lower().startswith("border") else "toll_plaza",
                         "place": re.search(r"[“\"]([^”\"“]+)[”\"“]", title).group(1)})
    return rows


def rmi_unplaced(body, isd_table):
    isd = E.isd_rows(isd_table, {v[0] for v in E.RMI_ISD.values()})
    return [p for p in E.rmi_pages(body) if not (E.RMI_ISD.get(p["station"]) and E.isd_place(isd, *E.RMI_ISD[p["station"]]))]


def shmu_unplaced(body, isd_table):
    isd = E.isd_rows(isd_table, {v[0] for v in E.SHMU_ISD.values()})
    return [c for c in E.shmu_cameras(body) if not (E.SHMU_ISD.get(c["camera"]) and E.isd_place(isd, *E.SHMU_ISD[c["camera"]]))]


def tirol_unplaced(out):
    sid = "tirol_luft_livebilder"
    rows = []
    for cam in E.parse_tirol_livebilder(E.read_raw(out, sid, "livebilder.html")):
        name = f"station-{cam['station_slug']}.html"
        body = E.read_raw(out, sid, name)
        st = E.tirol_station(body) if body else None
        if st and st["lat"] is None:
            rows.append(dict(cam, station_name=st["name"], station_file=name))
    return rows


# ======================================================================================
# Feature tables: which open-data feature stands for each named place (matched in the cached lookups)
# ======================================================================================


def find(elements, *, name=None, tag=None, place=False):
    """Elements whose (any-language) name matches `name` (regex on loose names) and whose tags include `tag`."""
    rows = []
    for el in elements:
        t = tags(el)
        if tag and not all((t.get(k) == v if v is not True else k in t) for k, v in tag.items()):
            continue
        if place and "place" not in t:
            continue
        if name and not any(re.search(name, fold(n)) or re.search(name, loose(n)) for n in names(el)):
            continue
        rows.append(el)
    return rows


def one(rows):
    """The single matching element, or None when there is none or the match is ambiguous (rule 3)."""
    groups = clusters(rows, link_km=0.3) if rows else []
    if len(groups) != 1:
        return None, len(groups)
    group = groups[0]
    rep, spread = group_feature(group, el_point(group[0]))
    return (rep, spread), 1


def feature_option(found, feature, *, minimum, country=None, centre=None, max_km=5, allow_sea=False, role="named_feature"):
    rep, spread = found
    plc = placement(rep, feature, role=role, minimum=minimum, extra_m=spread)
    return option(plc, centre=centre or el_point(rep), max_km=max_km, allow_sea=allow_sea, expected_country=country)


def simple_spec(provider, provider_id, name, country, region, page, source_page, source_catalog, observed_at, **extra):
    return {"provider": provider, "provider_id": provider_id, "name": name, "country": country, "region": region, "page": page,
            "source_page": source_page, "source_catalog": source_catalog, "observed_at": observed_at, "extra": extra}


def add_feature(outcome, spec, countries, rows, feature, *, minimum, role="named_feature", centre=None, max_km=5,
                allow_sea=False, missing="no OSM feature with that name"):
    found, n = one(rows)
    if not found:
        outcome.add(spec, [], countries, why_none=f"{missing} ({n} candidate groups)" if n else missing)
        return
    outcome.add(spec, [feature_option(found, feature, minimum=minimum, country=spec["country"], centre=centre, max_km=max_km,
                                      allow_sea=allow_sea, role=role)], countries)


# ----- North Macedonia: toll plazas and the Bogorodica border post -----

def build_mk_state_roads_video_kameri(out, lookups, countries):
    sid = "mk_state_roads_video_kameri"
    base = E.build_mk_state_roads_video_kameri(out)
    outcome = Outcome()
    if base["status"] != "integrated":
        return dict(base, outcome=outcome)
    page, posts = E.read_raw(out, sid, "page_video_kameri.json"), E.read_raw(out, sid, "video_kamera_posts.json")
    when = E.when_of(out, sid, "video_kamera_posts.json")
    els = area_elements(lookups, "mk")
    for row in mk_unplaced(page, posts):
        spec = simple_spec(sid, str(row["post"]), f"{row['title']} — State Roads video camera", "MK", "North Macedonia", row["page"],
                           E.MK_MAP, E.MK_POSTS_REST, when, site_type=row["kind"])
        want = "|".join(tokens(row["place"]))
        village = find(els, name=want, place=True)
        centre = el_point(village[0]) if len(village) == 1 else None
        if row["kind"] == "toll_plaza":
            rows = find(els, name=want, tag={"barrier": "toll_booth"})
            add_feature(outcome, spec, countries, rows, f"Toll plaza {row['place']} (OSM barrier=toll_booth)", minimum=100,
                        centre=centre, max_km=6)
        else:
            if centre is None:
                outcome.add(spec, [], countries, why_none=f"no single place node named {row['place']}")
                continue
            posts_mk = [el for _, el in nearest(find(els, tag={"barrier": "border_control"}), centre, 5)
                        if countries.country(*el_point(el)) == "MK"]
            # the source country's post: unnamed groups, or groups named after the Macedonian place
            groups = [g for g in clusters(posts_mk) if not any(names(el) for el in g)
                      or tokens_match([t for el in g for n in names(el) for t in tokens(n)], tokens(row["place"]))]
            rows = [el for g in groups for el in g] if len(groups) == 1 else []
            add_feature(outcome, spec, countries, rows, f"{row['place']} border crossing — North Macedonian post "
                                                        "(OSM barrier=border_control)", minimum=150, centre=centre, max_km=5,
                        missing=f"{len(groups)} North Macedonian post groups within 5 km of {row['place']}")
    return extend(base, outcome, ["OpenStreetMap (ODbL 1.0)"],
                  "pages without a map marker placed at the named OSM toll plaza / the Macedonian border post (named_feature)")


# ----- Land Tirol air-quality camera sites -----

TIROL_FEATURES = {  # station slug -> (area, name regex, tags, role, minimum uncertainty m, feature text)
    "oeav-patscherkofel": ("patscherkofel", r"patscerkofel", {"tourism": "alpine_hut"}, "named_feature", 100,
                           "Patscherkofel Schutzhaus (the ÖAV hut named on the station page)"),
    "schwaz-koglmoos": ("koglmoos", r"^koglmoos$", {"place": "locality"}, "place_centre", 1000,
                        "Koglmoos above Schwaz (locality named on the station page)"),
    "lienz-zettersfeld": ("zettersfeld", r"^zettersfeld$", {"place": True}, "place_centre", 1500,
                          "Zettersfeld above Lienz (hamlet named on the station page)"),
}


def build_tirol_luft_livebilder(out, lookups, countries):
    sid = "tirol_luft_livebilder"
    base = E.build_tirol_luft_livebilder(out)
    outcome = Outcome()
    if base["status"] != "integrated":
        return dict(base, outcome=outcome)
    for cam in tirol_unplaced(out):
        name = f"{cam['station_name']} — Land Tirol Luftgüte webcam" + (f" ({cam['view']})" if cam["view"] else "")
        spec = simple_spec(sid, cam["key"], name, "AT", "Tirol", cam["station_page"], E.TIROL_LIVE, E.TIROL_LIVE,
                           E.when_of(out, sid, cam["station_file"]), direction=cam["view"])
        if cam["station_slug"] not in TIROL_FEATURES:
            outcome.add(spec, [], countries, why_none="station not in the feature table")
            continue
        area, rx, tag, role, minimum, feature = TIROL_FEATURES[cam["station_slug"]]
        add_feature(outcome, spec, countries, find(area_elements(lookups, area), name=rx, tag=tag), feature, minimum=minimum,
                    role=role)
    return extend(base, outcome, ["OpenStreetMap (ODbL 1.0)"],
                  "station pages without a published position placed at the hut/place they name (webcam_places)")


# ----- RMI/KMI and SHMÚ: stations without an agency-table position -----

RMI_FEATURES = {  # station -> (area, name regex, tags, role, minimum m, feature)
    "jabbeke": ("be", r"jabbeke", {"man_made": "monitoring_station", "operator": "KMI"}, "named_feature", 150,
                "Weerradar Jabbeke (KMI station, OSM man_made=monitoring_station)"),
    "stabroek": ("be", r"^stabroek$", {"place": True}, "place_centre", 3000, "Stabroek (town centre; the KMI station is not mapped)"),
    "wideumont": ("wideumont", r"^wideumont$", {"place": True}, "place_centre", 1500,
                  "Wideumont (village centre; the IRM station is not mapped)"),
}
WIDEUMONT_STATION = (r"wideumont|radar", {"man_made": "monitoring_station"})
SHMU_FEATURES = {  # camera -> (area, name regex, tags, role, minimum m, feature)
    "hdcam02": ("senica", r"^kunov$", None, "named_feature", 1500, "Kunov reservoir near Senica (named in the camera title)"),
    "hdcam04": ("sk", r"^turzovka$", {"place": True}, "place_centre", 2000, "Turzovka (town centre; the SHMÚ station is not mapped)"),
    "hdcam07": ("sk", r"^banska bistrica$", {"place": "city"}, "place_centre", 4000,
                "Banská Bystrica (city centre; the SHMÚ station is not mapped)"),
    "hdcam08": ("sk", r"^lom nad rimavicou$", {"place": True}, "place_centre", 2000,
                "Lom nad Rimavicou (village centre; the SHMÚ station is not mapped)"),
    "hdcam69": ("sk", r"^stara lesna$", {"place": True}, "place_centre", 2000,
                "Stará Lesná (village centre; the SHMÚ station is not mapped)"),
    "hdcam19": ("sk", r"^bardejov$", {"place": True}, "place_centre", 3000, "Bardejov (town centre; the SHMÚ station is not mapped)"),
}


def build_be_rmi_kmi_webcams(out, lookups, countries):
    sid = "be_rmi_kmi_webcams"
    base = E.build_be_rmi_kmi_webcams(out)
    outcome = Outcome()
    if base["status"] != "integrated":
        return dict(base, outcome=outcome)
    when = E.when_of(out, sid, "webcams.html")
    for p in rmi_unplaced(E.read_raw(out, sid, "webcams.html"), E.read_raw(out, E.REFERENCE, "isd-history.csv")):
        spec = simple_spec(sid, f"{p['kind']}-{p['station']}", f"IRM/KMI {p['kind']} {p['label']}", "BE", "Belgium",
                           "https://www.meteo.be" + p["path"], E.RMI_INDEX, E.RMI_INDEX, when)
        if p["station"] not in RMI_FEATURES:
            outcome.add(spec, [], countries, why_none="station not in the feature table")
            continue
        area, rx, tag, role, minimum, feature = RMI_FEATURES[p["station"]]
        if lookup_missing(lookups, area):
            outcome.held += missing_lookup_outcome([spec], countries, area_request(AREAS[area])).held
            continue
        els = area_elements(lookups, area)
        if p["station"] == "wideumont":  # the station itself when OSM maps it, else the village centre
            station = find(els, name=WIDEUMONT_STATION[0], tag=WIDEUMONT_STATION[1])
            if station:
                add_feature(outcome, spec, countries, station, "IRM/KMI Wideumont station (OSM man_made=monitoring_station)",
                            minimum=150)
                continue
        add_feature(outcome, spec, countries, find(els, name=rx, tag=tag), feature, minimum=minimum, role=role)
    return extend(base, outcome, ["OpenStreetMap (ODbL 1.0)"],
                  "stations missing from the agency table placed at the OSM KMI station or the named place (webcam_places)")


def build_shmu_webcams(out, lookups, countries):
    sid = "shmu_webcams"
    base = E.build_shmu_webcams(out)
    outcome = Outcome()
    if base["status"] != "integrated":
        return dict(base, outcome=outcome)
    when = E.when_of(out, sid, "webkamery.html")
    for c in shmu_unplaced(E.read_raw(out, sid, "webkamery.html"), E.read_raw(out, E.REFERENCE, "isd-history.csv")):
        spec = simple_spec(sid, c["camera"], f"SHMÚ webkamera {c['name']}", "SK", "Slovensko",
                           f"{E.SHMU_PAGE}&kamera={c['camera']}", E.SHMU_PAGE, E.SHMU_PAGE, when)
        if c["camera"] not in SHMU_FEATURES:
            outcome.add(spec, [], countries, why_none="camera not in the feature table")
            continue
        area, rx, tag, role, minimum, feature = SHMU_FEATURES[c["camera"]]
        if lookup_missing(lookups, area):
            outcome.held += missing_lookup_outcome([spec], countries, area_request(AREAS[area])).held
            continue
        add_feature(outcome, spec, countries, find(area_elements(lookups, area), name=rx, tag=tag), feature, minimum=minimum,
                    role=role)
    return extend(base, outcome, ["OpenStreetMap (ODbL 1.0)"],
                  "cameras whose station is missing from the agency table placed at the named place (webcam_places)")


# ----- Finland: Port of Helsinki, Visit Finland streams, Turku Cathedral -----

HELSINKI_FEATURES = {  # slug -> (name regex, tags, minimum m, feature)
    "south-harbour": (r"^etelasatama$", {"natural": "bay"}, 500, "Eteläsatama (South Harbour basin)"),
    "vuosaari-harbour": (r"^vuosaaren satama$", {"landuse": True}, 300, "Vuosaaren satama (Vuosaari Harbour)"),
    "west-harbour": (r"^lansisatama$", {"landuse": True}, 300, "Länsisatama (West Harbour)"),
    "west-harbour-lt1": (r"^lansisatama$", {"landuse": True}, 300,
                         "Länsisatama (West Harbour; West Terminal 1 is not mapped on its own)"),
    "west-harbour-lt2": (r"^lansiterminaali 2$", {"amenity": "ferry_terminal"}, 150, "Länsiterminaali 2 (West Terminal 2)"),
    "west-harbour-p-area": (r"^lansisatama$", {"landuse": True}, 300,
                            "Länsisatama (West Harbour; the P area is not named on its own)"),
}


def build_port_of_helsinki_webcams(out, lookups, countries):
    sid = "port_of_helsinki_webcams"
    body = E.read_raw(out, sid, "web-camera-south-harbour.html")
    when = E.when_of(out, sid, "web-camera-south-harbour.html")
    els = area_elements(lookups, "helsinki")
    outcome = Outcome()
    for cam in helsinki_cameras(body):
        spec = simple_spec(sid, cam["slug"], f"Port of Helsinki web camera — {cam['label']}", "FI", "Uusimaa", cam["page"],
                           E.HELSINKI_PORT, E.HELSINKI_PORT, when)
        if cam["slug"] not in HELSINKI_FEATURES:
            outcome.add(spec, [], countries, why_none="camera not in the feature table")
            continue
        rx, tag, minimum, feature = HELSINKI_FEATURES[cam["slug"]]
        add_feature(outcome, spec, countries, find(els, name=rx, tag=tag), feature, minimum=minimum, allow_sea=True)
    return {"status": "integrated", "country": "FI", "outcome": outcome, "policy": new_source_policy(out, sid),
            "robots": "www.portofhelsinki.fi: page allowed by robots.txt and read in round 2",
            "changes": ["six camera pages from the page's camera menu, each at its named harbour/terminal (allow_sea: harbour features)"]}


VISITFINLAND_FEATURES = {  # first word of the headline -> (area, name regex, tags, role, minimum m, feature, allow_sea)
    "rovaniemi": ("rovaniemi", r"^joulupukin pajakila$", {"tourism": "theme_park"}, "named_feature", 300,
                  "Joulupukin Pajakylä (Santa Claus Village)", False),
    "koli": ("koli", r"^ukko-koli$", {"natural": "peak"}, "named_feature", 1500, "Ukko-Koli (the top of Koli)", False),
    "levi": ("levi", r"^levi$", {"natural": "peak"}, "named_feature", 1000, "Levi fell top (Levi Ski Resort)", False),
    "helsinki": ("helsinki", r"^kauppatori$", {"amenity": "marketplace"}, "named_feature", 200,
                 "Kauppatori (Helsinki Market Square)", True),
    "turku": ("turku", r"^turun satama$", {"landuse": "industrial"}, "named_feature", 500, "Turun satama (Port of Turku)", True),
    "kilpisjarvi": ("kilpisjarvi", r"^kilpisjarvi$", {"place": True}, "place_centre", 3000, "Kilpisjärvi (village centre)", False),
}


def build_visitfinland_live_streams(out, lookups, countries):
    sid = "visitfinland_live_streams"
    body = E.read_raw(out, sid, "live-from-finland.html")
    when = E.when_of(out, sid, "live-from-finland.html")
    outcome = Outcome()
    for s in visitfinland_streams(body):
        key = fold(s["headline"]).split(" ")[0]
        channel = "/channel/" in s["operator_url"]
        spec = simple_spec(sid, key, f"{s['headline']} — live stream by {s['operator']} (Visit Finland)", "FI", "Finland",
                           s["operator_url"] if channel else E.VISITFINLAND, E.VISITFINLAND, E.VISITFINLAND, when,
                           stream_operator=s["operator"], reference_url=None if channel else s["operator_url"])
        if key not in VISITFINLAND_FEATURES:
            outcome.add(spec, [], countries, why_none="stream place not in the feature table")
            continue
        area, rx, tag, role, minimum, feature, sea = VISITFINLAND_FEATURES[key]
        add_feature(outcome, spec, countries, find(area_elements(lookups, area), name=rx, tag=tag), feature, minimum=minimum,
                    role=role, allow_sea=sea)
    return {"status": "integrated", "country": "FI", "outcome": outcome, "policy": new_source_policy(out, sid),
            "robots": "www.visitfinland.com: page allowed by robots.txt and read in round 2",
            "changes": ["six streams; the link is the operator's YouTube channel credited by Visit Finland (Helsinki: the "
                        "credit links one video, so the record links Visit Finland's page)"]}


def build_turku_cathedral_tower_cams(out, lookups, countries):
    sid = "turku_cathedral_tower_cams"
    when = E.when_of(out, sid, "tower-camera.html")
    outcome = Outcome()
    spec = simple_spec(sid, "tower-camera", "Turku Cathedral tower camera (west and south views)", "FI", "Varsinais-Suomi",
                       E.TURKU_PAGE, E.TURKU_PAGE, E.TURKU_PAGE, when)
    qids = sorted(wikidata_wanted(lookups))
    coords = cached(out, "wikidata:" + qids[0]) if len(qids) == 1 else None
    if coords:
        claims = coords["entities"][qids[0]]["claims"].get("P625") or []
        value = claims[0]["mainsnak"]["datavalue"]["value"] if claims else None
        if value:
            plc = {"role": "named_feature", "lat": value["latitude"], "lng": value["longitude"], "source": f"wikidata:{qids[0]}",
                   "feature": "Turku Cathedral (Turun tuomiokirkko), the tower that carries the camera", "uncertainty_m": 100}
            outcome.add(spec, [option(plc, centre=(value["latitude"], value["longitude"]), max_km=1, expected_country="FI")],
                        countries)
            return {"status": "integrated", "country": "FI", "outcome": outcome,
                    "policy": new_source_policy(out, sid, datasets=("Wikidata (CC0 1.0)",)),
                    "robots": "turunseurakunnat.fi: page allowed by robots.txt and read in round 2; www.wikidata.org Special:EntityData",
                    "changes": [f"one record at the Wikidata position (P625) of Turku Cathedral ({qids[0]}, found through the "
                                "OSM wikidata tag of the cathedral)"]}
    outcome.add(spec, [], countries, why_none="no Wikidata position read for Turku Cathedral")
    return {"status": "held", "country": "FI", "outcome": outcome, "policy": None}


# ----- Kiel, Italian resorts -----

KIEL_FEATURES = {"Schwedenkai": (r"^schwedenkai$", {"landuse": True}, 200, "Schwedenkai (Stena Line terminal quay)"),
                 "Hafenhaus": (r"^hafenhaus$", {"building": True}, 100, "HafenHaus (port office building at the Schwedenkai)")}


def build_port_of_kiel_webcams(out, lookups, countries):
    sid = "port_of_kiel_webcams"
    body = E.read_raw(out, sid, "webcam.html")
    when = E.when_of(out, sid, "webcam.html")
    outcome = Outcome()
    for name in kiel_cameras(body):
        if name not in KIEL_FEATURES:  # 'Kieler Förde' is the feratel camera already in the catalogue
            continue
        spec = simple_spec(sid, fold(name), f"PORT OF KIEL — Webcam {name}", "DE", "Schleswig-Holstein", E.KIEL_PAGE, E.KIEL_PAGE,
                           E.KIEL_PAGE, when)
        rx, tag, minimum, feature = KIEL_FEATURES[name]
        add_feature(outcome, spec, countries, find(area_elements(lookups, "kiel"), name=rx, tag=tag), feature, minimum=minimum,
                    allow_sea=True)
    return {"status": "integrated", "country": "DE", "outcome": outcome, "policy": new_source_policy(out, sid),
            "robots": "www.portofkiel.com: page allowed by robots.txt and read in round 2",
            "changes": ["two records (Schwedenkai, HafenHaus) linking webcam.html; 'Kieler Förde' left out (feratel 3375 already "
                        "in the catalogue)"]}


IT_RESORTS = {  # source -> (area, name regex, tags, role, minimum m, feature, record id, record name, region)
    "it_ski_bormio": ("bormio", r"^bormio 2000$", {"aerialway": "station"}, "named_feature", 3000,
                      "Bormio 2000 lift station (the page's views: Bormio 2000, Cima Bianca, Le Motte)", "bormio-ski-webcams",
                      "Bormio Ski webcams (Bormio 2000, Cima Bianca, Le Motte)", "Lombardia"),
    "it_ski_campiglio_apt": ("campiglio", r"^madonna di campiglio$", {"place": True}, "place_centre", 5000,
                             "Madonna di Campiglio (village centre; the page also shows Pinzolo and Folgarida)",
                             "campiglio-webcams", "Madonna di Campiglio webcams (APT page; also Pinzolo, Folgarida)", "Trentino"),
    "it_ski_cervinia": ("cervinia", r"^breuil-cervinia$", {"place": True}, "place_centre", 5000,
                        "Breuil-Cervinia (village centre; the views reach Plan Maison and Plateau Rosa)", "cervinia-webcams",
                        "Breuil-Cervinia webcams (Cervino S.p.A.)", "Valle d'Aosta"),
}


def resort_builder(sid):
    def build(out, lookups, countries):
        m = NEW_SOURCES[sid]
        when = E.when_of(out, sid, m["page_file"])
        area, rx, tag, role, minimum, feature, rid, rname, region = IT_RESORTS[sid]
        outcome = Outcome()
        spec = simple_spec(sid, rid, rname, "IT", region, m["url"], m["url"], m["url"], when)
        add_feature(outcome, spec, countries, find(area_elements(lookups, area), name=rx, tag=tag), feature, minimum=minimum,
                    role=role)
        return {"status": "integrated", "country": "IT", "outcome": outcome, "policy": new_source_policy(out, sid),
                "robots": "page allowed by robots.txt and read in round 2",
                "changes": ["one resort-level record linking the official webcam page"]}
    return build


build_it_ski_bormio = resort_builder("it_ski_bormio")
build_it_ski_campiglio_apt = resort_builder("it_ski_campiglio_apt")
build_it_ski_cervinia = resort_builder("it_ski_cervinia")

# ======================================================================================
# Sources whose features come from the "extra" (lifts) and "geom" (streets, bridge, boundary) lookups
# ======================================================================================


def lookup_missing(lookups, area):
    return lookups.get(area_request(AREAS[area])) is None


def missing_lookup_outcome(spec_list, countries, request):
    outcome = Outcome()
    for spec in spec_list:
        outcome.add(spec, [], countries, why_none=f"Overpass lookup '{request}' failed three times (overpass.kumi.systems answered "
                                                  "HTTP 504) and no Wikidata item of the feature is known without it; re-run the "
                                                  "lookup stage when the server answers")
    return outcome


# ----- Plzeň: squares, streets and the Makro junction -----

PLZEN_FEATURES = {  # camera -> (name regex on folded names, preferred tag (when mapped), minimum m, feature)
    1: (r"^namesti republiky$", "place", 150, "náměstí Republiky (square)"),
    2: (r"^sady petatricatniku$", "highway", 150, "sady Pětatřicátníků (park ring street)"),
    3: (r"^mlynska strouha$", None, 300, "Mlýnská strouha (mill race)"),
    4: (r"^rokycanska( trida)?$", "highway", 150, "Rokycanská třída (avenue)"),
    5: (r"^namesti milady horakove$", "place", 150, "náměstí Milady Horákové (square)"),
}
PLZEN_JUNCTION = {8: ("folmavska", ("domazlicka", "regensburska")), 12: ("folmavska", ("domazlicka", "regensburska"))}
PLZEN_SKIPPED = {6: "Škoda sport park: already in the catalogue as an OpenStreetMap link to the same city page (register)"}


def way_nodes(el):
    """(node id, lat, lng) of a way from an `out geom` answer."""
    return [(nid, g["lat"], g["lon"]) for nid, g in zip(el.get("nodes") or [], el.get("geometry") or []) if g]


def junction(elements, first, seconds, landmark, within_km=0.6):
    """Nodes shared by a way named `first` and a way named one of `seconds`, within within_km of the landmark;
    one group of such nodes -> (node id, lat, lng), else None (rule 3: never guess a corner)."""
    ways_a = [el for el in elements if el["type"] == "way" and any(fold(n) == first for n in names(el))]
    ways_b = [el for el in elements if el["type"] == "way" and any(fold(n) in seconds for n in names(el))]
    nodes_a = {nid: (lat, lng) for w in ways_a for nid, lat, lng in way_nodes(w)}
    shared = sorted({nid for w in ways_b for nid, _, _ in way_nodes(w) if nid in nodes_a})
    near = [(nid, nodes_a[nid]) for nid in shared if dist_km(nodes_a[nid], landmark) <= within_km]
    if not near:
        return None
    pts = [p for _, p in near]
    if max(dist_km(a, b) for a in pts for b in pts) > 0.25:
        return None
    nid, pt = min(near, key=lambda r: (dist_km(r[1], landmark), r[0]))
    return nid, pt[0], pt[1]


def build_plzen_city_webcams(out, lookups, countries):
    sid = "plzen_city_webcams"
    when = E.when_of(out, sid, "webkamery.html")
    cams = plzen_cameras(E.read_raw(out, sid, "webkamery.html"))
    specs = {c["camera"]: simple_spec(sid, f"kamera{c['camera']}", f"Plzeň webcam — {c['label']}", "CZ", "Plzeňský kraj",
                                      E.PLZEN_PAGE, E.PLZEN_PAGE, E.PLZEN_PAGE, when) for c in cams if c["camera"] not in PLZEN_SKIPPED}
    policy = new_source_policy(out, sid)
    if lookup_missing(lookups, "plzen"):
        return {"status": "held", "country": "CZ", "outcome": missing_lookup_outcome(specs.values(), countries, "geom"),
                "policy": policy}
    els = area_elements(lookups, "plzen")
    city = find(els, name=r"^plzen$", tag={"place": "city"})
    centre = el_point(city[0]) if city else None
    makro = find(els, name=r"makro", tag={"shop": True})
    outcome = Outcome()
    for cam in cams:
        if cam["camera"] in PLZEN_SKIPPED:
            continue
        spec = specs[cam["camera"]]
        if cam["camera"] in PLZEN_JUNCTION:
            first, seconds = PLZEN_JUNCTION[cam["camera"]]
            hit = junction(els, first, seconds, el_point(makro[0])) if len(makro) == 1 else None
            if not hit:
                outcome.add(spec, [], countries, why_none="the Makro junction is not identified by one shared node of the named streets")
                continue
            nid, lat, lng = hit
            plc = {"role": "named_feature", "lat": lat, "lng": lng, "source": f"osm:node/{nid}", "uncertainty_m": 150,
                   "feature": "junction of Folmavská and Domažlická/Regensburská by the Makro store ('křižovatka u Makra')"}
            outcome.add(spec, [option(plc, centre=centre or (lat, lng), max_km=8, expected_country="CZ")], countries)
            continue
        if cam["camera"] not in PLZEN_FEATURES:
            outcome.add(spec, [], countries, why_none="camera label not in the feature table")
            continue
        rx, prefer, minimum, feature = PLZEN_FEATURES[cam["camera"]]
        rows = [el for el in find(els, name=rx) if el["type"] != "node" and not tags(el).get("railway")]
        if prefer and any(prefer in tags(el) for el in rows):
            preferred = [el for el in rows if prefer in tags(el)]
            # one feature: the preferred element(s) stand for the place; the rest only widens the uncertainty
            found, n = one(preferred)
            if found:
                spread = max(dist_km(el_point(found[0]), el_point(el)) * 1000 + el_extent_m(el) for el in rows)
                outcome.add(spec, [option(placement(found[0], feature, minimum=minimum, extra_m=max(found[1], spread - el_extent_m(found[0]))),
                                          centre=centre or el_point(found[0]), max_km=8, expected_country="CZ")], countries)
                continue
        add_feature(outcome, spec, countries, rows, feature, minimum=minimum, centre=centre, max_km=8)
    return {"status": "integrated", "country": "CZ", "outcome": outcome, "policy": policy,
            "robots": "www.plzen.eu: page allowed by robots.txt and read in round 2",
            "changes": ["7 city cameras (the HTTP-only players are not linked; every record links the city's HTTPS page)",
                        PLZEN_SKIPPED[6]]}


# ----- PKL: upper station of each venue's lift -----

PKL_SUMMITS = {  # venue -> (summit name regex on folded names, feature)
    "kasprowy-wierch": r"^kasprowy wierch$", "gubalowka": r"^gubalowka$", "jaworzyna-krynicka": r"^jaworzyna( krynicka)?$",
    "palenica": r"^palenica$", "gora-zar": r"^(gora )?zar$", "mosorny-gron": r"^mosorny gron$", "solina": r"^jawor$",
}
PKL_BOXES = dict(zip(("kasprowy-wierch", "gubalowka", "jaworzyna-krynicka", "palenica", "gora-zar", "mosorny-gron", "solina"),
                     range(7)))


def in_box(el, box):
    pt = el_point(el)
    return pt and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]


def build_pkl_webcams(out, lookups, countries):
    sid = "pkl_webcams"
    when = E.when_of(out, sid, "kamery-online.html")
    venues, others = pkl_venues(E.read_raw(out, sid, "kamery-online.html"))
    specs = {v["slug"]: simple_spec(sid, v["slug"], f"PKL {v['name']} — kamery online" + (f" ({v['cameras']} cameras)" if v["cameras"] else ""),
                                    "PL", "Małopolska" if v["slug"] != "solina" else "Podkarpacie", v["page"], E.PKL_LIST, E.PKL_LIST,
                                    when) for v in venues}
    for v in venues:
        if v["slug"] == "gora-zar":
            specs[v["slug"]]["region"] = "Śląsk"
    policy = new_source_policy(out, sid)
    changes = [f"tiles linking elsewhere left out: {[o['name'] for o in others]}"] if others else []
    if lookup_missing(lookups, "pkl"):
        return {"status": "held", "country": "PL", "outcome": missing_lookup_outcome(specs.values(), countries, "extra"),
                "policy": policy, "changes": changes}
    els = area_elements(lookups, "pkl")
    outcome = Outcome()
    for v in venues:
        spec = specs[v["slug"]]
        box = AREAS["pkl"]["boxes"][PKL_BOXES[v["slug"]]]
        local = [el for el in els if in_box(el, box)]
        summits = [el for el in find(local, tag={"natural": "peak"}) if any(re.search(PKL_SUMMITS[v["slug"]], fold(n)) for n in names(el))]
        stations = [el for el in local if tags(el).get("aerialway") == "station"
                    or (tags(el).get("railway") == "station" and tags(el).get("station") == "funicular")]
        if len(summits) != 1:
            outcome.add(spec, [], countries, why_none=f"{len(summits)} summits named for the venue in OSM")
            continue
        top = el_point(summits[0])
        near = nearest(stations, top, 1.5)
        if near:
            st = near[0][1]
            feature = f"{tags(st).get('name') or v['name']} — upper lift station (OSM, nearest station to the {v['name']} summit)"
            plc = placement(st, feature, minimum=300)
        else:
            plc = placement(summits[0], f"{tags(summits[0]).get('name')} summit (no lift station mapped within 1.5 km)",
                            minimum=500)
        outcome.add(spec, [option(plc, centre=top, max_km=2, expected_country="PL")], countries)
    return {"status": "integrated", "country": "PL", "outcome": outcome, "policy": policy,
            "robots": "www.pkl.pl: page allowed by robots.txt and read in round 2",
            "changes": ["one record per venue camera page, at the venue lift's upper station"] + changes}


# ----- Bansko: the named stations, meadows and summits of the ski area -----

BANSKO_FEATURES = {  # slug -> (name regex on loose names, preferred tag keys, minimum m, feature)
    "bansko": (r"^bansko$|^gondola|^kabina", ("aerialway",), 300, "Bansko gondola lower station"),
    "chalin": (r"^calin valog", ("aerialway", "place"), 300, "Chalin Valog (Чалин валог)"),
    "bunderitsa": (r"^banderis(ka|ka polana)|^banderica|^bunderi", ("aerialway", "place", "tourism"), 300,
                   "Banderishka polyana (Бъндеришка поляна)"),
    "shiligarnik": (r"^siligarnik", ("aerialway", "place"), 300, "Shiligarnik (Шилигарник)"),
    "platoto": (r"^plato", ("place", "aerialway"), 300, "Plato (Платото)"),
    "todorka": (r"^todorka", ("aerialway", "natural"), 300, "Todorka (Тодорка)"),
}


def build_bansko_ski_webcams(out, lookups, countries):
    sid = "bansko_ski_webcams"
    when = E.when_of(out, sid, "home.html")
    cams = bansko_cameras(E.read_raw(out, sid, "home.html"))
    specs = {c["slug"]: simple_spec(sid, c["slug"], f"Bansko ski area webcam — {c['label']}", "BG", "Blagoevgrad", c["page"],
                                    E.BANSKO_HOME, E.BANSKO_HOME, when) for c in cams}
    policy = new_source_policy(out, sid)
    if lookup_missing(lookups, "bansko"):
        return {"status": "held", "country": "BG", "outcome": missing_lookup_outcome(specs.values(), countries, "extra"),
                "policy": policy}
    els = area_elements(lookups, "bansko")
    town = find(els, name=r"^bansko$", place=True)
    centre = el_point(town[0]) if town else None
    outcome = Outcome()
    for cam in cams:
        spec = specs[cam["slug"]]
        rx, keys, minimum, feature = BANSKO_FEATURES.get(cam["slug"], (None, (), 0, None))
        rows = []
        for key in keys:  # the first kind of feature that has matches decides
            rows = [el for el in find(els, name=rx) if key in tags(el)]
            if rows:
                break
        add_feature(outcome, spec, countries, rows, feature or cam["label"], minimum=minimum, centre=centre, max_km=12)
    return {"status": "integrated", "country": "BG", "outcome": outcome, "policy": policy,
            "robots": "www.banskoski.com: page allowed by robots.txt and read in round 2",
            "changes": ["six webcam pages placed at the named lift station, meadow or summit"]}


# ----- Øresund: the two pylons of the cable-stayed span; the boundary line decides DK/SE -----

def side_of_boundary(boundary_ways, point):
    """'east' or 'west' of the Denmark–Sweden boundary at the point's latitude (the line runs north–south here)."""
    lat, lng = point
    for w in boundary_ways:
        geo = w.get("geometry") or []
        for a, b in zip(geo, geo[1:]):
            if a and b and min(a["lat"], b["lat"]) <= lat <= max(a["lat"], b["lat"]) and a["lat"] != b["lat"]:
                x = a["lon"] + (lat - a["lat"]) * (b["lon"] - a["lon"]) / (b["lat"] - a["lat"])
                return "east" if lng > x else "west"
    return None


def build_oresundsbron_pylon_cams(out, lookups, countries):
    sid = "oresundsbron_pylon_cams"
    when = E.when_of(out, sid, "pylonkamera.html")
    cams = oresund_cameras(E.read_raw(out, sid, "pylonkamera.html"))
    specs = {key: simple_spec(sid, key, f"Øresundsbron — {label}", "SE", "Öresund", E.ORESUND_PAGE, E.ORESUND_PAGE,
                              E.ORESUND_PAGE, when) for key, label in cams}
    policy = new_source_policy(out, sid)
    if lookup_missing(lookups, "oresund"):
        return {"status": "held", "country": "SE", "outcome": missing_lookup_outcome(specs.values(), countries, "geom"),
                "policy": policy}
    els = area_elements(lookups, "oresund")
    pylons = [el for el in els if tags(el).get("bridge:support") == "pylon"]  # each pylon: two mapped legs
    boundary = [el for el in els if tags(el).get("boundary") == "administrative" and tags(el).get("admin_level") == "2"]
    outcome = Outcome()
    groups = [group_feature(g, el_point(g[0])) for g in clusters(pylons, link_km=0.2)]
    ordered = sorted(groups, key=lambda g: el_point(g[0])[1])  # west to east
    for key, _ in cams:
        spec = specs[key]
        if len(ordered) != 2:
            outcome.add(spec, [], countries, why_none=f"{len(ordered)} bridge pylons mapped in OSM (two expected)")
            continue
        el, spread = ordered[1] if key == "pyloneast" else ordered[0]
        side = side_of_boundary(boundary, el_point(el))
        if side is None:
            outcome.add(spec, [], countries, why_none="the Denmark–Sweden boundary line does not cross the pylon's latitude")
            continue
        spec["country"] = "SE" if side == "east" else "DK"
        plc = placement(el, f"Øresund Bridge {'east' if key == 'pyloneast' else 'west'} pylon ({'Swedish' if side == 'east' else 'Danish'} "
                            "side of the OSM Denmark–Sweden boundary)", minimum=100, extra_m=spread)
        outcome.add(spec, [option(plc, centre=el_point(el), max_km=1, allow_sea=True, expected_country=spec["country"])], countries)
    countries_used = sorted({x["country"] for x in outcome.items}) or ["SE"]
    return {"status": "integrated", "country": "/".join(countries_used), "outcome": outcome,
            "policy": new_source_policy(out, sid, countries=countries_used),
            "robots": "www.oresundsbron.com: page allowed by robots.txt and read in round 2",
            "changes": ["two pylon cameras linking the operator's pylon-camera page (the /cams/ targets are not linked: their media type "
                        "was not read)"]}

# ======================================================================================
# Build stage
# ======================================================================================

COUNTRIES_FILE = SCRATCH_OPEN_DATA / "ne_10m_admin_0_countries.geojson"
RETIRED = {"md_border_police_webcams_ukraine_facing": "its 18 pages are records of md_border_police_webcams (hold lifted by the user)"}
KEPT_HELD = {
    "ru_gazprom_polyana_webcams": "sanctions exposure of the operator (Gazprom group) not assessed",
    "dwd_webcams (Hamburg-SO, Hamburg-SW views)": "camera site not published (Fuhlsbüttel or the Seewetteramt St. Pauli)",
    "andorra_mobilitat": "no camera list",
    "arpa_fvg_webcam_directory": "robots.txt redirects to plain HTTP (treated as disallow)",
    "bafg_deutsches_eck_webcam": "host refused (HTTP 403)",
}


def build_sources():
    return {
        "md_border_police_webcams": build_md_border_police_webcams,
        "plzen_city_webcams": build_plzen_city_webcams,
        "pkl_webcams": build_pkl_webcams,
        "bansko_ski_webcams": build_bansko_ski_webcams,
        "port_of_helsinki_webcams": build_port_of_helsinki_webcams,
        "port_of_kiel_webcams": build_port_of_kiel_webcams,
        "visitfinland_live_streams": build_visitfinland_live_streams,
        "oresundsbron_pylon_cams": build_oresundsbron_pylon_cams,
        "turku_cathedral_tower_cams": build_turku_cathedral_tower_cams,
        "it_ski_bormio": build_it_ski_bormio,
        "it_ski_campiglio_apt": build_it_ski_campiglio_apt,
        "it_ski_cervinia": build_it_ski_cervinia,
        "tirol_luft_livebilder": build_tirol_luft_livebilder,
        "mk_state_roads_video_kameri": build_mk_state_roads_video_kameri,
        "be_rmi_kmi_webcams": build_be_rmi_kmi_webcams,
        "shmu_webcams": build_shmu_webcams,
    }


def held_policy(sid, result):
    m = NEW_SOURCES.get(sid, {})
    rows = result["outcome"].held
    reasons = sorted({r["reason"] for r in rows})
    reason = (f"no record could be placed ({len(rows)} records): " + "; ".join(reasons)) if rows else "no records"
    return E.held(sid, m.get("name", sid), m.get("url", ""), reason[:1500],
                  "an official position, or an open-data feature that identifies the named place and passes the checks",
                  m.get("evidence", []), result.get("country"))


def write_result(out, sid, result):
    outcome = result["outcome"]
    items = list(result.get("base_items", [])) + outcome.items
    policy_file = E.policy_path(out, sid)
    if not items:
        write_json(policy_file, {sid: held_policy(sid, result)})
        return None, policy_file
    if outcome.held:
        result["policy"]["source"]["not_placed"] = [{"id": r["id"], "reason": r["reason"]} for r in outcome.held]
    write_json(policy_file, {sid: result["policy"]})
    F.write_catalog(Path(out) / f"{sid}.json", sources=[sid], items=items)
    return items, policy_file


def retire_fragments(out):
    moved = []
    for sid, why in RETIRED.items():
        src = Path(out) / "policies" / f"{sid}.json"
        if src.exists():
            dst = Path(out) / "unused" / f"{sid}.retired.json.txt"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            src.unlink()
        dst = Path(out) / "unused" / f"{sid}.retired.json.txt"
        if dst.exists():
            moved.append({"id": sid, "moved_to": dst.relative_to(out).as_posix(), "why": why})
    return moved


def build_stage(out, only=None, countries_file=COUNTRIES_FILE):
    out = Path(out)
    countries = P.load_countries(countries_file)
    lookups = load_lookups(out)
    if lookups.get("bb") is None:
        raise SystemExit("the first Overpass lookup is not cached: run the lookup stage first")
    report = {"family": FAMILY, "generated_at": F.now(), "contract": "CONTRACT-PLACES.md (placement round 2026-11-14)",
              "sources": [], "held_records": [], "retired_fragments": [], "kept_held": KEPT_HELD, "hosts_refused": [],
              "lookups": lookup_summary(out), "coordinator_notes": COORDINATOR_NOTES}
    for sid, build in build_sources().items():
        if only and sid not in only:
            continue
        result = build(out, lookups, countries)
        outcome = result.setdefault("outcome", Outcome())
        items, policy_file = write_result(out, sid, result)
        base = len(result.get("base_items", []))
        row = {"id": sid, "country": result.get("country"), "status": "integrated" if items else "held",
               "policy_file": policy_file.relative_to(out).as_posix(), "records": len(items or []),
               "records_official_position": base, "placed": outcome.summary(), "page_only": len(items or []), "viewable": 0,
               "input_file": f"{sid}.json" if items else None, "check": None,
               "fallbacks": outcome.fallbacks, "not_placed": [{"id": r["id"], "reason": r["reason"], "tried": r["tried"]}
                                                              for r in outcome.held]}
        row.update({k: result[k] for k in ("robots", "changes", "match_notes") if result.get(k)})
        report["sources"].append(row)
        report["held_records"] += [{"source": sid, **r} for r in outcome.held]
    if not only:
        report["retired_fragments"] = retire_fragments(out)
    failed = [e for e in (cached_log(out) or {}).get("lookups", []) if e.get("error")]
    for request in [r for r in REQUESTS if lookups.get(r) is None]:
        errors = [e["error"].split(" for ")[0] for e in failed if e["lookup"] == f"overpass:{request}"]
        report["hosts_refused"].append({"host": "overpass.kumi.systems", "lookup": request, "attempts": len(errors),
                                        "reason": "; ".join(errors) or "not attempted"})
    report["totals"] = {
        "sources": len(report["sources"]),
        "integrated_sources": sum(r["status"] == "integrated" for r in report["sources"]),
        "records": sum(r["records"] for r in report["sources"]),
        "placed": dict(collections.Counter(role for r in report["sources"] for role, v in r["placed"].items()
                                           for _ in range(v["records"]))),
        "held_records": len(report["held_records"])}
    write_json(out / "reports" / f"{FAMILY}.json", report)
    print(json.dumps(report["totals"], ensure_ascii=False))
    for r in report["sources"]:
        print(r["id"], r["status"], r["records"], json.dumps(r["placed"]), len(r["not_placed"]), "not placed")
    return report


def lookup_summary(out):
    log = cached_log(out)
    return {"overpass": OVERPASS_NOTE, "requests": [{k: e.get(k) for k in ("url", "status", "bytes", "started_at")}
                                                     for e in (log or {}).get("requests", [])][:20],
            "cache": f"raw/places/{FAMILY}/"}


def cached_log(out):
    path = cache_dir(out) / "lookup_log.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


COORDINATOR_NOTES = [
    "scripts/webcam_source_policies.json still holds the round-2 held entry md_border_police_webcams_ukraine_facing: "
    "merge_policies.py never deletes, so remove it by hand (its fragment is retired to unused/).",
    "collect_europe2.py build no longer writes the 17 sources listed in its BUILT_BY_PLACES (this collector owns them).",
    "Natural Earth puts the Moldovan villages Grimăncăuți and Mirnoe (Taraclia) in Ukraine and several Moldovan posts on "
    "the Prut in Romania: those crossings fall back to the village centre (when it is inside Natural Earth's Moldova) or stay held.",
    "plzen kamera4 'Rokycanská třída' is placed on the avenue with its full extent (about 3 km): the camera's point on it is unknown.",
]
OVERPASS_NOTE = ("Two Overpass requests to overpass.kumi.systems (GET, robots.txt read first, PoliteClient): every candidate of "
                 "every area at once (out bb / out geom), matched offline; the Wikidata entity of Turku Cathedral read through "
                 "Special:EntityData. All cached; rebuilds make no request.")


def wikidata_wanted(lookups):
    """Wikidata items to read: the landmarks placed from Wikidata (P625), found through the OSM wikidata tag."""
    wanted = set()
    for el in area_elements(lookups, "turku"):
        if named(el, r"turun tuomiokirkko|turku cathedral") and re.fullmatch(r"Q\d+", tags(el).get("wikidata", "")):
            wanted.add(tags(el)["wikidata"])
    return wanted


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output folder (webcam-inputs-2026-11)")
    ap.add_argument("stage", choices=("lookup", "build"))
    ap.add_argument("--only", help="lookup: bb and/or geom; build: comma-separated source ids")
    args = ap.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None
    if args.stage == "lookup":
        lookup_stage(args.out, only)
    else:
        build_stage(args.out, only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
