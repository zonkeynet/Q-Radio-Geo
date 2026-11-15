#!/usr/bin/env python3
"""Placement round (family places_world): cameras held or left out ONLY because the operator publishes no position.

Placement rules (CONTRACT-PLACES): an official position first (operator page/list/agency table: normal roles);
else the exact named feature in an open dataset (OSM node/way, OurAirports, Wikidata P625) -> named_feature;
else the town/place centre -> place_centre (last resort). Every placed record goes through webcam_places.place()
and webcam_places.check(); failing records stay out and are reported.

  python scripts/collect_places_world.py --out <SCRATCH>/webcam-inputs-2026-11 [--offline] [--lookups-only]

--offline uses only pages already saved under raw/ and lookups already cached under raw/places/places_world/.
"""
from __future__ import annotations

# One Overpass query per area (bounding boxes; Kenya and Nova Scotia split into regions as "area:part", merged into
# one area); candidates are matched locally. The text is the cache key: do not reformat.
OVERPASS = {
    "jerusalem": '[out:json][timeout:60];nwr(around:300,31.7767,35.2345)["name:en"~"Western Wall"];out tags bb;',
    "karbala": '[out:json][timeout:60];nwr(around:800,32.6164,44.0324)["amenity"="place_of_worship"];out tags bb;',
    "mayapur": '[out:json][timeout:60][bbox:23.41,88.375,23.44,88.405];nwr["amenity"="place_of_worship"];out tags bb;',
    "maunakea": '[out:json][timeout:60][bbox:19.81,-155.49,19.84,-155.46];'
                '(nwr["man_made"~"^(telescope|observatory)$"];nwr["name"~"Submillimeter",i];);out tags bb;',
    "shymbulak": '[out:json][timeout:60][bbox:43.08,77.03,43.18,77.13];nwr["landuse"="winter_sports"];out tags bb;',
    "hongkong": '[out:json][timeout:90][bbox:22.15,113.83,22.57,114.44];'
                'nwr["name:en"~"^(Elegantia College|International Commerce Centre|Hong Kong Maritime Museum|Victoria Peak|'
                'The Peak|German Swiss International School|Sai Wan Ho|Tai Lam Chung|Cheung Sha|Upper Cheung Sha|'
                'Lower Cheung Sha)"];out tags bb;',
    "macau": '[out:json][timeout:90][bbox:22.10,113.52,22.22,113.61];(node["place"]["name"];'
             'nwr["name"~"友誼大橋|西灣大橋|澳門大橋|圓形地|前地|廣場|口岸|碼頭|停車場|隧道|威尼斯人|捐血中心|海灣花園|港珠澳|人工島"];);'
             'out tags bb;',
    "novascotia:places": '[out:json][timeout:120][bbox:43.3,-66.5,47.1,-59.6];'
                         '(node["place"~"^(city|town|village|hamlet|locality|suburb|neighbourhood|quarter|isolated_dwelling)$"];'
                         'node["highway"="motorway_junction"];);out body;',
    "novascotia:features": '[out:json][timeout:120][bbox:43.3,-66.5,47.1,-59.6];'
                           'nwr["name"~"Causeway|Seal Island Bridge|Kelly.s Mountain|Cape Smokey|Weavers Mountain|Pottle Lake",i]'
                           '[!"highway"];out tags bb;',
    "novascotia:roads": '[out:json][timeout:90][bbox:45.5,-62.9,46.4,-60.4];'
                        'way["highway"]["name"~"^(Canso Causeway|Seal Island Bridge|Pictou Causeway)$"];out tags bb;',
    "kenya:nairobi": '[out:json][timeout:90][bbox:-1.7,36.4,-1.0,37.0];'
                     '(node["place"]["name"~"^(Hardy|Karen|Champagne Ridge|Saikeri|Tigoni|Limuru)$",i];'
                     'nwr["name"~"Storage Central|Tulip House|Champagne Ridge|Riara",i];);out tags bb;',
    "kenya:central": '[out:json][timeout:90][bbox:-0.6,36.2,0.8,37.8];'
                     '(node["place"]["name"~"^(Nyeri|Meru|Nanyuki|Nyahururu)$",i];'
                     'nwr["name"~"Mogwooni|Mugwooni|Safari Club|Lewa House|Ezri|Loisaba|Suyian",i];);out tags bb;',
    "kenya:rift": '[out:json][timeout:90][bbox:-1.4,35.0,-0.1,36.5];'
                  '(node["place"]["name"~"^(Kabarak|Molo|Narok|Aitong|Lemek)$",i];'
                  'nwr["name"~"Green Park|Agventure|Kudenga|Lemek",i];);out tags bb;',
    "kenya:south": '[out:json][timeout:90][bbox:-3.8,37.2,-2.0,41.1];'
                   '(node["place"]["name"~"^(Malindi|Kilifi)$",i];'
                   'nwr["name"~"Tawi|Ithumba|Manda Bay|Ras Kitoka",i];);out tags bb;',
    "costarica": '[out:json][timeout:90][bbox:9.8,-85.6,11.0,-83.6];'
                 '(nwr["natural"~"^(volcano|peak|crater)$"]["name"~"Po[aá]s|Turrialba|Iraz[uú]|Rinc[oó]n",i];'
                 'nwr["name"~"Chahuites|Curuband[eé]|Gavil[aá]n|Sensoria",i];);out tags bb;',
}

import argparse  # noqa: E402
import collections  # noqa: E402
import html as htmllib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from pathlib import Path  # noqa: E402
import re  # noqa: E402
import statistics  # noqa: E402
import sys  # noqa: E402
from urllib.parse import quote, urljoin  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as W  # noqa: E402
import webcam_places as P  # noqa: E402
import collect_world2 as W2  # noqa: E402
import collect_apac_pages as AP  # noqa: E402

FAMILY = "places_world"
REVIEWED_AT = "2026-11-14"
OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright"
OURAIRPORTS = "https://ourairports.com/data/"
NAME_KEYS = ("name", "name:en", "name:pt", "name:zh", "name:zh-Hant", "name:ar", "alt_name", "official_name", "old_name")


class Offline(Exception):
    """A page or lookup is not saved/cached and --offline forbids the request."""


# ================================================================= small pure helpers
def decoded(body):
    return body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body


def text_of(fragment):
    fragment = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", decoded(fragment))
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def feature_point(el):
    """(lat, lng, extent_m) of an Overpass element: a node's position, or the centre of a way/relation's
    bounding box (Overpass 'center' is the same bbox centre) with its half-diagonal as the extent."""
    if el.get("type") == "node" and "lat" in el:
        return el["lat"], el["lon"], 0.0
    b = el.get("bounds")
    if not b:
        return None
    lat, lng = (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2
    dy = (b["maxlat"] - b["minlat"]) * 111_320 / 2
    dx = (b["maxlon"] - b["minlon"]) * 111_320 * math.cos(math.radians(lat)) / 2
    return lat, lng, math.hypot(dx, dy)


def osm_ref(el):
    return f"osm:{el['type']}/{el['id']}"


def names_of(el):
    tags = el.get("tags", {})
    return [tags[k] for k in NAME_KEYS if tags.get(k)]


def km(a, b):
    return P.distance_km(a[0], a[1], b[0], b[1])


def round_up(value, step=50):
    return int(math.ceil(max(value, 1) / step) * step)


def find_osm(elements, pattern, *, near=None, max_km=None, where=None):
    """Elements whose name (any NAME_KEYS) matches pattern, optionally within max_km of near and passing where(tags)."""
    out = []
    for el in elements:
        if pattern is not None and not any(re.search(pattern, n, re.I) for n in names_of(el)):
            continue
        if where and not where(el.get("tags", {})):
            continue
        pt = feature_point(el)
        if not pt:
            continue
        if near and max_km is not None and km(pt, near) > max_km:
            continue
        out.append(el)
    return out


def pick_one(candidates, cluster_m=300):
    """One feature, or (None, reason). Elements within cluster_m of each other are one feature mapped twice (a node
    and its building): the one with the largest extent wins. Farther apart: ambiguous (rule 3)."""
    if not candidates:
        return None, "no matching feature in the open dataset"
    pts = [feature_point(c) for c in candidates]
    spread = max(km(p, q) for p in pts for q in pts) * 1000
    if spread > cluster_m:
        return None, f"{len(candidates)} candidates up to {spread:.0f} m apart (ambiguous)"
    best = max(range(len(candidates)), key=lambda i: (pts[i][2], candidates[i]["type"] != "node"))
    return candidates[best], None


def merged(candidates, max_extent_m):
    """One feature mapped as several pieces (a bridge's spans): the union of their bounds, or (None, reason)."""
    boxes = []
    for el in candidates:
        if el.get("type") == "node":
            boxes.append((el["lat"], el["lon"], el["lat"], el["lon"]))
        elif el.get("bounds"):
            b = el["bounds"]
            boxes.append((b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]))
    if not boxes:
        return None, "no matching feature in the open dataset"
    union = {"minlat": min(b[0] for b in boxes), "minlon": min(b[1] for b in boxes),
             "maxlat": max(b[2] for b in boxes), "maxlon": max(b[3] for b in boxes)}
    lat, lng, extent = feature_point({"type": "way", "bounds": union})
    if extent > max_extent_m:
        return None, f"{len(candidates)} pieces spread over {extent:.0f} m (more than one feature?)"
    main = max(candidates, key=lambda el: (feature_point(el) or (0, 0, 0))[2])
    return {"type": main["type"], "id": main["id"], "tags": main.get("tags", {}), "bounds": union}, None


def dms_text(value):
    """'2°13'1.75"S' or '0°36'40"N' -> signed degrees."""
    m = re.fullmatch(r"\s*(\d+)°\s*(\d+)['’´]\s*([\d.]+)?\"?\s*([NSEW])\s*", value)
    if not m:
        raise ValueError(f"unreadable DMS {value!r}")
    deg = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3) or 0) / 3600
    return -deg if m.group(4) in "SW" else deg


# ================================================================= Aero Club of East Africa camera pages (pure)
def parse_acea_page(doc):
    """Location line, notes and the 'Airstrip Info' block of one camera page."""
    doc = decoded(doc)
    title = re.search(r"(?is)<title>(.*?)</title>", doc)
    loc = re.search(r'(?s)name="locationinfo" -->\s*<h5[^>]*>(.*?)</h5>', doc)
    notes = re.search(r'(?s)name="notes" -->(.*?)<!-- InstanceEndEditable', doc)
    strip = re.search(r"(?s)<h3>Airstrip Info</h3>(.*?)(?:<!--end airstrip|Sponsor/Host)", doc)
    return {"title": re.sub(r"^Kenya Webcams - ", "", text_of(title.group(1))) if title else None,
            "location": text_of(loc.group(1)) if loc else None,
            "notes": text_of(notes.group(1)) if notes else None,
            "airstrip": text_of(strip.group(1)) if strip else None}


# ================================================================= DSAT Macau index (pure)
DSAT_INDEX = "https://www.dsat.gov.mo/dsat/realtime.aspx"


def parse_dsat_index(doc, base=DSAT_INDEX):
    """Every camera of the index: id, name, area tab, sub-area tab and its zone description, per-camera page."""
    doc = decoded(doc)
    # Area buttons call show(N); the page script maps N to one container (macau_tab, cotai_tab, ...) holding that
    # area's sub-area buttons and camera lists.
    areas = {n: text_of(name) for n, name in re.findall(r'<div id="area(\d)" class="area_button[^"]*"[^>]*>(.*?)</div>', doc)}
    area_of_container = {box: areas.get(n) for n, box in re.findall(r"if \(tab==(\d)\) \{\$\('#(\w+_tab)'\)\.show\(\)", doc)}
    boxes = [(m.start(), m.group(1)) for m in re.finditer(r'<div id="(\w+_tab)"', doc)]
    if not boxes or set(b for _, b in boxes) - set(area_of_container):
        raise ValueError("DSAT index: area containers changed")

    def area_at(pos):
        inside = [box for start, box in boxes if start < pos]
        return area_of_container[inside[-1]] if inside else None

    subs = {sub: text_of(name) for sub, name in
            re.findall(r"<div id='sub_area_(s_\d+)' class='sub_area_button[^']*' onclick=show_sub\('s_\d+'\)>(.*?)</div>", doc)}
    cams = []
    for m in re.finditer(r'(?s)<div id="sub_tab_(s_\d+)"[^>]*>\s*<div><img[^>]*>&nbsp;(.*?)</div>(.*?)(?=<div id="sub_tab_|'
                         r'<div id="\w+_tab"|\Z)', doc):
        sub, zones, area = m.group(1), text_of(m.group(2)), area_at(m.start())
        for cam_id, name in re.findall(r'cam_id=(\d+)"\s+style=[^>]*>(.*?)</a>', m.group(3)):
            cams.append({"cam_id": cam_id, "name": text_of(name), "area": area, "sub_area": subs.get(sub),
                         "zones": zones, "page": urljoin(base, f"../realtime_core4.aspx?lang=tc&cam_id={cam_id}")})
    if len({c["cam_id"] for c in cams}) != len(set(re.findall(r"cam_id=(\d+)", doc))):
        raise ValueError("DSAT index: camera links outside the district tabs")
    return cams


def parse_dsat_camera(doc):
    """Name printed on a per-camera page and whether the page carries the live player."""
    doc = decoded(doc)
    m = re.search(r"(?s)<body[^>]*>\s*(.*?)<br", doc)
    return {"name": text_of(m.group(1)) if m else None, "player": "J_prismPlayer" in doc}


# ================================================================= Nova Scotia list (pure)
NS_LIST = "https://novascotia.ca/tran/cameras/all.asp"


def parse_ns_list(doc, base=NS_LIST):
    """[{id, label, detail, page}]: label is the place, detail the bracketed highway note (may be empty)."""
    doc = decoded(doc)
    out = []
    for m in re.finditer(r'(?s)<a href="cameradetails\.asp\?id=([^"]+)">.*?<div class="footer">(.*?)</div>', doc):
        cam = htmllib.unescape(m.group(1))
        parts = [text_of(p) for p in re.split(r"<br\s*/?>", m.group(2))]
        parts = [p for p in parts if p]
        label = parts[0] if parts else cam
        detail = parts[1].strip("() ") if len(parts) > 1 else ""
        out.append({"id": cam, "label": label, "detail": detail,
                    "page": urljoin(base, "cameradetails.asp?id=" + quote(cam, safe=""))})
    return out


# ================================================================= OVSICORI index (pure)
OVSICORI_INDEX = "https://www.ovsicori.una.ac.cr/index.php/camaras"


def parse_ovsicori_index(doc):
    doc = decoded(doc)
    return [{"slug": page.rsplit("/", 1)[1], "title": text_of(title), "page": page}
            for page, title in re.findall(r'<a class="camara-title" href="(https://www\.ovsicori\.una\.ac\.cr/index\.php/'
                                          r'vulcanologia/camara-volcanes-2/[a-z0-9-]+)"><strong>(.*?)</strong></a>', doc)]


# ================================================================= Western Wall live page (pure)
KOTEL_LIVE = "https://thekotel.org/en/connect-remotely-to-the-western-wall/"


def parse_kotel_live(doc):
    """The pop-up players listed under 'Live View of the Holy Wall'."""
    m = re.search(r"Live View of the Holy Wall (.*?) Virtual Services", text_of(doc))
    if not m:
        raise ValueError("live camera block not found")
    return [x.strip() for x in m.group(1).split("View now!") if x.strip()]


# ================================================================= placement (pure, given the looked-up data)
class Lookups:
    """What the network stage found: Overpass elements per area, Wikidata P625 per QID, OurAirports rows."""

    def __init__(self, areas=None, wikidata=None, airports=None):
        self.areas, self.wikidata, self.airports = areas or {}, wikidata or {}, airports or {}


def resolve(spec, lk):
    """A placement spec -> (lat, lng, source, feature, uncertainty_m) or (None, reason).

    kinds: wikidata {qid}; ourairports {ident}; osm {area, pattern, where?, near?, max_km?, cluster_m?};
    place {area, pattern, near?, max_km?} (an OSM place node). uncertainty: an int, or for OSM ways the feature's
    extent with spec['uncertainty'] as the floor."""
    kind = spec["kind"]
    if kind == "wikidata":
        pos = lk.wikidata.get(spec["qid"])
        if not pos:
            return None, f"no P625 for wikidata:{spec['qid']}"
        return (pos[0], pos[1], f"wikidata:{spec['qid']}", spec["feature"], spec["uncertainty"]), None
    if kind == "ourairports":
        row = lk.airports.get(spec["ident"])
        if not row:
            return None, f"OurAirports has no {spec['ident']}"
        if spec.get("name") and not re.search(spec["name"], row[2], re.I):
            return None, f"OurAirports {spec['ident']} is {row[2]!r}, not {spec['name']!r}"
        return (row[0], row[1], f"ourairports:{spec['ident']}", spec.get("feature") or f"{row[2]} (OurAirports)",
                spec["uncertainty"]), None
    if kind in ("osm", "place"):
        elements = lk.areas.get(spec["area"])
        if elements is None:
            return None, f"no OpenStreetMap data for area {spec['area']!r} (Overpass did not answer: HTTP 504/timeouts)"
        where = spec.get("where")
        if kind == "place":
            where = (lambda t: "place" in t and (spec.get("where") or (lambda _t: True))(t))
        found = find_osm(elements, spec.get("pattern"), near=spec.get("near"), max_km=spec.get("max_km"), where=where)
        if spec.get("merge"):
            el, why = merged(found, spec.get("max_extent_m", 3000))
        else:
            el, why = pick_one(found, spec.get("cluster_m", 300))
        if not el:
            return None, why
        lat, lng, extent = feature_point(el)
        if kind == "place":
            uncertainty = (spec.get("by_type") or {}).get(el.get("tags", {}).get("place"), spec["uncertainty"])
        else:
            uncertainty = spec["uncertainty"] if spec.get("fixed") else max(spec["uncertainty"], round_up(extent))
        label = spec.get("feature") or next(iter(names_of(el)), spec.get("pattern"))
        return (lat, lng, osm_ref(el), label, uncertainty), None
    raise ValueError(f"unknown placement kind {kind}")


def apply_placement(item, spec, lk, countries, rules=None):
    """Place item by spec and run the sanity checks. Returns (item, None) or (None, reason)."""
    found, why = resolve(spec, lk)
    if not found:
        return None, why
    lat, lng, source, feature, uncertainty = found
    placed = P.place(dict(item), role=spec["role"], lat=lat, lng=lng, source=source, feature=feature,
                     uncertainty_m=uncertainty)
    check = spec.get("check", {})
    problems = P.check(placed, countries, expected_country=item["country"], centre=check.get("centre"),
                       max_km=check.get("max_km"), allow_sea=check.get("allow_sea", False), rules=rules)
    if problems:
        return None, "; ".join(problems)
    if spec.get("note"):
        placed["coordinate_note"] = spec["note"]
    placed["coordinate_reference_system"] = "WGS84"  # OSM, Wikidata and OurAirports positions are WGS84
    return placed, None


def page_record(provider, pid, name, country, region, page, observed, *, source_page=None, catalog=None, **extra):
    record = {"provider": provider, "provider_id": pid, "id": f"{provider}:{pid}", "name": name, "lat": 0.0, "lng": 0.0,
              "country": country, "region": region, "format": "official_page", "stream_url": None, "snapshot_url": None,
              "official_page": page, "source_page": source_page or page, "source_catalog": catalog or page,
              "rights_status": "official_page_only", "observed_at": observed, "health": {"status": "unverified"},
              "link_scope": "official_camera_page"}
    record.update({k: v for k, v in extra.items() if v is not None})
    return record


def summarize(items):
    """Placed counts by role with the typical (median) and largest uncertainty."""
    out = {}
    for role in ("named_feature", "place_centre"):
        values = [i["coordinate_uncertainty_m"] for i in items if i.get("coordinate_role") == role]
        if values:
            out[role] = {"records": len(values), "median_uncertainty_m": int(statistics.median(values)),
                         "max_uncertainty_m": max(values)}
    official = [i for i in items if i.get("coordinate_role") not in ("named_feature", "place_centre")]
    if official:
        out["official"] = {"records": len(official), "roles": dict(collections.Counter(i["coordinate_role"] for i in official))}
    return out


# ================================================================= policies
PLACEMENT_NOTE = ("Positions placed by Q-Globe where the operator publishes none (placement round, 2026-11-14): the named "
                  "feature in OpenStreetMap (ODbL 1.0), Wikidata (CC0 1.0) or OurAirports (public domain) or, last "
                  "resort, the place centre; each card shows the feature, its source and the uncertainty.")
PLACEMENT_EVIDENCE = [OSM_COPYRIGHT, "https://www.wikidata.org/wiki/Wikidata:Licensing", OURAIRPORTS]
TRANSALVADOR = "https://cameras-transalvador.salvador.ba.gov.br/"
TRANSALVADOR_TERMS = TRANSALVADOR + "termos.html"
TRANSALVADOR_HOME = "https://transalvador.salvador.ba.gov.br/"
SHYMBULAK = "https://shymbulak.com/en/webcams/"
NS_TERMS = "https://511.novascotia.ca/about/about"
MAYAPUR_TV = "https://www.mayapur.tv/"
IMAM_HUSSAIN_LIVE = "https://imamhussain.org/arabic/live"


def with_placement(policy, *, notice=None, extra_hosts=(), extra_evidence=(), **source_changes):
    """A copy of an integrated policy that now also carries Q-Globe-placed records (no force_coordinate_role)."""
    policy = json.loads(json.dumps(policy))
    src = policy["source"]
    src["rights_note"] = (src.get("rights_note", "").rstrip() + " " + PLACEMENT_NOTE).strip()
    src["evidence"] = list(dict.fromkeys([*src.get("evidence", []), *extra_evidence, *PLACEMENT_EVIDENCE]))
    src.update(source_changes)
    if notice:
        src["provider_notice"] = notice
    policy["page_hosts"] = list(dict.fromkeys([*policy.get("page_hosts", []), *extra_hosts]))
    policy.pop("force_coordinate_role", None)
    return policy


def new_page_policy(sid, name, url, catalog, terms, licence, media_rights, note, attribution, page_hosts, countries,
                    evidence, notice=None):
    policy = W2.page_policy(sid, name, url, catalog, terms, licence, media_rights, note + " " + PLACEMENT_NOTE,
                            attribution, page_hosts, countries, [*evidence, *PLACEMENT_EVIDENCE],
                            role="associated_feature")
    policy["source"]["reviewed_at"] = REVIEWED_AT
    if notice:
        policy["source"]["provider_notice"] = notice
    return policy


def policies():
    w2, ap = W2.policies(), AP.POLICIES
    return {
        # ---- held until now (no position): integrated with placed positions
        "israel_western_wall_cameras": new_page_policy(
            "israel_western_wall_cameras", "Western Wall Heritage Foundation live cameras (Western Wall, Prayer Plaza, "
            "Wilson's Arch)", KOTEL_LIVE + "#live", KOTEL_LIVE, KOTEL_LIVE,
            "None stated (no terms page found); factual link to the foundation's own live page",
            "No terms or reuse text; the three players open as pop-ups on the foundation's page: link only.",
            "The old per-camera URLs (western-wall-cameras, cameras-prayer-plaza, camera-wilsons-arch) redirect to this "
            "one live page (re-read 2026-11-14).", "Western Wall Heritage Foundation (thekotel.org)", ["thekotel.org"],
            ["IL"], [KOTEL_LIVE, "https://thekotel.org/en/visitor_information/directions/"]),
        "brazil_transalvador_cameras": new_page_policy(
            "brazil_transalvador_cameras", "Transalvador live traffic cameras portal (Salvador, BA)", TRANSALVADOR,
            TRANSALVADOR, TRANSALVADOR_TERMS, "None (restrictive terms); one factual link to the agency's portal",
            "Viewers must not record, copy or redistribute the images, use them commercially or circumvent the "
            "platform's access controls: one city-level link only, nothing embedded.",
            "'Ao assistir, você se compromete a: não gravar, copiar ou redistribuir as imagens; não usar o conteúdo "
            "para finalidade comercial [...]; não tentar contornar os controles de acesso da plataforma' (termos.html). "
            "The camera list loads only after a Cloudflare Turnstile check, which Q-Globe does not bypass.",
            "Transalvador - Superintendência de Trânsito de Salvador", ["cameras-transalvador.salvador.ba.gov.br"],
            ["BR"], [TRANSALVADOR_TERMS, TRANSALVADOR_HOME],
            notice="Opens Transalvador's camera portal (it asks for a human check before the list). The marker is "
                   "Salvador's centre, not a camera."),
        "kz_shymbulak_webcams": new_page_policy(
            "kz_shymbulak_webcams", "Shymbulak Mountain Resort webcams (Almaty)", SHYMBULAK, SHYMBULAK, SHYMBULAK,
            "None found; factual link to the resort's own webcam page",
            "Resort-owned content with no licence: page link only.",
            "The page is script-rendered; its cameras are not enumerated, so one record links the page.",
            "Shymbulak Mountain Resort", ["shymbulak.com"], ["KZ"], [SHYMBULAK]),
        "macau_dsat_realtime_cameras": new_page_policy(
            "macau_dsat_realtime_cameras", "DSAT Macau real-time road condition cameras (即時路面情況)", DSAT_INDEX,
            DSAT_INDEX, DSAT_INDEX, "All rights reserved (footer); factual links to DSAT's own per-camera pages",
            "'Copyright © 2026 DSAT. All rights reserved.' The live streams are not embedded or fetched: each record "
            "opens DSAT's per-camera page.",
            "111 cameras grouped by district on the index; DSAT publishes no positions.",
            "Direcção dos Serviços para os Assuntos de Tráfego (DSAT), Macau SAR", ["www.dsat.gov.mo"], ["MO"],
            [DSAT_INDEX, "https://www.dsat.gov.mo/robots.txt"],
            notice="Opens DSAT's own camera page. Q-Globe placed the marker: at the bridge, port, roundabout or square "
                   "the camera is named after, otherwise at its district's centre (street corners are never guessed)."),
        "novascotia_highway_cameras": new_page_policy(
            "novascotia_highway_cameras", "Nova Scotia highway cameras", NS_LIST, NS_LIST, NS_TERMS,
            "Crown copyright (Government of Nova Scotia); factual links to the province's own camera pages",
            "Images are for personal and public non-commercial use: no image is fetched or embedded; each record "
            "links the camera's page on novascotia.ca.",
            "'The information has been posted with the intent that it be readily available for personal and public "
            "non-commercial (educational) use' (511 Nova Scotia terms). The province publishes no camera positions.",
            "Source: Nova Scotia Department of Public Works highway cameras.", ["novascotia.ca"], ["CA"],
            [NS_LIST, NS_TERMS],
            notice="Opens the province's camera page. Q-Globe placed the marker at the named highway exit or feature, "
                   "otherwise at the community the camera is named after."),
        "costa_rica_ovsicori_cameras": new_page_policy(
            "costa_rica_ovsicori_cameras", "OVSICORI-UNA volcano cameras", OVSICORI_INDEX, OVSICORI_INDEX,
            "https://www.ovsicori.una.ac.cr/",
            "All rights reserved; factual links to the observatory's own per-camera pages",
            "'Copyright © 2026 Observatorio Vulcanológico y Sismológico de Costa Rica. Todos los derechos reservados.' "
            "Images are not fetched or embedded: page links only.",
            "One page per camera on the observatory's camera index (re-read 2026-11-14).",
            "OVSICORI-UNA", ["www.ovsicori.una.ac.cr"], ["CR"], [OVSICORI_INDEX, "https://www.ovsicori.una.ac.cr/"],
            notice="Opens OVSICORI's camera page. Q-Globe placed the marker at the volcano or place the camera is "
                   "named after; the camera itself may stand several kilometres away."),
        # ---- integrated earlier: same policy, now also with placed records
        "kenya_aeroclub_webcams": with_placement(w2["kenya_aeroclub_webcams"]),
        # Exactly collect_apac_pages.POLICIES (its provider notice now covers placed sites): test_collect_apac_pages
        # checks that entry against the merged registry.
        "hong_kong_observatory_weather_photos": json.loads(json.dumps(ap["hong_kong_observatory_weather_photos"])),
        "iraq_karbala_shrine_live": with_placement(
            w2["iraq_karbala_shrine_live"], extra_hosts=["imamhussain.org"], extra_evidence=[IMAM_HUSSAIN_LIVE],
            name="Karbala holy shrines official live broadcasts (Imam Hussain and Al-Abbas shrines)",
            attribution="Imam Hussain Holy Shrine (imamhussain.org); Al-Abbas Holy Shrine (alkafeel.net)"),
        "india_temple_live_darshan_round2": with_placement(
            w2["india_temple_live_darshan_round2"], extra_hosts=["www.mayapur.tv"], extra_evidence=[MAYAPUR_TV],
            attribution="Shri Arasuri Ambaji Mata Devasthan Trust; Shri Mahalaxmi Temple Trust, Mumbai; "
                        "ISKCON Mayapur (Mayapur TV)"),
        "noaa_gml_observatory_webcams": with_placement(w2["noaa_gml_observatory_webcams"]),
    }


# ================================================================= network stage
class Net:
    """Polite reads (robots first, HTTPS, >=1 s per host) of pages saved under raw/<source>/ and of placement lookups
    cached under raw/places/places_world/. A saved page (same URL, HTTP 200, receipt) is never requested again."""

    def __init__(self, out, offline=False):
        self.out, self.offline = Path(out), offline
        self.cache = self.out / "raw" / "places" / FAMILY
        self.client = W.PoliteClient(delay=1.0, timeout=240)
        self.reads = []

    def cached(self, key):
        import hashlib
        return (self.cache / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")).exists()

    def page(self, source, name, url, max_bytes=4_000_000):
        folder = self.out / "raw" / source
        path, receipt_path = folder / name, folder / (name + ".receipt.json")
        if path.exists() and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("url") == url and receipt.get("status") == 200:
                self.reads.append({"url": url, "reused": True})
                return path.read_bytes(), receipt
        if self.offline:
            raise Offline(url)
        r = self.client.get(url, max_bytes=max_bytes)
        if r["status"] != 200:
            raise ValueError(f"HTTP {r['status']} for {url}")
        receipt = W.save_raw(folder, name, r)
        self.reads.append({"url": url, "reused": False, "status": r["status"]})
        return r["body"], receipt

    def overpass(self, key):
        if self.offline and not self.cached("overpass:" + OVERPASS[key]):
            raise Offline(f"overpass {key}")
        hit = self.cached("overpass:" + OVERPASS[key])
        data = P.overpass(self.client, OVERPASS[key], self.cache)
        self.reads.append({"url": f"overpass:{key}", "reused": hit})
        if data.get("remark"):
            raise ValueError(f"Overpass {key}: {data['remark'][:120]}")
        return data["elements"]

    def wikidata(self, qid):
        if self.offline and not self.cached("wikidata:" + qid):
            raise Offline(f"wikidata {qid}")
        hit = self.cached("wikidata:" + qid)
        pos = P.wikidata_coordinates(self.client, qid, self.cache)
        self.reads.append({"url": f"wikidata:{qid}", "reused": hit})
        return pos


def lookups(net, open_data, areas, qids, notes):
    lk = Lookups(airports=P.ourairports(Path(open_data) / "ourairports_airports.csv"))
    for key in areas:  # "kenya:rift" is one part of area "kenya": the parts are merged
        try:
            elements = net.overpass(key)
        except (W.Refused, OSError, ValueError, Offline) as e:
            notes.append(f"Overpass area {key} not available: {str(e)[:160]}")
            continue
        merged_area = lk.areas.setdefault(key.split(":")[0], [])
        seen = {(e["type"], e["id"]) for e in merged_area}
        merged_area += [e for e in elements if (e["type"], e["id"]) not in seen]
    for qid in qids:
        try:
            pos = net.wikidata(qid)
            if pos:
                lk.wikidata[qid] = pos
        except (W.Refused, OSError, ValueError, KeyError, Offline) as e:
            notes.append(f"Wikidata {qid} not available: {str(e)[:160]}")
    return lk


# ================================================================= single-page sources (specs: rule 1 hierarchy)
SINGLE = {
    "israel_western_wall_cameras": {
        "kind": "wikidata", "qid": "Q24009481", "role": "named_feature", "feature": "Western Wall Plaza, Jerusalem",
        "uncertainty": 150, "check": {"centre": (31.7767, 35.2345), "max_km": 1},
        "note": "Western Wall Plaza (Wikidata P625; OSM way 26492734 carries the same item): the three cameras (the "
                "Wall, the Prayer Plaza and Wilson's Arch) look over the plaza and the prayer area beside it."},
    "brazil_transalvador_cameras": {
        "kind": "wikidata", "qid": "Q36947", "role": "place_centre", "feature": "Salvador, Bahia (city centre)",
        "uncertainty": 15000, "check": {"centre": (-12.97, -38.50), "max_km": 10},
        "note": "City-level portal record (the camera list is behind a human check): Salvador's Wikidata position; "
                "15 km is the radius of a circle of the municipality's 693 km² (Wikidata P2046)."},
    "iraq_karbala_shrine_live:imam-hussain-shrine": {
        "kind": "wikidata", "qid": "Q773704", "role": "named_feature", "feature": "Imam Husayn Shrine, Karbala",
        "uncertainty": 150, "check": {"centre": (32.6164, 44.0324), "max_km": 1},
        "note": "Imam Husayn Shrine (Wikidata P625; OSM relation 14117800 carries the same item, about 120 m across)."},
}
SHYMBULAK_SPEC = {
    "kind": "osm", "area": "shymbulak", "pattern": r"Shymbulak|Chimbulak|Шымбулак|Чимбулак",
    "where": lambda t: t.get("landuse") == "winter_sports", "role": "named_feature",
    "feature": "Shymbulak ski area (OSM winter-sports area)", "uncertainty": 1000,
    "check": {"centre": (43.128, 77.081), "max_km": 6}}
MAYAPUR_SPEC = {
    "kind": "osm", "area": "mayapur", "pattern": r"Chandrodaya", "role": "named_feature",
    "feature": "Sri Mayapur Chandrodaya Mandir (ISKCON Mayapur)", "uncertainty": 400,
    "check": {"centre": (23.424, 88.389), "max_km": 2}}
WIKIDATA_QIDS = ["Q24009481", "Q36947", "Q773704", "Q14773"]  # Q14773: Macau (portal fallback, distance reference)


def single_page_records(net, lk, countries):
    """Western Wall, Transalvador portal, Imam Hussain shrine, Shymbulak, Mayapur TV: one page each."""
    out, held_out = {}, {}

    def put(sid, item, spec):
        placed, why = apply_placement(item, spec, lk, countries)
        if placed:
            out.setdefault(sid, []).append(placed)
        else:
            held_out.setdefault(sid, []).append({"provider_id": item["provider_id"], "name": item["name"], "reason": why})

    doc, r = net.page("israel_western_wall_cameras", "kotel_connect_remotely_full.html", KOTEL_LIVE)
    players = parse_kotel_live(doc)
    put("israel_western_wall_cameras", page_record(
        "israel_western_wall_cameras", "live-cameras", f"Western Wall live cameras ({', '.join(players)})", "IL",
        "Jerusalem", KOTEL_LIVE + "#live", r["observed_at"], catalog=KOTEL_LIVE, cameras_on_page=players,
        link_scope="official_live_page"), SINGLE["israel_western_wall_cameras"])

    doc, r = net.page("brazil_transalvador_cameras", "transalvador_cameras.html", TRANSALVADOR)
    home, _ = net.page("brazil_transalvador_cameras", "transalvador_home.html", TRANSALVADOR_HOME)
    if "Transalvador" not in text_of(doc) or "cameras-transalvador.salvador.ba.gov.br" not in decoded(home):
        raise ValueError("Transalvador portal or its link on the agency home page changed")
    put("brazil_transalvador_cameras", page_record(
        "brazil_transalvador_cameras", "portal", "Transalvador live traffic cameras — city portal (Salvador)", "BR",
        "Bahia", TRANSALVADOR, r["observed_at"], source_page=TRANSALVADOR_HOME, catalog=TRANSALVADOR,
        link_scope="city_portal"), SINGLE["brazil_transalvador_cameras"])

    doc, r = net.page("iraq_karbala_shrine_live", "imamhussain_live.html", IMAM_HUSSAIN_LIVE)
    if "البث المباشر" not in text_of(doc):  # 'live broadcast' in the page title
        raise ValueError("Imam Hussain live page title changed")
    put("iraq_karbala_shrine_live", page_record(
        "iraq_karbala_shrine_live", "imam-hussain-shrine", "Imam Hussain Holy Shrine, Karbala — live broadcast", "IQ",
        "Karbala", IMAM_HUSSAIN_LIVE, r["observed_at"], link_scope=None,
        broadcast_hours="09:00-21:00 Karbala time (page)"), SINGLE["iraq_karbala_shrine_live:imam-hussain-shrine"])

    doc, r = net.page("kz_shymbulak_webcams", "shymbulak_webcams.html", SHYMBULAK)
    if 'content="Shymbulak"' not in decoded(doc):
        raise ValueError("Shymbulak webcam page changed")
    put("kz_shymbulak_webcams", page_record(
        "kz_shymbulak_webcams", "webcams", "Shymbulak Mountain Resort webcams (Almaty)", "KZ", "Almaty", SHYMBULAK,
        r["observed_at"], link_scope="official_webcam_page"), SHYMBULAK_SPEC)

    doc, r = net.page("india_temple_live_darshan_round2", "mayapur_tv.html", MAYAPUR_TV)
    if "Sri Dham Mayapur Temple" not in text_of(doc) or "youtube.com/embed/" not in decoded(doc):
        raise ValueError("Mayapur TV page changed")
    put("india_temple_live_darshan_round2", page_record(
        "india_temple_live_darshan_round2", "mayapur-tv", "Mayapur TV — ISKCON Mayapur live (official)", "IN",
        "West Bengal", MAYAPUR_TV, r["observed_at"], link_scope=None, stream_platform="YouTube"), MAYAPUR_SPEC)
    return out, held_out


# ================================================================= Macau (DSAT): named feature, else district centre
def is_bridge(tags):
    return tags.get("bridge") not in (None, "no") or tags.get("man_made") == "bridge"


def _mo(key, label, floor, max_extent, sea=False, where=None):
    """A Macau feature: every OSM piece whose name contains key, merged (bridges and roundabouts are split into
    several ways); the uncertainty is the merged extent, at least floor."""
    spec = {"kind": "osm", "area": "macau", "pattern": re.escape(key), "where": where, "merge": True,
            "max_extent_m": max_extent, "feature": label, "uncertainty": floor, "role": "named_feature"}
    if sea:  # a sea bridge or a port on reclaimed land/an artificial island: offshore or port feature
        spec["check"] = {"allow_sea": True}
    return spec


# Camera-name prefix (after the direction is removed) -> feature. Rule 3: only when the name IS the feature (or the
# feature plus a direction, or a road meeting it at a roundabout); streets, corners and 'near X' are not features.
MACAU_FEATURES = {
    "友誼大橋": _mo("友誼大橋", "Ponte da Amizade (友誼大橋), the Macau–Taipa Friendship Bridge", 500, 3500, True, is_bridge),
    "西灣大橋": _mo("西灣大橋", "Ponte de Sai Van (西灣大橋)", 500, 2500, True, is_bridge),
    "澳門大橋": _mo("澳門大橋", "Ponte Macau (澳門大橋)", 500, 3000, True, is_bridge),
    "東亞運圓形地": _mo("東亞運圓形地", "East Asian Games roundabout (東亞運圓形地), Taipa", 100, 400),
    "北安圓形地": _mo("北安圓形地", "Pac On roundabout (北安圓形地), Taipa", 100, 400),
    "蘇利安圓形地": _mo("蘇利安圓形地", "蘇利安圓形地 roundabout, Taipa", 100, 400),
    "奧林匹克游泳館圓形地": _mo("奧林匹克游泳館圓形地", "Olympic Swimming Pool roundabout (奧林匹克游泳館圓形地), Taipa", 100, 400),
    "路氹連貫公路圓形地": _mo("路氹連貫公路圓形地", "Estrada do Istmo roundabout (路氹連貫公路圓形地)", 100, 400),
    "友誼圓形地": _mo("友誼圓形地", "Friendship roundabout (友誼圓形地)", 100, 400),
    "飛機場圓形地": _mo("飛機場圓形地", "Airport roundabout (飛機場圓形地), Taipa", 100, 400),
    "亞馬喇前地": _mo("亞馬喇前地", "Praça Ferreira do Amaral (亞馬喇前地)", 150, 400),
    "宋玉生廣場": _mo("宋玉生廣場", "宋玉生廣場 square", 150, 500),
    "西灣湖廣場": _mo("西灣湖廣場", "Praça do Lago Sai Van (西灣湖廣場)", 150, 500),
    "關閘廣場": _mo("關閘廣場", "Portas do Cerco square (關閘廣場)", 150, 500),
    "青茂口岸": _mo("青茂口岸", "Qingmao border crossing (青茂口岸), Macau side", 200, 600),
    "橫琴口岸": _mo("橫琴口岸", "Hengqin Port (橫琴口岸), Macau port zone", 300, 1500),
    "港珠澳": _mo("港珠澳大橋澳門口岸", "HZMB Macau Port (港珠澳大橋澳門口岸), artificial island", 500, 2000, True),
    "外港客運碼頭": _mo("外港客運碼頭", "Outer Harbour Ferry Terminal (外港客運碼頭)", 200, 800, True),
    "馬六甲街停車場": _mo("馬六甲街停車場", "Rua de Malaca car park (馬六甲街停車場)", 100, 300),
    "華士古停車場": _mo("華士古停車場", "華士古停車場 car park", 100, 300),
    "松山隧道": _mo("松山隧道", "Guia Tunnel (松山隧道)", 300, 800),
    "威尼斯人": _mo("威尼斯人", "The Venetian Macao (威尼斯人), Cotai", 300, 800),
    "捐血中心": _mo("捐血中心", "Blood Transfusion Centre (捐血中心)", 100, 300),
    "海灣花園": _mo("海灣花園", "海灣花園 estate, Taipa", 200, 600),
}
MACAU_FEATURE_ORDER = sorted(MACAU_FEATURES, key=len, reverse=True)  # longest key first
ROUNDABOUTS = [k for k in MACAU_FEATURE_ORDER if k.endswith("圓形地")]
MACAU_CENTRE = (22.19, 113.538056)  # Wikidata Q14773 P625 (read 2026-11-14): distance-check reference only
MACAU_QID = "Q14773"


def _district(pattern, label, uncertainty):
    return {"kind": "place", "area": "macau", "pattern": pattern, "feature": label, "uncertainty": uncertainty,
            "role": "place_centre"}


MACAU_DISTRICTS = {
    "peninsula": _district(r"^澳門半島|Macau Peninsula|Península de Macau", "Macau Peninsula (district centre)", 2500),
    "taipa": _district(r"^氹仔(?!.*(?:舊城|中心))|^Taipa$", "Taipa (district centre)", 2500),
    "cotai": _district(r"^路氹城|^Cotai", "Cotai (district centre)", 2000),
    "zone_a": _district(r"^新城A區|Zona A", "New Urban Zone A (新城A區, district centre)", 800),
}
MACAU_DIRECTION = re.compile(r"[（(][^）)]*[）)]|[往望向][^與]*?方向|方向$|\s*[-－]?[A-D]$")


def macau_feature(name):
    """The feature key a camera name identifies, or None (street, street corner, 'near X' -> district centre)."""
    head = MACAU_DIRECTION.sub("", name).strip()
    for key in MACAU_FEATURE_ORDER:
        if head.startswith(key):
            return key
    m = re.match(r"^[^與]+與(.+?)交界$", head)  # "road X meets the Y roundabout": the roundabout is the feature
    if m:
        return next((k for k in ROUNDABOUTS if m.group(1).startswith(k)), None)
    return None


def macau_district(cam):
    """The district whose centre stands in for a camera that names no feature (None: no single district)."""
    if cam["area"] in ("澳門區", "口岸"):
        return "peninsula" if cam["sub_area"] not in ("港珠澳大橋", "橫琴口岸區") else None
    if cam["area"] == "路氹區":
        return "cotai" if cam["sub_area"] == "路氹區" else "taipa"
    if cam["area"] == "新城A區":
        return "zone_a"
    if cam["area"] == "跨海大橋":  # bridge cameras that name no bridge: the bank their road is on
        return {"西灣湖景大馬路": "peninsula", "東亞運圓形地": "taipa"}.get(MACAU_DIRECTION.sub("", cam["name"]).strip())
    return None


# ================================================================= Kenya (Aero Club of East Africa): per site
# Read on each camera page (2026-11-14): the 'Location' line names the site; the page's weather link and Google
# Earth link are template copies (the same point on unrelated pages), so they are not used as positions.
# Each site: the location words the page must still show, then placement specs tried in order (rule 1 hierarchy),
# and a reference for the distance check: an OurAirports airfield the page names or that serves the area, or the
# OSM place node of the town the page names ("place", pattern, km).
def _osm(area, pattern, label, uncertainty, role="named_feature", **kw):
    return {"kind": "osm", "area": area, "pattern": pattern, "feature": label, "uncertainty": uncertainty, "role": role, **kw}


def _place(area, pattern, label, uncertainty, **kw):
    return {"kind": "place", "area": area, "pattern": pattern, "feature": label, "uncertainty": uncertainty,
            "role": "place_centre", **kw}


def _airport(ident, name, label, uncertainty):
    return {"kind": "ourairports", "ident": ident, "name": name, "feature": label, "uncertainty": uncertainty,
            "role": "named_feature"}


NAIROBI = (-1.32172, 36.8148)  # OurAirports HKNW Wilson Airport: reference for the Nairobi-area sites
KENYA_SITES = [
    {"folders": ["cbdl1", "cbdl2", "cbdl3", "cbdl4", "cbdl5"], "location": "Hardy Estate", "ref": (NAIROBI, 25),
     "specs": [_place("kenya", r"^Hardy$", "Hardy (Karen), Nairobi", 1500, near=NAIROBI, max_km=25)]},
    {"folders": ["storage1", "storage2", "storage3", "storage4"], "location": "Mombasa Road", "ref": (NAIROBI, 25),
     "specs": [_osm("kenya", r"^Storage Central", "Storage Central, Mombasa Road, Nairobi", 100, near=NAIROBI, max_km=25)]},
    {"folders": ["cornerbaridi"], "location": "Champagne Ridge", "ref": (NAIROBI, 60),
     "specs": [_place("kenya", r"^Champagne Ridge$", "Champagne Ridge (Kajiado)", 3000, near=NAIROBI, max_km=60),
               _osm("kenya", r"^Champagne Ridge$", "Champagne Ridge (Kajiado)", 3000, role="place_centre",
                    near=NAIROBI, max_km=60)]},
    {"folders": ["suswa1", "suswa2"], "location": None, "airstrip": "Saikeri", "ref": (NAIROBI, 80),
     "specs": [_place("kenya", r"^Saikeri$", "Saikeri (Kajiado)", 5000, near=NAIROBI, max_km=80)]},
    {"folders": ["riara1", "riara2", "riara3", "riara4"], "location": "Riara Airstrip", "ref": (NAIROBI, 40),
     "specs": [_osm("kenya", r"Riara", "Riara Ridge airstrip, Tigoni", 500, near=NAIROBI, max_km=40,
                    where=lambda t: t.get("aeroway") in ("aerodrome", "airstrip", "runway"))]},
    {"folders": ["nyeri1", "nyeri2", "nyeri3", "nyeri4"], "location": "Nyeri", "ref": ((-0.364414, 36.978485), 15),
     "specs": [_place("kenya", r"^Nyeri$", "Nyeri town", 5000, near=(-0.364414, 36.978485), max_km=15)],
     "note": "The club's map has two Nyeri placemarks 4.5 km apart and these cameras match neither by name: placed at "
             "Nyeri's centre with an uncertainty that covers both."},
    {"folders": ["nanyu1", "nanyu2"], "location": "Mogwooni", "ref": ((-0.062352, 37.041296), 50),
     "specs": [_osm("kenya", r"Mog?w?ooni|Mugwooni", "Mogwooni airstrip (Laikipia)", 500, near=(-0.062352, 37.041296),
                    max_km=50)]},
    {"folders": ["bondet1", "bondet2", "bondet3", "bondet4"], "location": "Bondet Farm",
     "ref": ((-0.062352, 37.041296), 20),
     "specs": [_osm("kenya", r"Mount Kenya Safari Club", "Fairmont Mount Kenya Safari Club (the camera is about 1 km "
                    "north-east of it)", 1500, near=(-0.062352, 37.041296), max_km=20, fixed=True),
               _airport("KE-6883", r"Fairmont", "Fairmont (Mount Kenya Safari Club) airstrip; the camera is about 1 km "
                        "north-east of the club and looks over the ranch airstrip", 3000)]},
    {"folders": ["lewahouse1", "lewahouse2", "lewahouse3", "lewahouse4", "lewahouse5"], "location": "Lewa House",
     "ref": ((0.195157, 37.470289), 6),
     "specs": [_osm("kenya", r"^Lewa House", "Lewa House safari lodge (hilltop)", 300, near=(0.195157, 37.470289), max_km=6),
               _airport("KE-0052", r"Lewa", "Lewa Airstrip (the camera page puts the camera 3.3 km away)", 3500)]},
    {"folders": ["meru1", "meru2", "meru3", "meru4"], "location": "Hotel Ezri", "ref": ("place", r"^Meru$", 5),
     "specs": [_osm("kenya", r"Ezri", "Hotel Ezri, Meru", 150),
               _place("kenya", r"^Meru$", "Meru town", 3000)]},
    {"folders": ["loisaba1"], "location": "Loisaba", "notes": "overlooking the airstrip", "ref": ((0.61196, 36.800095), 3),
     "specs": [_airport("KE-0207", r"Loisaba", "Loisaba Airstrip (camera on a mast overlooking it)", 500)]},
    {"folders": ["loisaba2"], "location": "Loisaba", "notes": "southern end of Loisaba", "ref": ((0.61196, 36.800095), 25),
     "specs": [_osm("kenya", r"^Loisaba", "Loisaba Conservancy", 3000, role="place_centre", near=(0.61196, 36.800095),
                    max_km=25, where=lambda t: t.get("boundary") == "protected_area" or t.get("leisure") == "nature_reserve")]},
    {"folders": ["loisabacam"], "location": "Suyian", "ref": ((0.61196, 36.800095), 40),
     "specs": [_osm("kenya", r"^Suyian", "Suyian Conservancy", 3000, role="place_centre", near=(0.61196, 36.800095),
                    max_km=40)]},
    {"folders": ["greenpark1", "greenpark2"], "location": "Green Park", "ref": ((-0.666147, 36.311102), 5),
     "specs": [_osm("kenya", r"^Green Park", "Green Park estate, Naivasha", 500, near=(-0.666147, 36.311102), max_km=5),
               _airport("KE-6084", r"Green Park", "Green Park airstrip (estate), Naivasha", 1500)]},
    {"folders": ["nakuru1", "nakuru2", "nakuru3", "nakuru4"], "location": "Agventure", "ref": ((-0.189141, 35.962871), 10),
     "specs": [_osm("kenya", r"Agventure", "Agventure silos, Kabarak", 150, near=(-0.189141, 35.962871), max_km=10),
               _place("kenya", r"^Kabarak$", "Kabarak", 3000, near=(-0.189141, 35.962871), max_km=10),
               _airport("KE-0014", r"Kabarak", "Kabarak Airstrip (the camera page puts it 4.5 km from the camera)", 5000)]},
    {"folders": ["nyahururu3", "nyahururu4", "nyahururu5", "nyahururu6"], "location": None, "airstrip": "5 km S of camera",
     "ref": ((-0.013767, 36.369736), 8),
     "specs": [_place("kenya", r"^Nyahururu$", "Nyahururu town (the page puts its airstrip 5 km south of the camera)",
                      3000, near=(-0.013767, 36.369736), max_km=8),
               _airport("KE-0029", r"Nyahururu", "Nyahururu airstrip (the camera page puts the camera 5 km north of it)",
                        5500)]},
    {"folders": ["molo1", "molo2", "molo5", "molo6"], "location": "Kudenga Farm", "ref": ((-0.273941, 35.767293), 25),
     "specs": [_osm("kenya", r"Kudenga", "Kudenga Farm, west of Molo", 1000, near=(-0.273941, 35.767293), max_km=25),
               _place("kenya", r"^Molo$", "Molo town (the camera is on a farm west of it)", 6000,
                      near=(-0.273941, 35.767293), max_km=25)]},
    {"folders": ["narok1", "narok2", "narok3", "narok4"], "location": "10 Kms from Narok Town", "ref": ((-1.13003, 35.789124), 15),
     "specs": [_place("kenya", r"^Narok$", "Narok town (the camera is 10 km out on road B3)", 12000,
                      near=(-1.13003, 35.789124), max_km=15)]},
    {"folders": ["sala"], "location": "Lemek Hills", "ref": ((-1.12471, 35.197795), 30),
     "specs": [_osm("kenya", r"^Lemek", "Lemek Hills (north of Aitong)", 3000, near=(-1.12471, 35.197795), max_km=30,
                    where=lambda t: t.get("natural") in ("ridge", "hill", "peak", "mountain_range")),
               _place("kenya", r"^Lemek$", "Lemek (Lemek Hills, north of Aitong)", 5000, near=(-1.12471, 35.197795), max_km=30)]},
    {"folders": ["ambo1"], "location": "TAWI LODGE", "ref": ((-2.72958, 37.428691), 5),
     "specs": [_osm("kenya", r"^Tawi Lodge", "Tawi Lodge, Amboseli", 200, near=(-2.72958, 37.428691), max_km=5,
                    where=lambda t: "tourism" in t),
               _airport("HKTW", r"Tawi", "Tawi Lodge Airstrip (the camera is at the lodge)", 2000)]},
    {"folders": ["ithumba1", "ithumba2", "ithumba3", "ithumba4"], "location": "Ithumba Mountain", "ref": ((-2.216722, 38.38689), 3),
     "specs": [_osm("kenya", r"^Ithumba", "Ithumba Hill (top), Tsavo East", 300, near=(-2.216722, 38.38689), max_km=3,
                    where=lambda t: t.get("natural") in ("peak", "hill", "mountain")),
               _airport("KE-0061", r"Ithumba", "Ithumba airstrip (the page puts the camera within 1 km)", 1500)]},
    {"folders": ["manda1", "manda2"], "location": "Manda Bay Lodge", "ref": ((-2.228949, 40.971447), 5),
     "specs": [_osm("kenya", r"^Manda Bay", "Manda Bay Lodge (communications mast)", 150, near=(-2.228949, 40.971447),
                    max_km=5, where=lambda t: "tourism" in t),
               _airport("KE-0148", r"Manda Point", "Manda Point airstrip, beside Manda Bay Lodge", 2000)]},
    {"folders": ["malindi1"], "location": "Malindi", "ref": ((-3.22931, 40.1017), 8),
     "specs": [_place("kenya", r"^Malindi$", "Malindi town (the camera is on a private residence: never pinpointed)",
                      3000, near=(-3.22931, 40.1017), max_km=8),
               _airport("HKML", r"Malindi", "Malindi International Airport (the camera, on a residence in Malindi, faces "
                        "it)", 3000)]},
    {"folders": ["kilifi1"], "location": "south of Kilifi Creek", "ref": ((-3.649041, 39.85191), 8),
     "specs": [_osm("kenya", r"Ras Kitoka", "Ras Kitoka headland, south of Kilifi Creek", 500,
                    near=(-3.649041, 39.85191), max_km=8),
               _place("kenya", r"^Kilifi$", "Kilifi town (the camera is on the headland south of the creek)", 3000,
                      near=(-3.649041, 39.85191), max_km=8),
               _airport("KE-6095", r"Kilifi Plantation", "Kilifi Plantation airstrip (the airstrip the camera page "
                        "names; the camera is on the headland south of Kilifi Creek)", 3000)]},
]


def first_placement(item, specs, lk, countries, check):
    """Try the specs in order (rule 1 hierarchy); the first that resolves AND passes the checks wins."""
    reasons = []
    for spec in specs:
        spec = dict(spec, check={**check, **spec.get("check", {})})
        placed, why = apply_placement(item, spec, lk, countries)
        if placed:
            return placed, None
        reasons.append(f"{spec['kind']}:{spec.get('pattern') or spec.get('ident') or spec.get('qid')}: {why}")
    return None, " | ".join(reasons)


def kenya_records(net, lk, countries):
    """Cameras of the club's index that round 2 left out (no position on the card or the club's map)."""
    source = "kenya_aeroclub_webcams"
    index, _ = net.page(source, "aeroclub_index.html", W2.ACEA_INDEX)
    cards = {c["folder"]: c for c in W2.parse_acea_index(index)}
    base = json.loads((net.out / f"{source}.json").read_text(encoding="utf-8"))["items"]
    have = {i["provider_id"] for i in base}
    placed, left = [], []
    for site in KENYA_SITES:
        for folder in site["folders"]:
            card = cards.get(folder)
            if not card or folder in have:
                left.append({"provider_id": folder, "reason": "not on the index any more" if not card else "already placed"})
                continue
            doc, r = net.page(source, f"pages/{folder}.html", card["page"])
            page = parse_acea_page(doc)
            evidence = " ".join(x for x in (page["location"], page["notes"], page["airstrip"]) if x)
            missing = [w for w in (site.get("location"), site.get("notes"), site.get("airstrip"))
                       if w and w.lower() not in evidence.lower()]
            if missing:  # the placement rests on these words of the camera page
                left.append({"provider_id": folder, "reason": f"camera page does not say {missing[0]!r}"})
                continue
            m = re.match(r"^\s*([A-Z][A-Z .]+?)\s*-\s*(.+)$", card["title"] or "")
            region = W2.ACEA_REGIONS.get(m.group(1).strip(), m.group(1).strip().title()) if m else None
            altitude = next((c for c in card["cells"] if re.search(r"[\d,]+\s*ftt?\b", c)), None)
            direction = next((c for c in card["cells"] if c != altitude), None)
            if m:
                title = m.group(2).strip(" -,")
            elif card["title"]:
                title = card["title"].strip(" -,")
            else:  # untitled card: the camera page's own title, plus the facing printed on the card
                title = re.sub(r"^Mt\. Kenya\s*-?\s*|,\s*Mt\. Kenya$", "", page["title"] or folder).strip()
                if direction and not re.search(r"\b[NSEW]{1,3}\b", title):
                    title = f"{title} {direction}"
                region = region or ("Mt. Kenya" if "/MtKenya/" in card["page"] else None)
            item = page_record(source, folder, f"{title} — Aero Club of East Africa webcam", "KE", region or "Kenya",
                               card["page"], r["observed_at"], source_page=W2.ACEA_INDEX, catalog=W2.ACEA_INDEX,
                               direction=direction, camera_altitude=altitude,
                               site_description=page["location"] or None)
            if site["ref"][0] == "place":  # the OSM place node of the town the page names
                anchor, why = pick_one(find_osm(lk.areas.get("kenya", []), site["ref"][1], where=lambda t: "place" in t))
                if not anchor:
                    left.append({"provider_id": folder, "name": item["name"], "reason": f"reference town: {why}"})
                    continue
                ref, max_km = feature_point(anchor)[:2], site["ref"][2]
            else:
                ref, max_km = site["ref"]
            got, why = first_placement(item, site["specs"], lk, countries, {"centre": ref, "max_km": max_km})
            if got:
                if site.get("note"):
                    got["coordinate_note"] = site["note"]
                placed.append(got)
            else:
                left.append({"provider_id": folder, "name": item["name"], "reason": why})
    return base, placed, left


# ================================================================= Hong Kong Observatory: sites without an HKO station
HK_CHECK = {"centre": (22.3193, 114.1694), "max_km": 40}  # Hong Kong: sanity bound only (the feature is the place)


def _hk(pattern, feature, uncertainty, role="named_feature", where=None, kind="osm"):
    return {"kind": kind, "area": "hongkong", "pattern": pattern, "feature": feature, "uncertainty": uncertainty,
            "role": role, "where": where, "check": HK_CHECK, "fixed": kind == "osm"}


HK_SPECS = {
    "ELC": _hk(r"^Elegantia College", "Elegantia College, Sheung Shui (school)", 150,
               where=lambda t: t.get("amenity") == "school"),
    "IC1": _hk(r"^International Commerce Centre$", "International Commerce Centre (tower), West Kowloon", 100),
    "IC2": _hk(r"^International Commerce Centre$", "International Commerce Centre (tower), West Kowloon", 100),
    # The museum stands on Central Pier 8, a ferry pier: a port feature, so the coastline test allows the water.
    "HMM": dict(_hk(r"^Hong Kong Maritime Museum", "Hong Kong Maritime Museum, Central Pier 8", 100),
                check={**HK_CHECK, "allow_sea": True}),
    "VPA": _hk(r"^Victoria Peak$", "Victoria Peak (the Peak area)", 1000, where=lambda t: t.get("natural") == "peak"),
    "VPB": _hk(r"^Victoria Peak$", "Victoria Peak (the Peak area)", 1000, where=lambda t: t.get("natural") == "peak"),
    # Two OSM features carry the school's name 2.4 km apart (main campus, kindergarten): ambiguous -> stays out.
    "GSI": _hk(r"^German Swiss International School", "German Swiss International School", 300),
    "SWH": _hk(r"^Sai Wan Ho$", "Sai Wan Ho (district centre)", 1500, role="place_centre", kind="place"),
    "TLC": _hk(r"^Tai Lam Chung$", "Tai Lam Chung (place centre)", 1500, role="place_centre", kind="place"),
    "CS1": _hk(r"^Cheung Sha$", "Cheung Sha, Lantau (village centre)", 1500, role="place_centre", kind="place"),
    "CS2": _hk(r"^Cheung Sha$", "Cheung Sha, Lantau (village centre)", 1500, role="place_centre", kind="place"),
}


def hk_records(net, lk, countries):
    source = "hong_kong_observatory_weather_photos"
    index_text, receipt = AP.read_raw(net.out, source, "index_webcam.htm")
    if index_text is None:
        raise Offline("HKO index not saved")
    base = json.loads((net.out / f"{source}.json").read_text(encoding="utf-8"))["items"]
    have = {i["provider_id"] for i in base}
    placed, left = [], []
    for code, site, view, page in AP.parse_hko_index(index_text):
        if code in have:
            continue
        photo, _ = AP.read_raw(net.out, source, f"photo/{code}_photo.htm")
        title = AP.parse_hko_photo_title(photo) if photo else None
        name = f"{site} ({view})" if view else site
        spec = HK_SPECS.get(code)
        if not spec:
            left.append({"provider_id": code, "name": name, "reason": "no placement rule"})
            continue
        item = AP.page_item(source, code, f"HKO weather photo: {name}", 0.0, 0.0, "HK", "Hong Kong", page,
                            receipt["observed_at"], source_page=AP.HKO_INDEX, source_catalog=AP.HKO_INDEX,
                            photo_page_title=title, view=view or None, link_scope="official_camera_page",
                            operator="Hong Kong Observatory")
        got, why = apply_placement(item, spec, lk, countries)
        if got:
            placed.append(got)
        else:
            left.append({"provider_id": code, "name": name, "reason": why})
    return base, placed, left


# ================================================================= NOAA GML: the Mauna Kea camera
MKCAM_SPEC = {
    "kind": "osm", "area": "maunakea", "pattern": r"Submillimeter Array", "role": "named_feature",
    "feature": "Submillimeter Array (Smithsonian / ASIAA), Maunakea", "uncertainty": 300}


def noaa_records(net, lk, countries):
    source = "noaa_gml_observatory_webcams"
    doc, receipt = net.page(source, "mlo_livecam.html", W2.GML_PAGES["MLO"])
    base = json.loads((net.out / f"{source}.json").read_text(encoding="utf-8"))["items"]
    cams = [c for c in W2.parse_gml_livecam(doc, W2.GML_PAGES["MLO"]) if c["cam"] == "mkcam"]
    if not cams or "Submillimeter Array on Mauna Kea" not in (cams[0]["caption"] or ""):
        raise ValueError("the MLO page no longer says the Mauna Kea camera is at the Submillimeter Array")
    cam = cams[0]
    item = W2.item(source, "mlo:mkcam", "Mauna Kea camera (NOAA GML, at the Submillimeter Array)", 0.0, 0.0, "US",
                   "Hawaii", "station_location", "snapshot", receipt["observed_at"], snapshot=cam["image_url"],
                   page=W2.GML_PAGES["MLO"], source_page=W2.GML_PAGES["MLO"], catalog=W2.GML_PAGES["MLO"],
                   caption=cam["caption"], minimum_refresh_seconds=900, media_fetch="viewer_on_tap_only",
                   media_fetch_note="robots.txt disallows /webdata/: no build-time request or sample check")
    if not net.offline and net.client.allowed(cam["image_url"]):
        raise ValueError("robots.txt no longer disallows /webdata/: review the policy before changing the media rule")
    sites, _ = net.page("gemini_north_webcams", "gemini_sites.html", W2.GEMINI_SITES)
    gemini_north = W2.parse_gemini_sites(sites)["North"]  # Gemini's published WGS84 position: distance reference
    got, why = apply_placement(item, dict(MKCAM_SPEC, check={"centre": gemini_north, "max_km": 2}), lk, countries)
    return base, [got] if got else [], [] if got else [{"provider_id": "mlo:mkcam", "reason": why}]


def macau_records(net, lk, countries):
    source = "macau_dsat_realtime_cameras"
    doc, receipt = net.page(source, "dsat_realtime_full.html", DSAT_INDEX)
    cams = parse_dsat_index(doc)
    sample = cams[0]
    page, _ = net.page(source, f"dsat_camera_{sample['cam_id']}.html", sample["page"])
    got = parse_dsat_camera(page)
    if got["name"] != sample["name"] or not got["player"]:
        raise ValueError("DSAT per-camera page no longer answers with the camera's player")
    placed, left, rules = [], [], collections.Counter()
    if "macau" not in lk.areas:  # no open-data features or district centres: one portal record at Macau's centre
        item = page_record(source, "index", "DSAT Macau real-time road cameras (111 cameras, index)", "MO", "Macau",
                           DSAT_INDEX, receipt["observed_at"], link_scope="camera_index", cameras_on_page=len(cams))
        spec = {"kind": "wikidata", "qid": MACAU_QID, "role": "place_centre", "feature": "Macau (SAR centre)",
                "uncertainty": 6000, "check": {"centre": MACAU_CENTRE, "max_km": 1},
                "note": "One record for DSAT's camera index: OpenStreetMap was not reachable for per-camera features or "
                        "district centres; 6 km is the radius of a circle of Macau's 118 km² (Wikidata P2046)."}
        got_portal, why = apply_placement(item, spec, lk, countries)
        return [], [got_portal] if got_portal else [], [] if got_portal else [{"provider_id": "index", "reason": why}]
    for cam in cams:
        key = macau_feature(cam["name"])
        district = macau_district(cam)
        item = page_record(source, f"cam-{cam['cam_id']}", f"DSAT camera {cam['cam_id']}: {cam['name']}", "MO", "Macau",
                           cam["page"], receipt["observed_at"], source_page=DSAT_INDEX, catalog=DSAT_INDEX,
                           district=cam["area"], sub_district=cam["sub_area"], district_zones=cam["zones"],
                           stream_platform="DSAT live player (HLS)")
        specs = []
        if key:
            specs.append(MACAU_FEATURES[key])
        if district:
            specs.append(MACAU_DISTRICTS[district])
        if not specs:
            left.append({"provider_id": item["provider_id"], "name": cam["name"],
                         "reason": "names no feature and belongs to no district with a centre"})
            continue
        res, why = first_placement(item, specs, lk, countries, {"centre": MACAU_CENTRE, "max_km": 12})
        if res:
            rules[res["coordinate_role"]] += 1
            placed.append(res)
        else:
            left.append({"provider_id": item["provider_id"], "name": cam["name"], "reason": why})
    return [], placed, left


# ================================================================= Nova Scotia: exit, named feature, else community
NS_ALIAS = {"Mt Uniacke": "Mount Uniacke", "Mt Thom": "Mount Thom", "Waverley2": "Waverley", "BuckLaw": "Bucklaw",
            "Mt William Rd": "Mount William"}
def _ns(pattern, label, floor, *, merge=False, max_extent=3000, sea=False, where=None, fixed=False):
    spec = {"kind": "osm", "area": "novascotia", "pattern": pattern, "feature": label, "uncertainty": floor,
            "role": "named_feature", "merge": merge, "max_extent_m": max_extent, "where": where, "fixed": fixed}
    if sea:  # a causeway or a bridge across open water: an offshore road feature
        spec["check"] = {"allow_sea": True}
    return spec


def _natural(t):
    return "natural" in t or "place" not in t and "highway" not in t


# Camera id -> the named feature its title is (cameras titled by a highway feature, not by a community).
NS_FEATURES = {
    "Canso Causeway": _ns(r"^Canso Causeway$", "Canso Causeway (Trans-Canada Highway)", 400, merge=True, max_extent=1500,
                          sea=True),
    "Seal Island - West": _ns(r"^Seal Island Bridge$", "Seal Island Bridge (Hwy 105), west end", 400, merge=True,
                              max_extent=1500, sea=True),
    "Seal Island - East": _ns(r"^Seal Island Bridge$", "Seal Island Bridge (Hwy 105), east end", 400, merge=True,
                              max_extent=1500, sea=True),
    "Pictou": _ns(r"^Pictou Causeway$", "Pictou Causeway", 400, merge=True, max_extent=2000, sea=True),
    "Kelly's Mountain": _ns(r"^Kelly.s Mountain$", "Kelly's Mountain (Hwy 105)", 3000, where=_natural, fixed=True),
    "Cape Smokey": _ns(r"^Cape Smokey$", "Cape Smokey (Cabot Trail)", 2000, where=_natural, fixed=True),
    "Weavers Mountain": _ns(r"^Weavers Mountain$", "Weavers Mountain", 2000, where=_natural, fixed=True),
    "North Sydney": _ns(r"^Pottle Lake$", "Pottle Lake beside Hwy 125", 500, where=lambda t: t.get("natural") == "water"),
}
NS_PLACE_UNCERTAINTY = {"city": 6000, "town": 5000}  # other place types (village, hamlet, locality...): 3,000 m
NS_RELATIVE = re.compile(r"\b(near|south of|north of|east of|west of)\b", re.I)


def ns_rule(cam):
    """('feature', key) | ('junction', exit_ref, highway, place) | ('place', place). Rule 3: 'near/south of Exit N'
    and 'road X @ road Y' do not identify one feature, so they fall back to the named community."""
    label, detail = cam["label"], cam["detail"]
    if cam["id"] in NS_FEATURES:
        return ("feature", cam["id"])
    exit_ = re.search(r"\bExit (\d+[A-Z]?)\b", detail)
    hwy = re.search(r"(?:Hwy\.?|Highway)\s*(\d+)", detail)
    place = NS_ALIAS.get(label, label)
    if exit_ and not NS_RELATIVE.search(detail):
        return ("junction", exit_.group(1), hwy.group(1) if hwy else None, place)
    return ("place", place)


def is_junction(ref):
    return lambda t: t.get("highway") == "motorway_junction" and ref in re.split(r"[;,\s]+", t.get("ref", ""))


def ns_place_spec(place):
    return {"kind": "place", "area": "novascotia", "pattern": "^" + re.escape(place) + "$",
            "feature": f"{place}, Nova Scotia (community)", "uncertainty": 3000, "by_type": NS_PLACE_UNCERTAINTY,
            "role": "place_centre"}


def ns_records(net, lk, countries):
    source = "novascotia_highway_cameras"
    doc, receipt = net.page(source, "ns_all.html", NS_LIST)
    cams = parse_ns_list(doc)
    sample, _ = net.page(source, "ns_detail_Amherst.html", "https://novascotia.ca/tran/cameras/cameradetails.asp?id=Amherst")
    if "Amherst" not in text_of(sample):
        raise ValueError("Nova Scotia camera page changed")
    places = lk.areas.get("novascotia", [])
    placed, left = [], []
    for cam in cams:
        rule = ns_rule(cam)
        detail = f" ({cam['detail']})" if cam["detail"] else ""
        pid = re.sub(r"[^A-Za-z0-9]+", "-", cam["id"]).strip("-").lower()
        item = page_record(source, pid, f"{cam['label']}{detail} — Nova Scotia highway camera", "CA", "Nova Scotia",
                           cam["page"], receipt["observed_at"], source_page=NS_LIST, catalog=NS_LIST,
                           road=cam["detail"] or None)
        specs, check = [], {"max_km": 30}
        if rule[0] == "feature":
            specs += [NS_FEATURES[rule[1]], ns_place_spec(NS_ALIAS.get(cam["label"], cam["label"]))]
        elif rule[0] == "junction":
            _, ref, hwy, place = rule
            anchor, why = pick_one(find_osm(places, "^" + re.escape(place) + "$", where=lambda t: "place" in t), 1000)
            if anchor:
                centre = feature_point(anchor)[:2]
                check["centre"] = centre
                specs.append({"kind": "osm", "area": "novascotia", "pattern": None, "where": is_junction(ref),
                              "near": centre, "max_km": 20, "cluster_m": 800, "uncertainty": 400, "fixed": True,
                              "feature": f"Highway {hwy} Exit {ref}" if hwy else f"Exit {ref}", "role": "named_feature"})
            specs.append(ns_place_spec(place))
        else:
            specs.append(ns_place_spec(rule[1]))
        got, why = first_placement(item, specs, lk, countries, check)
        if got:
            placed.append(got)
        else:
            left.append({"provider_id": pid, "name": item["name"], "reason": why})
    return [], placed, left


# ================================================================= OVSICORI: volcano or place the camera names
def _volcano(pattern, label, uncertainty):
    return {"kind": "osm", "area": "costarica", "pattern": pattern, "feature": label, "uncertainty": uncertainty,
            "fixed": True, "role": "named_feature", "where": lambda t: t.get("natural") in ("volcano", "peak", "crater")}


def _cr_place(pattern, label, uncertainty, role="place_centre", where=None):
    return {"kind": "place" if role == "place_centre" and where is None else "osm", "area": "costarica",
            "pattern": pattern, "feature": label, "uncertainty": uncertainty, "role": role, "where": where}


# Camera title -> the volcano or place it names (rule 3). The cameras watch the crater from the rim or from a
# station nearby: the uncertainty says how far the camera may stand from the named summit/crater.
OVSICORI_SPECS = {
    "camara-v-turrialba": _volcano(r"Turrialba", "Turrialba Volcano (summit)", 2000),
    "camara-2-v-turrialba": _volcano(r"Iraz[uú]", "Irazú Volcano (summit)", 2000),
    "camara-crater-v-poas": _volcano(r"Po[aá]s", "Poás Volcano (crater)", 1000),
    "camara-v-poas-so-del-crater": _volcano(r"Po[aá]s", "Poás Volcano (the camera is south-west of the crater)", 2500),
    "camara-v-poas-chahuites": _cr_place(r"Chahuites", "Chahuites (place the Poás camera looks from)", 2000),
    "rincon-de-la-vieja-sensoria2": _cr_place(r"Sensoria", "Sensoria reserve, Rincón de la Vieja", 1000,
                                              role="named_feature", where=lambda t: True),
    "camara-v-rincon-de-la-vieja-curubande": _cr_place(r"Curuband[eé]", "Curubandé (village)", 2000),
    "rincon-de-la-vieja-gavilan": _cr_place(r"Gavil[aá]n", "Gavilán (place)", 2000),
}


def ovsicori_records(net, lk, countries):
    source = "costa_rica_ovsicori_cameras"
    doc, receipt = net.page(source, "ovsicori_camaras.html", OVSICORI_INDEX)
    cams = parse_ovsicori_index(doc)
    sample = next(c for c in cams if c["slug"] == "camara-crater-v-poas")
    page, _ = net.page(source, "camera_page_crater_poas.html", sample["page"])
    if "Póas" not in text_of(page) and "Poás" not in text_of(page):
        raise ValueError("OVSICORI camera page changed")
    placed, left = [], []
    for cam in cams:
        item = page_record(source, cam["slug"], f"OVSICORI — {cam['title']}", "CR", "Costa Rica", cam["page"],
                           receipt["observed_at"], source_page=OVSICORI_INDEX, catalog=OVSICORI_INDEX)
        spec = OVSICORI_SPECS.get(cam["slug"])
        if not spec:
            left.append({"provider_id": cam["slug"], "name": cam["title"], "reason": "no placement rule"})
            continue
        got, why = first_placement(item, spec if isinstance(spec, list) else [spec], lk, countries,
                                   {"centre": (10.2, -84.2), "max_km": 150})
        if got:
            placed.append(got)
        else:
            left.append({"provider_id": cam["slug"], "name": cam["title"], "reason": why})
    return [], placed, left


# ================================================================= run
EXISTING = ("kenya_aeroclub_webcams", "hong_kong_observatory_weather_photos", "iraq_karbala_shrine_live",
            "india_temple_live_darshan_round2", "noaa_gml_observatory_webcams")
NEW = ("israel_western_wall_cameras", "brazil_transalvador_cameras", "kz_shymbulak_webcams", "macau_dsat_realtime_cameras",
       "novascotia_highway_cameras", "costa_rica_ovsicori_cameras")
KEEP_HELD = ("houston_transtar", "ccg_ice_monitoring_cameras", "colombia_sgc_volcano_cameras", "ipgp_ovsg_guadeloupe",
             "ipgp_ovsm_martinique", "ovpf_ipgp_piton_fournaise", "mvo_montserrat", "nyc_dot_tmc", "panama_canal_webcams",
             "ridot_cameras", "el_salvador_marn_snet_cameras")  # held for terms, permission, robots, relay or keys: untouched


def run(out, open_data, offline=False, lookups_only=False):
    out = Path(out)
    net = Net(out, offline)
    notes = []
    lk = lookups(net, open_data, list(OVERPASS), WIKIDATA_QIDS, notes)
    if lookups_only:
        print(json.dumps({"areas": {k: len(v) for k, v in lk.areas.items()}, "wikidata": lk.wikidata, "notes": notes},
                         ensure_ascii=False, indent=1))
        return None
    countries = P.load_countries(Path(open_data) / "ne_10m_admin_0_countries.geojson")
    pols = policies()
    report = {"family": FAMILY, "sources": [], "held": [], "not_placed": [], "check_failures": [], "hosts_refused": [],
              "notes": notes}
    missing = [k for k in OVERPASS if not net.cached("overpass:" + OVERPASS[k])]
    if missing:
        report["hosts_refused"].append({
            "host": "overpass.kumi.systems", "areas": missing,
            "reason": "HTTP 504 / read timeouts (host overloaded, 2026-11-14 20:00-22:00); at most 3 attempts per query "
                      "at least 30 s apart, then the fallbacks (Wikidata, OurAirports) or hold"})
    built = {sid: {"base": [], "placed": [], "left": []} for sid in (*EXISTING, *NEW)}

    def attempt(sids, fn):
        try:
            for sid, (base, placed, left) in fn().items():
                built[sid]["base"] = base
                built[sid]["placed"] += placed
                built[sid]["left"] += left
        except (W.Refused, OSError, ValueError, KeyError, Offline) as e:
            for sid in sids:
                built[sid]["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            if isinstance(e, W.Refused):
                m = re.search(r"https://([^/\s]+)", str(e))
                report["hosts_refused"].append({"sources": list(sids), "host": m.group(1) if m else None,
                                                "reason": str(e)[:200]})

    def singles():
        placed, left = single_page_records(net, lk, countries)
        return {sid: (None, placed.get(sid, []), left.get(sid, [])) for sid in
                ("israel_western_wall_cameras", "brazil_transalvador_cameras", "iraq_karbala_shrine_live",
                 "kz_shymbulak_webcams", "india_temple_live_darshan_round2")}

    attempt(("israel_western_wall_cameras", "brazil_transalvador_cameras", "iraq_karbala_shrine_live",
             "kz_shymbulak_webcams", "india_temple_live_darshan_round2"), singles)
    attempt(("kenya_aeroclub_webcams",), lambda: {"kenya_aeroclub_webcams": kenya_records(net, lk, countries)})
    attempt(("hong_kong_observatory_weather_photos",),
            lambda: {"hong_kong_observatory_weather_photos": hk_records(net, lk, countries)})
    attempt(("noaa_gml_observatory_webcams",), lambda: {"noaa_gml_observatory_webcams": noaa_records(net, lk, countries)})
    attempt(("macau_dsat_realtime_cameras",), lambda: {"macau_dsat_realtime_cameras": macau_records(net, lk, countries)})
    attempt(("novascotia_highway_cameras",), lambda: {"novascotia_highway_cameras": ns_records(net, lk, countries)})
    attempt(("costa_rica_ovsicori_cameras",), lambda: {"costa_rica_ovsicori_cameras": ovsicori_records(net, lk, countries)})

    for sid, b in built.items():
        if sid in EXISTING and b["base"] is None:  # single-page additions to an integrated source
            b["base"] = json.loads((out / f"{sid}.json").read_text(encoding="utf-8"))["items"]
        failures = [x for x in b["left"] if any(s in x.get("reason", "") for s in (
            "Natural Earth country", "outside every country polygon", "falls under exclusion", " km from the named place"))]
        report["check_failures"] += [{"source": sid, **x} for x in failures]
        if b.get("error") or not b["placed"]:
            reason = b.get("error") or "; ".join(sorted({x["reason"] for x in b["left"]}))[:400] or "nothing to place"
            if b["left"] and all("no OpenStreetMap data" in x["reason"] for x in b["left"]):
                reason = ("no open-data position: OpenStreetMap (Overpass) did not answer during the round (HTTP 504/"
                          "timeouts, at most 3 attempts per query) and no Wikidata or OurAirports record identifies the "
                          "named features or places")
            if sid in NEW:  # still held: same id, reason updated
                write_policy(out, sid, W2.held(sid, pols[sid]["source"]["name"], pols[sid]["source"]["url"],
                                               f"placement round: not placed ({reason})",
                                               "an open-data position for the named feature or place (retry the cached Overpass lookups when the host answers)",
                                               pols[sid]["source"]["evidence"]))
                report["held"].append({"id": sid, "reason": reason, "left_out": b["left"]})
            else:  # integrated source: its round-2 input stays as it is, the cameras stay out
                stale = out / f"{sid}.places.json"
                if stale.exists():
                    stale.unlink()  # this collector's own earlier output, now without new records
                report["not_placed"].append({"id": sid, "reason": reason, "left_out": b["left"]})
            continue
        items = (b["base"] or []) + b["placed"]
        ids = collections.Counter(i["id"] for i in items)
        if any(n > 1 for n in ids.values()):
            raise ValueError(f"{sid}: duplicate ids {[i for i, n in ids.items() if n > 1][:3]}")
        if sid in EXISTING:
            name = f"{sid}.places.json"
            W.write_catalog(out / name, [sid], items, supersedes=[sid])
        else:
            name = f"{sid}.json"
            W.write_catalog(out / name, [sid], items)
        if sid == "macau_dsat_realtime_cameras" and [i["provider_id"] for i in items] == ["index"]:
            pols[sid]["source"]["provider_notice"] = ("Opens DSAT's camera index (111 cameras). The marker is Macau's "
                                                      "centre, not a camera.")
        write_policy(out, sid, pols[sid])
        report["sources"].append({
            "id": sid, "country": sorted({i["country"] for i in items}), "input_file": name,
            "supersedes": sid if sid in EXISTING else None, "records_total": len(items),
            "records_kept_from_round2": len(b["base"] or []), "records_placed": len(b["placed"]),
            "viewable": sum(1 for i in items if i["format"] == "snapshot"), "placed": summarize(b["placed"]),
            "left_out": b["left"]})
    report["kept_held_untouched"] = list(KEEP_HELD)
    report["decisions"] = [
        "Macau (rule 3): per-camera pages work (sample cam 122 answered with its player), but 52 of 111 names are "
        "streets or street corners (never guessed) and the bridge/port/roundabout features and district centres need "
        "OpenStreetMap, which did not answer: one portal record at Macau's Wikidata centre (6 km) instead. The "
        "per-feature/district rules are in the collector and run as soon as the Macau Overpass area is cached.",
        "Kenya: every left-out camera page was read (66 pages): the Location line names the site; the pages' weather "
        "and Google Earth links are template copies (same point on unrelated pages) and are not used. Where the page "
        "ties the camera to an airfield, the OurAirports airfield is the named feature with the stated distance in "
        "the uncertainty; lodges, farms and towns needed OpenStreetMap and stay out.",
        "Hong Kong: Natural Earth 10 m leaves Victoria Harbour's reclaimed shore and Lantau's south coast at sea, so "
        "ICC, Sai Wan Ho and Cheung Sha fail the sea check and stay out; the Maritime Museum stands on Central Pier 8 "
        "(port feature, sea allowed).",
        "Round-2 collectors adjusted so a re-run cannot undo this round: collect_world2 no longer writes held "
        "fragments for the 4 sources placed here and its Karbala/India policies carry the new page hosts; "
        "collect_americas_pages no longer writes Nova Scotia's held fragment; collect_apac_pages' HKO notice covers "
        "placed sites (test_collect_apac_pages.PolicyTest passes once that fragment is merged into the registry). "
        "collect_latam still writes Costa Rica's held fragment on a re-run (same held state now)."]
    report["lookups"] = {"overpass_areas": {k: len(v) for k, v in lk.areas.items()},
                         "wikidata": sorted(lk.wikidata), "ourairports_rows": len(lk.airports),
                         "cache": str(net.cache)}
    report["requests"] = {"new": sum(1 for r in net.reads if not r["reused"]),
                          "reused": sum(1 for r in net.reads if r["reused"])}
    report["robots"] = {base: (rule if isinstance(rule, str) else "read and honoured")
                        for base, rule in net.client.robots.items()}
    report["generated_at"] = W.now()
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def write_policy(out, sid, entry):
    (Path(out) / "policies").mkdir(parents=True, exist_ok=True)
    (Path(out) / "policies" / f"{sid}.json").write_text(json.dumps({sid: entry}, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the webcam-inputs folder (inputs, raw/, policies/, reports/)")
    ap.add_argument("--open-data", help="folder with ne_10m_admin_0_countries.geojson and ourairports_airports.csv "
                                        "(default: <out>/../open-data)")
    ap.add_argument("--offline", action="store_true", help="use only saved pages and cached lookups")
    ap.add_argument("--lookups-only", action="store_true", help="run the Overpass/Wikidata lookups and stop")
    args = ap.parse_args(argv)
    open_data = args.open_data or str(Path(args.out).resolve().parent / "open-data")
    report = run(args.out, open_data, args.offline, args.lookups_only)
    if report:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"sources": [{k: s[k] for k in ("id", "records_total", "records_placed", "placed")}
                                      for s in report["sources"]],
                          "held": [{"id": h["id"], "reason": h["reason"][:200]} for h in report["held"]],
                          "not_placed": [h["id"] for h in report["not_placed"]],
                          "check_failures": len(report["check_failures"]), "requests": report["requests"]},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
