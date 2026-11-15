"""Placing cameras whose operator publishes no position (build_webcams.PLACED_ROLES).

Hierarchy: an official position (no placement needed) > the exact named feature in an open dataset
(OSM node/way, OurAirports for airfields, Wikidata for landmarks) > the place centre (last resort).
Every placed record says so: coordinate_role named_feature | place_centre, coordinate_source
(osm:node/123, wikidata:Q42, ourairports:HKJK, ...), coordinate_source_licence, coordinate_feature,
coordinate_uncertainty_m and identity_confirmed=false. Sanity checks run offline: the Natural Earth
country must match the source's country, no point at sea unless it is a port/offshore feature, a
reasonable distance from the named place, and the legal/safety exclusion rules. Online lookups go
through webcam_fetch.PoliteClient (robots.txt, >=1 s per host) and are cached by the caller.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from urllib.parse import quote

try:
    from collect_world_webcam_links import Countries
    import build_webcams as B
except ModuleNotFoundError:  # repository-root imports in tests
    from scripts.collect_world_webcam_links import Countries
    import scripts.build_webcams as B

LICENCES = {"osm": "ODbL 1.0", "wikidata": "CC0 1.0", "ourairports": "Public Domain (OurAirports)"}
OVERPASS = "https://overpass.kumi.systems/api/interpreter"


def place(item, *, role, lat, lng, source, feature, uncertainty_m, licence=None):
    """Set a QGlobe-placed position on an item (role named_feature or place_centre)."""
    if role not in B.PLACED_ROLES:
        raise ValueError(f"unknown placed role {role}")
    if not (isinstance(uncertainty_m, (int, float)) and uncertainty_m > 0):
        raise ValueError("uncertainty_m must be positive")
    kind = source.split(":", 1)[0]
    item.update({"lat": round(float(lat), 6), "lng": round(float(lng), 6), "coordinate_role": role,
                 "coordinate_source": source, "coordinate_source_licence": licence or LICENCES.get(kind),
                 "coordinate_feature": feature, "coordinate_uncertainty_m": int(round(uncertainty_m)),
                 "identity_confirmed": False})
    return item


def distance_km(lat1, lng1, lat2, lng2):
    return B.distance_m(lat1, lng1, lat2, lng2) / 1000


def check(item, countries, *, expected_country=None, centre=None, max_km=None, allow_sea=False, rules=None):
    """Reasons this placement must not be published (empty list = fine)."""
    problems = []
    found = countries.country(item["lat"], item["lng"])
    expected = expected_country or item.get("country")
    if found == "ZZ":
        if not allow_sea:
            problems.append("outside every country polygon (sea or border gap)")
    elif expected and found != expected:
        problems.append(f"Natural Earth country {found}, source country {expected}")
    if centre and max_km is not None:
        far = distance_km(item["lat"], item["lng"], centre[0], centre[1])
        if far > max_km:
            problems.append(f"{far:.1f} km from the named place centre (limit {max_km} km)")
    rule = B.exclusion_rule(item, rules if rules is not None else B.load_exclusions()["rules"])
    if rule:
        problems.append(f"falls under exclusion rule {rule['id']}")
    return problems


def load_countries(path):
    return Countries(json.loads(Path(path).read_text(encoding="utf-8")))


def ourairports(path):
    """ident -> (lat, lng, name) from OurAirports airports.csv (public domain)."""
    import csv
    with open(path, encoding="utf-8", newline="") as f:
        return {row["ident"]: (float(row["latitude_deg"]), float(row["longitude_deg"]), row["name"])
                for row in csv.DictReader(f) if row.get("latitude_deg") and row.get("longitude_deg")}


def cached_json(cache_dir, key, fetch):
    """Return the cached JSON for key, or fetch it once and cache it (rebuilds never repeat a lookup)."""
    path = Path(cache_dir) / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["data"]
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": key, "data": data}, ensure_ascii=False), encoding="utf-8")
    return data


def overpass(client, query, cache_dir):
    """One Overpass QL query (GET, robots-checked, polite), cached by its text."""
    return cached_json(cache_dir, "overpass:" + query,
                       lambda: client.get_json(OVERPASS + "?data=" + quote(query), max_bytes=40 * 1024 * 1024)[0])


def wikidata_coordinates(client, qid, cache_dir):
    """(lat, lng) of a Wikidata item's P625, cached."""
    data = cached_json(cache_dir, "wikidata:" + qid, lambda: client.get_json(
        f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")[0])
    claims = data["entities"][qid]["claims"].get("P625") or []
    if not claims:
        return None
    value = claims[0]["mainsnak"]["datavalue"]["value"]
    return value["latitude"], value["longitude"]


def element_point(el):
    """Overpass element -> (lat, lng) for nodes, or the centre of ways/relations (out center)."""
    if el.get("type") == "node":
        return el["lat"], el["lon"]
    centre = el.get("center") or {}
    return (centre["lat"], centre["lon"]) if centre else None


def round_trip_ok(lat, lng):
    return math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180
