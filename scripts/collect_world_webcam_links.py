#!/usr/bin/env python3
"""Normalize explicit OSM/Wikidata webcam links without requesting any camera.

Offline input: osm_webcams.json, wikidata_webcams.json, naturalearth_countries.json
and their *_receipt.json files. Acquisitions must be complete and SHA256-matched.
Natural Earth country inference is approximate; it never changes coordinates.
OSM feature centres and Wikidata place coordinates never establish camera identity.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
from build_webcams import page_url, private_url_reason, write_json

SOURCES = [
    {"id": "osm_webcams", "name": "OpenStreetMap explicit webcam links",
     "url": "https://wiki.openstreetmap.org/wiki/Webcams",
     "terms_url": "https://www.openstreetmap.org/copyright", "metadata_license": "ODbL-1.0",
     "media_rights": "Metadata license only. Linked publishers retain their media rights; no embedding authorized.",
     "attribution": "© OpenStreetMap contributors, ODbL 1.0. Webcam metadata normalized by QGlobe.",
     "rights_status": "official_page_only", "allowed_hosts": [], "provenance_type": "community_directory"},
    {"id": "wikidata_webcams", "name": "Wikidata webcam page links (P4238)",
     "url": "https://www.wikidata.org/wiki/Property:P4238",
     "terms_url": "https://www.wikidata.org/wiki/Wikidata:Licensing", "metadata_license": "CC0-1.0",
     "media_rights": "CC0 applies to structured metadata, not linked pictures or streams. External links only.",
     "attribution": "Wikidata contributors, CC0. Webcam metadata normalized by QGlobe.",
     "rights_status": "official_page_only", "allowed_hosts": [], "provenance_type": "community_directory"},
]


def load_verified(folder, name):
    body = (folder / (name + ".json")).read_bytes()
    receipt = json.loads((folder / (name + "_receipt.json")).read_text())
    if receipt.get("status") != 200 or receipt.get("sha256") != hashlib.sha256(body).hexdigest() or receipt.get("bytes") != len(body):
        raise ValueError(f"Incomplete or hash-mismatched metadata acquisition: {name}")
    return json.loads(body), receipt


def bbox(ring):
    return min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring)


def in_box(x, y, box):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def in_ring(x, y, ring):
    inside = False
    x0, y0 = ring[-1][:2]
    for point in ring:
        x1, y1 = point[:2]
        if (y1 > y) != (y0 > y) and x < (x0-x1)*(y-y1)/(y0-y1)+x1:
            inside = not inside
        x0, y0 = x1, y1
    return inside


class Countries:
    """Small offline point-in-polygon index using public-domain Natural Earth."""
    def __init__(self, geojson):
        self.rows = []
        for f in geojson["features"]:
            p, g = f["properties"], f["geometry"]
            code = p.get("ISO_A2_EH") or p.get("ISO_A2")
            if not isinstance(code, str) or not re.fullmatch("[A-Z]{2}", code):
                continue
            polygons = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for rings in polygons:
                if rings and len(rings[0]) >= 4:
                    self.rows.append((bbox(rings[0]), code, rings))

    def country(self, lat, lng):
        found = {code for box, code, rings in self.rows if in_box(lng, lat, box)
                 and in_ring(lng, lat, rings[0]) and not any(in_ring(lng, lat, hole) for hole in rings[1:])}
        return next(iter(found)) if len(found) == 1 else "ZZ"


def valid_coords(lat, lng):
    return isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180 and (lat != 0 or lng != 0)


def normalize(folder):
    osm, osm_receipt = load_verified(folder, "osm_webcams")
    wd, wd_receipt = load_verified(folder, "wikidata_webcams")
    ne, ne_receipt = load_verified(folder, "naturalearth_countries")
    if osm.get("remark") or not isinstance(osm.get("elements"), list):
        raise ValueError("Overpass response is incomplete or includes a runtime error")
    countries = Countries(ne)
    items, rejected, duplicate_rows = [], [], []
    for element in osm["elements"]:
        tags = element.get("tags", {})
        pos = element if element["type"] == "node" else element.get("center", {})
        lat, lng = pos.get("lat"), pos.get("lon")
        element_id = f"{element['type']}-{element['id']}"
        if not valid_coords(lat, lng):
            rejected.append({"provider": "osm_webcams", "provider_id": element_id, "reason": "invalid_coordinates"})
            continue
        fields = ["contact:webcam", "webcam"]
        if tags.get("surveillance") == "webcam" or tags.get("tourism") == "webcam":
            fields += ["website", "url", "contact:website"]
        found = {}
        for field in fields:
            value = tags.get(field, "")
            for candidate in re.split(r";\s*(?=https?://)", value):
                if not candidate:
                    continue
                # Community links: camera device endpoints are refused too (privacy filter).
                link = page_url(candidate, community=True)
                if not link:
                    privacy = private_url_reason(candidate, community=True)
                    rejected.append({"provider": "osm_webcams", "provider_id": element_id, "field": field,
                                     **({} if privacy else {"value_sha256": hashlib.sha256(candidate.encode()).hexdigest()}),
                                     "reason": f"privacy_filter_{privacy}" if privacy else "unsafe_or_non_url_webcam_tag"})
                    continue
                found.setdefault(link, []).append(field)
        role = "camera_location" if element["type"] == "node" and (tags.get("surveillance:type") == "camera" or tags.get("surveillance") == "webcam" or tags.get("tourism") == "webcam" or tags.get("man_made") == "surveillance") else "associated_feature" if element["type"] == "node" else "feature_center"
        declared_country = str(tags.get("addr:country") or tags.get("ISO3166-1:alpha2") or "").upper()
        direct_country = bool(re.fullmatch("[A-Z]{2}", declared_country))
        country = declared_country if direct_country else countries.country(lat, lng)
        for link, fields_used in sorted(found.items()):
            provider_id = element_id + "-" + hashlib.sha256(link.encode()).hexdigest()[:12]
            items.append({"provider": "osm_webcams", "provider_id": provider_id, "id": "osm_webcams:" + provider_id,
                          "name": tags.get("name") or tags.get("description") or "Webcam · " + urlsplit(link).hostname,
                          "lat": lat, "lng": lng, "country": country, "region": tags.get("addr:city") or tags.get("addr:state") or "",
                          "country_inferred": not direct_country and country != "ZZ",
                          "country_basis": "source_tag" if direct_country else "Natural Earth 1:10m polygon; approximate, not a boundary ruling",
                          "format": "official_page", "stream_url": None, "snapshot_url": None, "official_page": link,
                          "source_page": f"https://www.openstreetmap.org/{element['type']}/{element['id']}",
                          "source_catalog": "https://wiki.openstreetmap.org/wiki/Webcams", "rights_status": "official_page_only",
                          "observed_at": osm_receipt["observed_at"], "coordinate_role": role,
                          "osm_type": element["type"], "osm_id": element["id"], "webcam_tag_keys": fields_used,
                          "location_group_id": "osm:" + element_id, "operator": tags.get("operator"),
                          "direction": tags.get("camera:direction") or tags.get("direction"),
                          "link_scope": "published_webcam_reference", "link_provenance": "community_directory",
                          "identity_basis": "OSM element and explicit published webcam URL", "health": {"status": "unverified"}})
    grouped = collections.defaultdict(list)
    for binding in wd["results"]["bindings"]:
        value = {k: v["value"] for k, v in binding.items()}
        link = page_url(value.get("webcam"), community=True)
        qid = value.get("item", "").rsplit("/", 1)[-1]
        match = re.fullmatch(r"Point\(([-+0-9.eE]+) ([-+0-9.eE]+)\)", value.get("coord", ""))
        if not link or not re.fullmatch(r"Q[1-9][0-9]*", qid) or not match:
            rejected.append({"provider": "wikidata_webcams", "provider_id": qid, "reason": "invalid_link_item_or_coordinate",
                             "value_sha256": hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()})
            continue
        lng, lat = map(float, match.groups())
        if not valid_coords(lat, lng):
            rejected.append({"provider": "wikidata_webcams", "provider_id": qid, "reason": "invalid_coordinates"})
            continue
        grouped[(qid, link, lat, lng)].append(value)
    for (qid, link, lat, lng), rows in sorted(grouped.items()):
        if len(rows) > 1:
            duplicate_rows.append({"qid": qid, "url": link, "query_rows": len(rows)})
        codes = {r["countryCode"] for r in rows if re.fullmatch("[A-Z]{2}", r.get("countryCode", ""))}
        direct_country = len(codes) == 1
        country = next(iter(codes)) if direct_country else countries.country(lat, lng)
        # Multiple coordinate statements stay distinct; neither is silently picked.
        key = f"{link}|{lat:.8f}|{lng:.8f}"
        provider_id = qid + "-" + hashlib.sha256(key.encode()).hexdigest()[:12]
        items.append({"provider": "wikidata_webcams", "provider_id": provider_id, "id": "wikidata_webcams:" + provider_id,
                      "name": next((r["label"] for r in rows if r.get("label")), qid), "lat": lat, "lng": lng,
                      "country": country, "region": "", "country_inferred": not direct_country and country != "ZZ",
                      "country_basis": "Wikidata P17/P297" if direct_country else "Natural Earth 1:10m polygon; approximate",
                      "format": "official_page", "stream_url": None, "snapshot_url": None, "official_page": link,
                      "source_page": "https://www.wikidata.org/wiki/" + qid,
                      "source_catalog": "https://www.wikidata.org/wiki/Property:P4238", "rights_status": "official_page_only",
                      "observed_at": wd_receipt["observed_at"], "coordinate_role": "associated_feature",
                      "location_group_id": "wikidata:" + qid, "wikidata_id": qid,
                      "link_scope": "published_webcam_reference", "link_provenance": "community_directory",
                      "coordinate_note": "P625 locates the described place, not necessarily its webcam. Do not proximity-match as an exact camera.",
                      "health": {"status": "unverified"}})
    items.sort(key=lambda r: r["id"])
    report = {"records": len(items), "by_provider": dict(collections.Counter(r["provider"] for r in items)),
              "by_country": dict(sorted(collections.Counter(r["country"] for r in items).items())),
              "coordinate_roles": dict(collections.Counter(r["coordinate_role"] for r in items)),
              "unknown_country_records": sum(r["country"] == "ZZ" for r in items), "rejected_values": len(rejected),
              "collapsed_wikidata_join_rows": sum(r["query_rows"]-1 for r in duplicate_rows),
              "camera_urls_requested": 0, "osm_base_timestamp": osm.get("osm3s", {}).get("timestamp_osm_base"),
              "natural_earth_sha256": ne_receipt["sha256"], "country_inference_license": "Natural Earth public domain",
              "acquisitions": [osm_receipt, wd_receipt, ne_receipt]}
    return {"schema_version": 1, "sources": SOURCES, "items": items}, report, rejected, duplicate_rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    catalog, report, rejected, duplicates = normalize(args.source_dir)
    write_json(args.out, catalog)
    write_json(args.out.with_name("summary.json"), report)
    write_json(args.out.with_name("rejected_records.json"), rejected)
    write_json(args.out.with_name("query_duplicate_rows.json"), duplicates)
    print(json.dumps({k: v for k, v in report.items() if k != "acquisitions"}, indent=2))


if __name__ == "__main__":
    main()
