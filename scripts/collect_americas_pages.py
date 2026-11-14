#!/usr/bin/env python3
"""Collect US/Canada official camera lists as page links (official_page) for the Q-Globe catalogue (stdlib only).

Integrated when the keyless list answers with coordinates (2026-11 Americas register ids):
  drivenc_ncdot       NCDOT_Cameras ArcGIS layer (official NCDOT org): links to DriveNC's camera list page
  lincoln_ne_traffic  City of Lincoln traffic camera layer: links to the city's video.html viewer pages
  idaho_511_itd       ITD GIS CCTV layer (keyless): links to 511 Idaho's camera list page
No image is fetched or embedded: the terms of these operators do not license the media for a paid app.
Every other source of this family is written as a held policy with its reason (no records).

  python scripts/collect_americas_pages.py --out <dir>
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as W  # noqa: E402

FAMILY = "americas_pages"
REVIEWED_AT = "2026-11-14"

NC_LAYER = "https://services.arcgis.com/NuWFvHYDMVmmxMeM/arcgis/rest/services/NCDOT_Cameras/FeatureServer/0"
NC_QUERY = (NC_LAYER + "/query?where=1%3D1&outFields=OBJECTID,CameraId,CameraStatus,Description,Division,Highway,"
            "LocationName,Latitude,Longitude,County,ImageStatus&returnGeometry=true&outSR=4326&orderByFields=OBJECTID"
            "&resultRecordCount=2000&f=json")
NC_ITEM = "https://www.arcgis.com/home/item.html?id=eace738dc8d44ff99b2793459572d86e"
NC_PAGE = "https://www.drivenc.gov/cctv"
NC_TERMS = "https://www.ncdot.gov/about-us/how-we-operate/policy-process/Pages/terms-use.aspx"

LN_LAYER = "https://services1.arcgis.com/wpJGOi6N4Rq5cqFv/arcgis/rest/services/TrafficCamerasMap_WFL1/FeatureServer/0"
LN_QUERY = LN_LAYER + "/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&orderByFields=OBJECTID&f=json"
LN_ITEM = "https://www.arcgis.com/home/item.html?id=9b9cb862992847c4994ce060a1c59372"
LN_VIEWER_HOST = "ticcamvw02.lincoln.ne.gov"

ID_LAYER = "https://gisp.itd.idaho.gov/server/rest/services/GDWarehouse/IntelligentTransportationSystems/MapServer/0"
ID_QUERY = ID_LAYER + "/query?where=1%3D1&outFields=*&returnGeometry=false&f=json"
ID_ITEMINFO = "https://gisp.itd.idaho.gov/server/rest/services/GDWarehouse/IntelligentTransportationSystems/MapServer/info/iteminfo"
ID_PAGE = "https://511.idaho.gov/cctv"


def coords(lat, lng, box=None):
    lat, lng = float(lat), float(lng)
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError("no usable coordinates")
    if box and not (box[0] <= lat <= box[1] and box[2] <= lng <= box[3]):
        raise ValueError("coordinates outside the operator's area")
    return round(lat, 6), round(lng, 6)


def features(doc):
    if not isinstance(doc, dict) or "error" in doc or not isinstance(doc.get("features"), list):
        raise ValueError("not an ArcGIS feature set")
    if doc.get("exceededTransferLimit"):
        raise ValueError("ArcGIS transfer limit exceeded: list incomplete")
    return doc["features"]


def page_item(provider, pid, name, lat, lng, region, page, catalog, source_page, observed_at, **extra):
    item = {"provider": provider, "provider_id": pid, "id": f"{provider}:{pid}", "name": name, "lat": lat, "lng": lng,
            "country": "US", "region": region, "coordinate_role": "camera_location", "format": "official_page",
            "stream_url": None, "snapshot_url": None, "official_page": page, "source_page": source_page,
            "source_catalog": catalog, "rights_status": "official_page_only", "observed_at": observed_at,
            "health": {"status": "unverified"}}
    item.update({k: v for k, v in extra.items() if v not in (None, "")})
    return item


def count(excluded, reason):
    excluded[reason] = excluded.get(reason, 0) + 1


# ================================================================= parsers (pure)
def parse_ncdot(doc, observed_at):
    items, excluded, seen = [], {}, set()
    for f in features(doc):
        a = f.get("attributes") or {}
        status = str(a.get("CameraStatus") or "")
        if not status.startswith("Active"):
            count(excluded, "not_active")
            continue
        pid = str(a.get("CameraId") or "").strip()
        try:
            lat, lng = coords(a.get("Latitude"), a.get("Longitude"), (33.5, 37.0, -84.6, -75.2))
        except (TypeError, ValueError):
            count(excluded, "no_coordinates")
            continue
        if not re.fullmatch(r"[0-9]{1,10}", pid) or pid in seen:
            count(excluded, "bad_or_duplicate_id")
            continue
        seen.add(pid)
        name = str(a.get("LocationName") or a.get("Description") or pid).strip()
        items.append(page_item("drivenc_ncdot", pid, name, lat, lng, "NC", NC_PAGE, NC_LAYER, NC_PAGE, observed_at,
                               road=a.get("Highway"), county=a.get("County"), provider_status=status,
                               provider_in_service=status == "Active Streaming", link_scope="provider_camera_list"))
    return items, excluded


def parse_lincoln(doc, observed_at):
    items, excluded, seen = [], {}, set()
    for f in features(doc):
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        pid = str(a.get("Camera_ID") or "").strip()
        page = str(a.get("LiveSDURL") or a.get("LiveHDURL") or "")
        u = urlsplit(page)
        if u.scheme != "https" or u.hostname != LN_VIEWER_HOST or u.path != "/video.html":
            count(excluded, "no_city_viewer_page")
            continue
        try:
            lat, lng = coords(g.get("y"), g.get("x"), (40.5, 41.1, -97.0, -96.4))
        except (TypeError, ValueError):
            count(excluded, "no_coordinates")
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}", pid) or pid in seen:
            count(excluded, "bad_or_duplicate_id")
            continue
        seen.add(pid)
        items.append(page_item("lincoln_ne_traffic", pid, str(a.get("Camera_Location") or pid).strip(), lat, lng, "NE",
                               page, LN_LAYER, LN_ITEM, observed_at, link_scope="provider_viewer_page"))
    return items, excluded


def parse_idaho(doc, observed_at):
    items, excluded, seen = [], {}, set()
    for f in features(doc):
        a = f.get("attributes") or {}
        pid = str(a.get("GlobalID") or "").strip("{} ").lower()
        try:
            lat, lng = coords(a.get("Latitude"), a.get("Longitude"), (41.9, 49.1, -117.3, -110.9))
        except (TypeError, ValueError):
            count(excluded, "no_coordinates")
            continue
        if not re.fullmatch(r"[0-9a-f-]{36}", pid) or pid in seen:
            count(excluded, "bad_or_duplicate_id")
            continue
        seen.add(pid)
        name = str(a.get("LocationName") or a.get("UniqueID") or pid).strip()
        items.append(page_item("idaho_511_itd", pid, name, lat, lng, "ID", ID_PAGE, ID_LAYER, ID_PAGE, observed_at,
                               city=a.get("City"), county=a.get("County"), itd_district=a.get("District"),
                               itd_camera_label=a.get("UniqueID"), location_address=a.get("LocationAddress"),
                               link_scope="provider_camera_list"))
    return items, excluded


# ================================================================= policies
def page_policy(sid, name, url, catalog, terms, licence, media_rights, attribution, page_hosts, evidence, note=None, **extra):
    policy = {
        "source": {"id": sid, "name": name, "url": url, "catalog_url": catalog, "terms_url": terms,
                   "metadata_license": licence, "license": licence, "media_rights": media_rights,
                   "rights_note": note or media_rights, "attribution": attribution, "rights_status": "official_page_only",
                   "allowed_hosts": [], "review_status": "reviewed_for_external_references_only",
                   "reviewed_at": REVIEWED_AT, "evidence": evidence},
        "media_hosts": [], "page_hosts": page_hosts, "formats": ["official_page"], "countries": ["US"],
        "operator_hints": [], "coordinate_role": "camera_location"}
    policy.update(extra)
    return policy


def policies():
    return {
        "drivenc_ncdot": page_policy(
            "drivenc_ncdot", "NCDOT DriveNC traffic cameras (NCDOT_Cameras layer)", NC_PAGE, NC_LAYER, NC_TERMS,
            "No licence stated on the official NCDOT_Cameras ArcGIS item (owner TIMSApp.NCDOT.GOV); factual camera "
            "list, links only",
            "NCDOT grants copying and distribution of images 'for non-commercial use' only: no image is fetched or "
            "embedded; each record links to DriveNC's camera list.",
            "North Carolina Department of Transportation (NCDOT) / DriveNC. Metadata normalized by QGlobe.",
            ["www.drivenc.gov"], [NC_TERMS, NC_ITEM, NC_LAYER],
            "DriveNC publishes no per-camera page outside its map; the camera list page is linked.",
            official_map_url=NC_PAGE),
        "lincoln_ne_traffic": page_policy(
            "lincoln_ne_traffic", "City of Lincoln (NE) traffic cameras", LN_ITEM, LN_LAYER, LN_ITEM,
            "No licence stated on the city's public feature service ('Traffic camera feeds used for public facing "
            "applications'); factual list, links only",
            "No licence for video or photos: each record links to the city's own video.html viewer page; the "
            "accliveviewer (VMS) path is not used.", "City of Lincoln, Nebraska", [LN_VIEWER_HOST], [LN_ITEM, LN_LAYER]),
        "idaho_511_itd": page_policy(
            "idaho_511_itd", "Idaho Transportation Department CCTV sites (511 Idaho)", ID_PAGE, ID_LAYER, ID_ITEMINFO,
            "ITD Spatial Data Disclaimer (data provided 'as is'); factual list from the keyless ITD GIS layer, links only",
            "No licence for images (the GIS layer has no image URLs; the 511 Idaho key was not used): each record "
            "links to 511 Idaho's camera list.", "Idaho Transportation Department / 511 Idaho", ["511.idaho.gov"],
            [ID_ITEMINFO + "?f=json", ID_LAYER], official_map_url=ID_PAGE),
    }


def held(sid, name, url, reason, until, evidence):
    return {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
            "source": {"id": sid, "name": name, "url": url}}


HELD = {
    "novascotia_highway_cameras": held(
        "novascotia_highway_cameras", "Nova Scotia highway cameras", "https://novascotia.ca/tran/cameras/all.asp",
        "List re-read 2026-11-14: 55 per-camera pages, but neither the list nor a camera page publishes a position.",
        "published camera positions (or a documented gazetteer accepted as approximate)",
        ["https://novascotia.ca/tran/cameras/all.asp", "https://511.novascotia.ca/about/about"]),
    "ccg_ice_monitoring_cameras": held(
        "ccg_ice_monitoring_cameras", "Canadian Coast Guard ice monitoring cameras",
        "https://e-navigation.canada.ca/topics/cameras/index-en",
        "Single list page without camera positions or per-camera pages; Government of Canada terms bar commercial "
        "redistribution without permission.", "published camera positions and a per-camera page",
        ["https://e-navigation.canada.ca/topics/cameras/index-en", "https://www.canada.ca/en/transparency/terms.html"]),
    "houston_transtar": held(
        "houston_transtar", "Houston TranStar traffic cameras", "https://traffic.houstontranstar.org/cctv/transtar/",
        "Camera list and map pages re-read 2026-11-14: road-by-road lists and an image map, no camera coordinates; "
        "TxDOT terms forbid linking to specific images (pages only).",
        "a published camera list with coordinates", ["https://traffic.houstontranstar.org/disclaimer.aspx"]),
    "nyc_dot_tmc": held(
        "nyc_dot_tmc", "NYC DOT Traffic Management Center webcams", "https://webcams.nyctmc.org/",
        "webcams.nyctmc.org did not serve robots.txt on 2026-11-14 (unreachable, treated as disallow); camera list, "
        "coordinates and stable per-camera pages unverified.", "a reachable list with coordinates and stable camera pages",
        ["https://www.nyc.gov/html/dot/html/motorist/atis.shtml", "https://www.nyc.gov/main/terms-of-use"]),
    "phenocam_network": held(
        "phenocam_network", "PhenoCam Network (Northern Arizona University)", "https://phenocam.nau.edu/",
        "Licence confirmation needed for in-app display (held by the brief); robots disallows /data/ for image probes.",
        "PhenoCam's confirmation of CC BY 4.0 display in a paid app", ["https://phenocam.nau.edu/webcam/fairuse_statement/"]),
    "newengland511_compass": held(
        "newengland511_compass", "New England Compass (Maine DOT, NHDOT, VTrans)", "http://nec-por.ne-compass.com/DeveloperPortal",
        "Images only as base64 inside per-state bulk XML: needs an image relay (or a per-camera HTTPS image URL) and "
        "the developer terms agreement.", "an image relay decision or per-camera HTTPS images under the same terms",
        ["http://nec-por.ne-compass.com/DeveloperPortal/Home/Terms"]),
    "fl511_fdot": held(
        "fl511_fdot", "FL511 / FDOT traffic cameras", "https://fl511.com/cctv",
        "Conditional in the register: FDOT third-party feed agreement for media; page listing deferred by the brief.",
        "FDOT feed agreement / confirmation", ["https://www.arcgis.com/home/item.html?id=79023e7f3a4948cf80c91534e565cdcf"]),
    "ridot_cameras": held(
        "ridot_cameras", "RIDOT traffic cameras", "https://www.dot.ri.gov/travel/",
        "Conditional: RIDOT confirmation that the RI.gov copyright policy covers camera images; no coordinates "
        "(names carry route/exit only).", "RIDOT confirmation and a positioned list", ["https://ri.gov/policies/copyright"]),
    "bellevue_wa_traffic": held(
        "bellevue_wa_traffic", "City of Bellevue traffic cameras", "https://trafficmap.bellevuewa.gov/",
        "No documented camera list endpoint (list loaded by the map's script bundle).", "a documented list with positions",
        ["https://bellevuewa.gov/city-government/departments/transportation/traffic-conditions"]),
    "sioux_falls_traffic": held(
        "sioux_falls_traffic", "City of Sioux Falls traffic cameras", "https://gis.siouxfalls.gov/arcgis/rest/services/Data/Traffic/MapServer/8",
        "Server unreachable in research (connection refused/timeout); not retried by this adapter.",
        "the city GIS server answering", ["https://www.arcgis.com/home/item.html?id=71ee3a06d0aa476d8c8545761dde916e"]),
    "us_ski_tourism_pattern": held(
        "us_ski_tourism_pattern", "US ski resort and tourism webcams (pattern)", "https://www.roundshot.com/",
        "No list or coordinates in the register; would need a hand-curated list per resort terms.",
        "a curated list with per-resort terms and positions", ["https://www.roundshot.com/de/service/legal.html/106"]),
    "explore_org_livecams": held(
        "explore_org_livecams", "explore.org live nature cams", "https://explore.org/livecams",
        "No list or coordinates in the register; terms allow deep links but not automated harvesting.",
        "a hand-curated list with positions", ["https://explore.org/terms-of-service"]),
    "iowa_soda_plow_cams": held(
        "iowa_soda_plow_cams", "Snow plow dash cameras (Nebraska view)", "https://www.arcgis.com/home/item.html?id=e254de3a5ced49fb89de03fe97b0fd11",
        "Skipped: moving vehicle cameras, last images May 2023, not fixed webcams.", "not planned",
        ["https://www.arcgis.com/home/item.html?id=e254de3a5ced49fb89de03fe97b0fd11"]),
}
REFUSED_HOSTS = {"nyc_dot_tmc": "webcams.nyctmc.org"}


# ================================================================= network run
def run(out, client=None):
    out = Path(out)
    client = client or W.PoliteClient()
    pols = policies()
    report = {"family": FAMILY, "sources": [], "held": [], "hosts_refused": []}

    def write_policy(source, entry):
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{source}.json").write_text(json.dumps({source: entry}, ensure_ascii=False, indent=1), encoding="utf-8")

    def hold(source, entry, host=None):
        write_policy(source, entry)
        report["held"].append({"id": source, "reason": entry["held_reason"]})
        if host:
            report["hosts_refused"].append({"source": source, "host": host, "reason": entry["held_reason"][:160]})
        print(source, "HELD")

    jobs = (("drivenc_ncdot", NC_QUERY, "ncdot_cameras.json", parse_ncdot,
             [(NC_PAGE, "drivenc_cctv.html")]),
            ("lincoln_ne_traffic", LN_QUERY, "lincoln_cameras.json", parse_lincoln, []),
            ("idaho_511_itd", ID_QUERY, "itd_cctv.json", parse_idaho,
             [(ID_ITEMINFO + "?f=json", "itd_iteminfo.json"), (ID_PAGE, "idaho511_cctv.html")]))
    for source, url, raw_name, parse, pages in jobs:
        try:
            doc, r = client.get_json(url)
            W.save_raw(out / "raw" / source, raw_name, r)
            for page_url, name in pages:  # the linked page (and terms) must answer before records point at it
                W.save_raw(out / "raw" / source, name, client.get(page_url))
            items, excluded = parse(doc, r["observed_at"])
            if not items:
                raise ValueError("no usable cameras")
        except (W.Refused, OSError, ValueError) as e:
            hold(source, held(source, pols[source]["source"]["name"], pols[source]["source"]["url"],
                              f"camera list or linked page not readable now: {str(e)[:160]}", "the list answers",
                              pols[source]["source"]["evidence"]), host=urlsplit(url).hostname)
            continue
        W.write_catalog(out / f"{source}.json", [source], items)
        write_policy(source, pols[source])
        report["sources"].append({"id": source, "status": "integrated", "countries": ["US"],
                                  "records": {"viewable": 0, "page_only": len(items)}, "excluded": excluded,
                                  "input_file": f"{source}.json", "policy_file": f"policies/{source}.json",
                                  "check": None, "notes": ["Page links only; no media requested."]})
        print(source, len(items), excluded)

    for source, entry in HELD.items():
        hold(source, entry, host=REFUSED_HOSTS.get(source))
    report["robots"] = {base: (rule if isinstance(rule, str) else "robots.txt read and honoured")
                        for base, rule in client.robots.items()}
    report["generated_at"] = W.now()
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output folder (normalized inputs, raw/, policies/, reports/)")
    run(ap.parse_args(argv).out)


if __name__ == "__main__":
    main()
