#!/usr/bin/env python3
"""Collect the central-European webcam sources of the 2026-11-14 round (stdlib only).

Family europe_central: CZ, CH, SI, DE, FR, LU, AT, PL, GR, FO, GB, UA, plus the held
entries the round assigned to this family (SE, ES, RU). The Italian sources live in
collect_italy.py, which reuses the helpers and the stage runner below.

Fetch stage (network, PoliteClient only): the camera list of each source (and the one
robots.txt or terms page a decision depends on), saved with its receipt under
OUT/raw/<source>/. A refusal (robots, 401/403/429/5xx) is recorded in
OUT/raw/<source>/refused.json and the source is held. Check stage: at most one image
or HLS sample per new or upgraded viewable provider, saved under OUT/checks/. Build
stage (offline): parse the saved lists with the pure functions below and write
OUT/<source>.json, OUT/policies/<source>.json and OUT/reports/<family>.json.

  python scripts/collect_europe_central.py --out <dir> fetch [--only a,b]
  python scripts/collect_europe_central.py --out <dir> check [--only a,b]
  python scripts/collect_europe_central.py --out <dir> build

Coordinates typed below (HAND_PLACED tables) are approximate positions of the named
place or road, set by hand where the operator publishes no coordinates; every such
record carries coordinate_role approximate/associated_feature and a coordinate_note.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import quote, urljoin, urlsplit
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as F  # noqa: E402

FAMILY = "europe_central"
REVIEWED_AT = "2026-11-14"
REGISTER = "SCRATCH/webcam-research/europe.json (register of 2026-11-14)"
CC_BY_4 = "https://creativecommons.org/licenses/by/4.0/"
HAND_NOTE = "Hand-placed at the named place (no published coordinates); approximate."

# ======================================================================================
# Shared helpers (collect_italy.py uses them too)
# ======================================================================================


def raw_dir(out, source):
    return Path(out) / "raw" / source


def save(out, source, name, response):
    return F.save_raw(raw_dir(out, source), name, response)


def record_refusal(out, source, url, error):
    folder = raw_dir(out, source)
    folder.mkdir(parents=True, exist_ok=True)
    doc = {"source": source, "url": url, "refused_at": F.now(), "reason": str(error)[:300], "user_agent": F.USER_AGENT}
    (folder / "refused.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def robots_evidence(client, out, source, base, name):
    """Read a host's robots.txt once, keep it as evidence and prime the client's cache with it."""
    r = client._open(base.rstrip("/") + "/robots.txt", 512 * 1024)
    receipt = save(out, source, name, r)
    if r["status"] >= 500:
        client.robots[base] = "deny"
    elif r["status"] >= 400:
        client.robots[base] = "allow"
    else:
        client.robots[base] = F.Robots(r["body"].decode("utf-8", "replace"))
    return receipt


def fetch_one(client, out, source, name, url, accept=None, max_bytes=20 * 1024 * 1024):
    """One list request; a refusal is recorded and None returned (the source is then held)."""
    try:
        r = client.get(url, accept=accept, max_bytes=max_bytes)
    except F.Refused as e:
        record_refusal(out, source, url, e)
        return None
    except OSError as e:
        record_refusal(out, source, url, f"network error: {e}")
        return None
    save(out, source, name, r)
    return r


def read_raw(out, source, name):
    path = raw_dir(out, source) / name
    return path.read_bytes() if path.exists() else None


def raw_receipt(out, source, name):
    path = raw_dir(out, source) / (name + ".receipt.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def refused(out, source):
    path = raw_dir(out, source) / "refused.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def raw_files(out, source, *names):
    """Provenance entries (file, url, time, hash) for a policy's source block."""
    rows = []
    for name in names:
        r = raw_receipt(out, source, name)
        if r:
            rows.append({"file": f"raw/{source}/{name}", "url": r["url"], "observed_at": r["observed_at"],
                         "status": r["status"], "sha256": r["sha256"], "bytes": r["bytes"]})
    return rows


def text(body):
    return body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body


def clean(value):
    """A short label without tags, entities or runs of whitespace."""
    value = html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def iri(url):
    """Percent-encode non-ASCII characters of a published link (IRI to URI), keeping its structure."""
    return quote(url, safe=":/?#[]@!$&'()*+,;=%-._~")


def item(provider, provider_id, name, lat, lng, country, region, *, format_, source_page, source_catalog, observed_at,
         coordinate_role, official_page=None, snapshot_url=None, stream_url=None, **extra):
    """One normalized record in the shape build_webcams.normalize_world_item reads."""
    lat, lng = round(float(lat), 6), round(float(lng), 6)
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError(f"bad coordinates for {provider}:{provider_id}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,159}", provider_id):
        raise ValueError(f"bad provider id {provider_id!r}")
    rec = {"provider": provider, "provider_id": provider_id, "id": f"{provider}:{provider_id}",
           "identity_basis": extra.pop("identity_basis", "official_record_id"), "name": name, "lat": lat, "lng": lng,
           "country": country, "region": region, "coordinate_role": coordinate_role, "format": format_,
           "stream_url": stream_url if format_ == "hls" else None,
           "snapshot_url": snapshot_url if format_ == "snapshot" else None,
           "official_page": official_page, "source_page": source_page, "source_catalog": source_catalog,
           "rights_status": "official_page_only" if format_ == "official_page" else "official_public_feed",
           "observed_at": observed_at, "health": {"status": "unverified"}}
    rec.update({k: v for k, v in extra.items() if v is not None})
    return rec


def hand_placed(provider, provider_id, name, place, country, region, *, page, source_page, source_catalog, observed_at,
                role="approximate", note=HAND_NOTE, **extra):
    """A page-only record at a hand-placed coordinate (place = (lat, lng))."""
    return item(provider, provider_id, name, place[0], place[1], country, region, format_="official_page",
                official_page=page, source_page=source_page, source_catalog=source_catalog, observed_at=observed_at,
                coordinate_role=role, coordinate_crs="EPSG:4326", coordinate_transform_applied=False,
                coordinate_note=note, **extra)


def policy(source_id, *, name, url, terms_url, license_, media_rights, attribution, evidence, formats, countries,
           media_hosts=(), page_hosts=(), catalog_url=None, license_url=None, metadata_license=None,
           minimum_refresh_seconds=None, coordinate_role=None, force_coordinate_role=None, official_map_url=None,
           rights_note=None, provider_notice=None, raw=(), extra_source=None):
    """A policy entry in the shape of scripts/webcam_source_policies.json."""
    viewable = any(f in ("snapshot", "hls") for f in formats)
    source = {"id": source_id, "name": name, "url": url, "catalog_url": catalog_url or url, "terms_url": terms_url,
              "metadata_license": metadata_license or license_, "license": license_, "license_url": license_url,
              "media_rights": media_rights, "rights_note": rights_note or media_rights, "attribution": attribution,
              "rights_status": "official_public_feed" if viewable else "official_page_only",
              "allowed_hosts": sorted(media_hosts), "official_page_hosts": sorted(page_hosts),
              "review_status": "reviewed_for_snapshot_and_reference_use" if viewable else "reviewed_for_external_references_only",
              "reviewed_at": REVIEWED_AT, "evidence": list(evidence),
              "review_note": "Approved scope is limited to the formats and origins in this registry; no upstream liveness claim is accepted."}
    if minimum_refresh_seconds:
        source["minimum_refresh_seconds"] = minimum_refresh_seconds
    if provider_notice:
        source["provider_notice"] = provider_notice
    if raw:
        source["raw_files"] = list(raw)
    source.update(extra_source or {})
    entry = {"source": source, "media_hosts": sorted(media_hosts), "page_hosts": sorted(page_hosts),
             "formats": list(formats), "countries": sorted(countries), "operator_hints": []}
    if coordinate_role:
        entry["coordinate_role"] = coordinate_role
    if force_coordinate_role:
        entry["force_coordinate_role"] = force_coordinate_role
    if official_map_url:
        entry["official_map_url"] = official_map_url
    return entry


def held(source_id, name, url, reason, until, evidence, country=None):
    entry = {"status": "held", "held_reason": reason, "held_until": until, "evidence": list(evidence),
             "source": {"id": source_id, "name": name, "url": url}, "reviewed_at": REVIEWED_AT}
    if country:
        entry["countries"] = [country]
    return entry


def hosts_of(items, field):
    return sorted({urlsplit(x[field]).hostname for x in items if x.get(field)})


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def read_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ---------- one sample per new or upgraded viewable provider ----------

def check_snapshot(client, out, result):
    """Sample the first record's image once (64 KiB, nothing kept) and save the event list."""
    first = next((x for x in result["items"] if x["format"] == "snapshot"), None)
    if first is None:
        return None
    event = client.check_image(first["snapshot_url"], first["provider"], first["id"], result["policy"]["media_hosts"])
    write_json(Path(out) / "checks" / f"{first['provider']}.snapshot.json", [event])
    return event


def check_hls(client, out, result):
    first = next((x for x in result["items"] if x["format"] == "hls"), None)
    if first is None:
        return None
    event = client.check_hls(first["stream_url"], first["provider"])
    event["record_id"] = first["id"]
    write_json(Path(out) / "checks" / f"{first['provider']}.health.json", [event])
    return event


def check_summary(out, source):
    for kind in ("snapshot", "health"):
        events = read_json(Path(out) / "checks" / f"{source}.{kind}.json")
        if events:
            e = events[0]
            if kind == "snapshot":
                return {"kind": "image", "url": e.get("url"), "status": e.get("status"), "http": e.get("http_status"),
                        "signature": e.get("signature"), "content_type": e.get("content_type"),
                        "bytes_read": e.get("bytes_read"), "checked_at": e.get("checked_at"),
                        "reason": e.get("inconclusive_reason")}
            return {"kind": "hls", "url": e.get("url"), "status": "manifest_valid" if e.get("manifest_valid") else e.get("status"),
                    "http": e.get("http_status"), "signature": "#EXTM3U" if e.get("manifest_valid") else None,
                    "content_type": e.get("content_type"), "checked_at": e.get("checked_at"), "reason": e.get("error")}
    return None


# ---------- stage runner (shared with collect_italy.py) ----------

def run(family, sources, args, check_fns=None, etiquette=()):
    """sources: {id: {"fetch": fn(client, out) | None, "build": fn(out) -> result}} in report order."""
    out = Path(args.out)
    only = set(args.only.split(",")) if args.only else None
    chosen = [s for s in sources if not only or s in only]
    if args.stage == "fetch":
        client = F.PoliteClient()
        for sid in chosen:
            fn = sources[sid].get("fetch")
            if fn:
                n0 = len(client.log)
                fn(client, out)
                log_path = raw_dir(out, sid) / "request_log.json"
                previous = read_json(log_path) or []
                write_json(log_path, previous + client.log[n0:])
        return 0
    if args.stage == "check":
        client = F.PoliteClient()
        for sid in chosen:
            if not (check_fns or {}).get(sid):
                continue
            result = sources[sid]["build"](out)
            if result["status"] != "integrated":
                print(f"{sid}: not integrated, no check")
                continue
            event = check_fns[sid](client, out, result)
            if event is None:
                print(f"{sid}: no viewable record, no check")
                continue
            print(sid, json.dumps({k: event.get(k) for k in ("status", "http_status", "signature", "manifest_valid", "error",
                                                             "inconclusive_reason")}))
        return 0
    # build
    report = {"family": family, "generated_at": F.now(), "register": REGISTER, "sources": [], "held": [],
              "hosts_refused": [], "etiquette": list(etiquette)}
    for sid in chosen:
        result = sources[sid]["build"](out)
        write_json(out / "policies" / f"{sid}.json", {sid: result["policy"]})
        row = {"id": sid, "country": result.get("country"), "status": result["status"]}
        if result["status"] == "integrated":
            items = result["items"]
            F.write_catalog(out / f"{sid}.json", sources=[sid], items=items, supersedes=result.get("supersedes", ()))
            formats = collections.Counter(x["format"] for x in items)
            row.update({"records": len(items), "viewable": formats["snapshot"] + formats["hls"],
                        "page_only": formats["official_page"], "input_file": f"{sid}.json",
                        "supersedes": result.get("supersedes") or [], "check": check_summary(out, sid),
                        "countries": dict(collections.Counter(x["country"] for x in items))})
        else:
            report["held"].append({"id": sid, "country": result.get("country"), "reason": result["policy"]["held_reason"]})
        for host in result.get("refused_hosts", ()):
            report["hosts_refused"].append({"source": sid, "host": host["host"], "reason": host["reason"]})
        row.update({k: result[k] for k in ("robots", "overlap", "changes", "notes", "etiquette") if result.get(k)})
        report["sources"].append(row)
    write_json(out / "reports" / f"{family}.json", report)
    summary = [(r["id"], r["status"], r.get("viewable"), r.get("page_only")) for r in report["sources"]]
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output folder (webcam-inputs-2026-11)")
    ap.add_argument("stage", choices=("fetch", "check", "build"))
    ap.add_argument("--only", help="comma-separated source ids")
    return ap.parse_args(argv)


# ======================================================================================
# Sources of this family: endpoints
# ======================================================================================

CHMI_LIST = "https://produkty.chmi.cz/webkamery/webcams.json"
CHMI_MAP = "https://produkty.chmi.cz/webkamery/webcamMap.php"
CHMI_DETAIL = "https://produkty.chmi.cz/webkamery/webcamDetail.php?cam={file}"
CHMI_IMAGE = "https://produkty.chmi.cz/webkamery/input_data/kam/{file}.jpg"
SITG_QUERY = ("https://vector.sitg.ge.ch/arcgis/rest/services/INFOMOB_CAMERA/FeatureServer/0/query"
              "?f=json&where=1%3D1&outFields=*&returnGeometry=true&outSR=4326")
SITG_DATASET = "https://sitg.ge.ch/donnees/infomob-camera"
GE_TRAFFIC_MAP = "https://ge.ch/terinfomobilite/"
METEOSWISS_GEOJSON = "https://data.geo.admin.ch/ch.meteoschweiz.messnetz-webcams/ch.meteoschweiz.messnetz-webcams_en.json"
METEOSWISS_LEGAL = "https://www.meteoswiss.admin.ch/about-us/legal-basis.html"
METEOSWISS_TERMS = "https://opendatadocs.meteoswiss.ch/general/terms-of-use"
ARSO_DIR = "https://meteo.arso.gov.si/uploads/probase/www/observ/webcam/"
DWD_README = "https://opendata.dwd.de/README.txt"
HAMBURG_COLLECTIONS = "https://api.hamburg.de/datasets/v1/verkehrskameras/collections?f=json"
HAMBURG_ITEMS = ("https://api.hamburg.de/datasets/v1/verkehrskameras/collections/verkehr_kameras_internet/items"
                 "?f=json&limit=100")
CITA_KML = "https://www.cita.lu/kml/cameras.kml"
CITA_DATASET = "https://data.public.lu/fr/datasets/cita-cameras-autoroute/"
FOTO_WEBCAM_META = "https://www.foto-webcam.eu/webcam/include/metadata.php"
LANDSVERK_PAGE = "https://www.landsverk.fo/fo-fo/borgari/vevmyndatol"
DIRCE_HOME = "https://www.webcams-dir.centre-est.developpement-durable.gouv.fr/"
WALES_ROADS = "https://traffic.wales/road-cameras"
TOPR_HOME = "https://pogoda.topr.pl/"
ORLEANS_DATASET = "https://www.data.gouv.fr/api/1/datasets/webcam-orleans-metropole/"
ORLEANS_EXPORT = ("https://data.orleans-metropole.fr/api/explore/v2.1/catalog/datasets/om-webcam-dispositif/"
                  "exports/geojson")
AODOS_LIVE = "https://www.aodos.gr/en/live-streaming/"
BRETTEN_PAGE = "https://www.bretten.de/stadt-rathaus-verwaltung/webcams-marktplatz-und-pfeiferturm"
BUKOVEL_SITEMAP = "https://bukovel.com/sitemap.xml"


def fetch_chmi(client, out):
    fetch_one(client, out, "chmi", "webcams.json", CHMI_LIST, accept="application/json")


def fetch_geneva_sitg(client, out):
    fetch_one(client, out, "geneva_sitg", "infomob_camera.json", SITG_QUERY, accept="application/json")


def fetch_meteoswiss_weathercams(client, out):
    if not fetch_one(client, out, "meteoswiss_weathercams", "messnetz-webcams_en.json", METEOSWISS_GEOJSON):
        return
    # The images sit on backend.roundshot.com: its robots.txt and the open-data terms decide viewable or page links.
    # The thumbnail URL answers 302 to storage2.roundshot.com (seen at the image check): both robots files count.
    for host in ROUNDSHOT_HOSTS:
        try:
            robots_evidence(client, out, "meteoswiss_weathercams", f"https://{host}", f"{host}.robots.txt")
        except (OSError, F.Refused) as e:
            record_refusal(out, "meteoswiss_weathercams", f"https://{host}/robots.txt", e)
    fetch_one(client, out, "meteoswiss_weathercams", "legal-basis.html", METEOSWISS_LEGAL)  # the layer's own licence link
    fetch_one(client, out, "meteoswiss_weathercams", "opendata-terms-of-use.html", METEOSWISS_TERMS)


def fetch_arso_webcams(client, out):
    fetch_one(client, out, "arso_webcams", "webcam_dir.html", ARSO_DIR)


def fetch_dwd_webcams(client, out):
    fetch_one(client, out, "dwd_webcams", "README.txt", DWD_README)


def fetch_hamburg_verkehrskameras(client, out):
    if fetch_one(client, out, "hamburg_verkehrskameras", "collections.json", HAMBURG_COLLECTIONS, accept="application/json"):
        fetch_one(client, out, "hamburg_verkehrskameras", "items.json", HAMBURG_ITEMS, accept="application/geo+json")


def fetch_cita_luxembourg(client, out):
    fetch_one(client, out, "cita_luxembourg", "cameras.kml", CITA_KML)


def fetch_foto_webcam_eu(client, out):
    fetch_one(client, out, "foto_webcam_eu", "metadata.json", FOTO_WEBCAM_META, accept="application/json")


def fetch_faroe_landsverk(client, out):
    fetch_one(client, out, "faroe_landsverk", "vevmyndatol.html", LANDSVERK_PAGE)


def fetch_dir_centre_est_webcams(client, out):
    fetch_one(client, out, "dir_centre_est_webcams", "index.html", DIRCE_HOME)


def fetch_traffic_wales_cctv(client, out):
    fetch_one(client, out, "traffic_wales_cctv", "road-cameras.html", WALES_ROADS)


def fetch_topr_pogoda_cams(client, out):
    fetch_one(client, out, "topr_pogoda_cams", "index.html", TOPR_HOME)


def fetch_orleans_metropole_webcams(client, out):
    """The data.gouv.fr record names only Opendatasoft /api/ exports: the client asks robots.txt first."""
    if fetch_one(client, out, "orleans_metropole_webcams", "dataset.json", ORLEANS_DATASET, accept="application/json"):
        fetch_one(client, out, "orleans_metropole_webcams", "om-webcam-dispositif.geojson", ORLEANS_EXPORT)


def fetch_attiki_odos_live(client, out):
    fetch_one(client, out, "attiki_odos_live", "live-streaming.html", AODOS_LIVE)


def fetch_bretten_webcams(client, out):
    fetch_one(client, out, "bretten_webcams", "webcams.html", BRETTEN_PAGE)


def fetch_ua_bukovel_cams(client, out):
    fetch_one(client, out, "ua_bukovel_cams", "sitemap.xml", BUKOVEL_SITEMAP)


# ======================================================================================
# Pure parsers (tests feed them the saved fixtures)
# ======================================================================================


def parse_chmi(body):
    rows = json.loads(text(body))
    out = []
    for r in rows:
        file_ = str(r.get("file") or "").strip()
        if not re.fullmatch(r"[a-z0-9_-]{1,60}", file_):
            continue
        out.append({"file": file_, "name": clean(r.get("name")), "lat": float(r["lat"]), "lng": float(r["lon"]),
                    "direction": clean(r.get("smer")) or None, "region": clean(r.get("kraj")) or None,
                    "branch": clean(r.get("pobocka")) or None,
                    "altitude_m": float(r["vyska"]) if str(r.get("vyska") or "").strip() else None})
    return out


def parse_sitg(body):
    doc = json.loads(text(body))
    if (doc.get("spatialReference") or {}).get("wkid") != 4326:
        raise ValueError("SITG answer is not in EPSG:4326")
    rows = []
    for f in doc.get("features", []):
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        rows.append({"objectid": int(a["OBJECTID"]), "name": clean(a.get("NOM")), "lat": float(g["y"]), "lng": float(g["x"]),
                     "direction_aller": a.get("DIRECTION_ALLER"), "direction_retour": a.get("DIRECTION_RETOUR"),
                     "image_aller": a.get("IMAGE_ALLER"), "image_retour": a.get("IMAGE_RETOUR")})
    return rows


def lv95_to_wgs84(east, north):
    """swisstopo approximate formulas (LV95 / EPSG:2056 to WGS84), accuracy about 1 m."""
    y, x = (east - 2600000) / 1e6, (north - 1200000) / 1e6
    lng = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lat * 100 / 36, lng * 100 / 36


def parse_meteoswiss(body):
    doc = json.loads(text(body))
    if (doc.get("crs") or {}).get("properties", {}).get("name") != "EPSG:2056":
        raise ValueError("MeteoSwiss layer is not in EPSG:2056")
    rows = []
    for f in doc.get("features", []):
        p, (east, north) = f["properties"], f["geometry"]["coordinates"][:2]
        desc = p.get("description") or ""
        img = re.search(r'<img src="(https://backend\.roundshot\.com/cams/[0-9a-f]{32}/thumbnail)"', desc)
        page = re.search(r'href="(https://www\.meteoswiss\.admin\.ch/[^"]+station=[A-Z0-9]+)"', desc)
        owner = re.search(r"Data Owner</strong></td><td>([^<]+)</td>", desc)
        lat, lng = lv95_to_wgs84(float(east), float(north))
        rows.append({"station": str(f["id"]), "name": clean(p.get("station_name")), "lat": lat, "lng": lng,
                     "east": east, "north": north, "altitude": clean(p.get("altitude")),
                     "image": img.group(1) if img else None, "page": html.unescape(page.group(1)) if page else None,
                     "owner": clean(owner.group(1)) if owner else None})
    return rows


KML = "{http://www.opengis.net/kml/2.2}"


def parse_cita_kml(body):
    root = ET.fromstring(body if isinstance(body, bytes) else body.encode("utf-8"))
    rows = []
    for pm in root.iter(KML + "Placemark"):
        name = clean(pm.findtext(KML + "name"))
        desc = pm.findtext(KML + "description") or ""
        page = re.search(r'src="(https://www\.cita\.lu/webcam/map/(\d+))"', desc)
        coords = (pm.findtext(f"{KML}Point/{KML}coordinates") or "").strip().split(",")
        if not page or len(coords) < 2:
            continue
        road = re.match(r"([AB]\d+|N\d+)\b", name)
        rows.append({"camera": page.group(2), "name": name, "page": page.group(1), "lat": float(coords[1]),
                     "lng": float(coords[0]), "road": road.group(1) if road else None})
    return rows


FOTO_WEBCAM_COUNTRIES = {"at": "AT", "de": "DE", "it": "IT", "ch": "CH", "li": "LI", "si": "SI", "cz": "CZ"}


def parse_foto_webcam(body):
    """Cameras whose own page is on www.foto-webcam.eu, listed (not hidden), online, in the Alpine countries."""
    rows, skipped = [], collections.Counter()
    for c in json.loads(text(body)).get("cams", []):
        link = c.get("link") or ""
        cam = str(c.get("id") or "")
        if not re.fullmatch(r"[a-z0-9_-]{1,80}", cam) or link != f"https://www.foto-webcam.eu/webcam/{cam}/":
            skipped["page_not_on_foto_webcam_eu"] += 1
            continue
        if c.get("hidden") or c.get("offline"):
            skipped["hidden_or_offline"] += 1
            continue
        country = FOTO_WEBCAM_COUNTRIES.get(str(c.get("country") or "").lower())
        if not country:
            skipped["country_outside_scope"] += 1
            continue
        rows.append({"camera": cam, "name": clean(c.get("name")), "title": clean(c.get("title")), "page": link,
                     "lat": float(c["latitude"]), "lng": float(c["longitude"]), "country": country,
                     "elevation_m": c.get("elevation"), "direction_deg": c.get("direction"),
                     "capture_interval_s": c.get("captureInterval")})
    return rows, dict(skipped)


def parse_landsverk(body):
    """(area, page link, image code, caption) per view, in page order."""
    t = text(body)
    marks = [(m.start(), "area", clean(m.group(1))) for m in re.finditer(r'teksturleftTrue">(.*?)</div>', t, re.S)]
    for m in re.finditer(r'<div class="col-md-4 col-xs-6 vevmyndlistcont">(.*?)</div>', t, re.S):
        block = m.group(1)
        a, im = re.search(r'href="([^"]+)"', block), re.search(r'src="([^"]+)"', block)
        caption = " ".join(x for x in (clean(p) for p in re.findall(r"<p>(.*?)</p>", block, re.S)) if x)
        if a and im:
            code = re.search(r"/tmp/([A-Za-z0-9-]+)\.jpg", im.group(1))
            marks.append((m.start(), "view", (a.group(1), code.group(1) if code else None, caption)))
    area, views = None, []
    for _, kind, value in sorted(marks):
        if kind == "area":
            area = value
        else:
            views.append({"area": area, "link": value[0], "code": value[1], "caption": value[2]})
    return views


DIRCE_RECORD = re.compile(r'\{id:\s*(\d+),\s*latitude:\s*([-0-9.]+),\s*longitude:\s*([-0-9.]+),\s*cap:\s*(\d+),\s*'
                          r'secteur:\s*(\d+),\s*description:"([^"]*)",\s*direction:"([^"]*)"\}')


def parse_dirce(body):
    t = text(body)
    block = re.search(r"var donneesCamera = (\[.*?\]);", t, re.S)
    if not block:
        raise ValueError("camera array not found")
    rows = []
    for m in DIRCE_RECORD.finditer(block.group(1)):
        desc = clean(m.group(6))
        road = re.search(r"\b([AN]\d+[A-Z]?)\b", desc)
        rows.append({"camera": m.group(1), "lat": float(m.group(2)), "lng": float(m.group(3)), "heading_deg": int(m.group(4)),
                     "sector": m.group(5), "description": desc, "direction": clean(m.group(7)),
                     "road": road.group(1) if road else None})
    if len(rows) != block.group(1).count("{id"):
        raise ValueError("unparsed camera objects")
    return rows


def parse_wales_roads(body):
    return [(m.group(1), clean(m.group(2))) for m in re.finditer(r'<a href="/cctv-cameras/([a-z0-9]+)"[^>]*>(.*?)</a>', text(body), re.S)]


def parse_topr(body):
    rows = []
    pattern = (r'download/current/([a-z0-9]+)\.jpeg[^"]*" class="pt-lightbox">.*?gel-heading-title">(.*?)</h3>'
               r'(.*?)(https://new\.pogoda\.topr\.pl/[a-z0-9-]+/)')
    for m in re.finditer(pattern, text(body), re.S):
        view = re.search(r'gel-heading-description">(.*?)</p>', m.group(3), re.S)
        rows.append({"code": m.group(1), "name": clean(m.group(2)), "view": clean(view.group(1)) if view else None,
                     "page": m.group(4)})
    return rows


def parse_aodos(body):
    rows = []
    for m in re.finditer(r'<div class="camera-wrapper">\s*<h2 class="title">(.*?)</h2>\s*<video id="(cam\d+)".*?'
                         r'<p class="description">(.*?)</p>', text(body), re.S):
        rows.append({"camera": m.group(2), "name": clean(m.group(1)), "description": clean(m.group(3))})
    return rows


def parse_bretten(body):
    t = text(body)
    images = re.findall(r'<img alt="WebCam"[^>]*src="(/sites/default/files/Webcm_(Mark|Pfeif)/[^"]+)"', t)
    title = re.search(r"<title>(.*?)</title>", t, re.S)
    return {"title": clean(title.group(1)) if title else None, "views": [kind for _, kind in images]}


def parse_sitemap_cams(body):
    return [u for u in re.findall(r"<loc>(.*?)</loc>", text(body)) if re.fullmatch(r"https://bukovel\.com/cams/[a-z0-9-]+", u)]


def parse_orleans_dataset(body):
    doc = json.loads(text(body))
    return {"license": doc.get("license"), "resources": [r.get("url") for r in doc.get("resources", [])]}


# ======================================================================================
# Hand-placed positions (approximate; the operators publish names, not coordinates)
# ======================================================================================

LANDSVERK_PLACES = {  # page link -> (name, (lat, lng))
    "/default.aspx?id=447": ("Viðareiðisvegurin (Viðoy)", (62.325, -6.527)),
    "/default.aspx?id=360": ("Klaksvík", (62.2266, -6.589)),
    "/fo-fo/borgari/vevmyndatol/norðoyggjar/fugloy": ("Fugloy (Hattarvík, Kirkja)", (62.327, -6.296)),
    "/fo-fo/borgari/vevmyndatol/norðoyggjar/svinoy": ("Svínoy", (62.277, -6.342)),
    "/default.aspx?id=356": ("Gøtueiði", (62.175, -6.775)),
    "/default.aspx?id=359": ("Kambsdalur", (62.247, -6.873)),
    "/default.aspx?id=355": ("Gjáarskarð", (62.31, -6.95)),
    "/default.aspx?id=439": ("Runavík", (62.1083, -6.7217)),
    "/fo-fo/borgari/vevmyndatol/eysturoy/oyndarfjoerður-heltnin": ("Oyndarfjørður, Heltnin", (62.27, -6.86)),
    "/default.aspx?id=443": ("Streymnes", (62.193, -7.02)),
    "/default.aspx?id=361": ("Kollafjørður", (62.105, -6.92)),
    "/default.aspx?id=358": ("Kaldbaksbotnur", (62.07, -6.87)),
    "/default.aspx?id=444": ("Sund", (62.045, -6.855)),
    "/default.aspx?id=448": ("Velbastaðháls", (61.995, -6.815)),
    "/default.aspx?id=3247": ("Høgareyn", (62.04, -6.83)),
    "/fo-fo/borgari/vevmyndatol/vagar/sandavagshalsur": ("Sandavágsháls", (62.065, -7.165)),
    "/fo-fo/borgari/vevmyndatol/vagar/vatnsoyrar": ("Vatnsoyrar", (62.0717, -7.2445)),
    "/fo-fo/borgari/vevmyndatol/vagar/mykines-lending": ("Mykines, lending", (62.1015, -7.646)),
    "/fo-fo/borgari/vevmyndatol/vagar/mykines": ("Mykines, lending 2", (62.1022, -7.645)),
    "/fo-fo/borgari/vevmyndatol/vagar/mykines-tyrlupallur": ("Mykines, tyrlupallur", (62.103, -7.648)),
    "/default.aspx?id=357": ("Hvalba", (61.601, -6.955)),
    "/default.aspx?id=438": ("Porkerisháls", (61.485, -6.765)),
    "/default.aspx?id=340": ("Gamlarætt", (61.9908, -6.8566)),
    "/default.aspx?id=441": ("Skopun", (61.903, -6.882)),
    "/default.aspx?id=362": ("Krambatangi", (61.565, -6.793)),
    "/fo-fo/borgari/vevmyndatol/havnir/krambatangi": ("Krambatangi, atløga", (61.565, -6.793)),
    "/default.aspx?id=445": ("Syðradalur (Kalsoy)", (62.245, -6.66)),
}

WALES_ROADS_PLACES = {  # road page -> representative point on that road in Wales
    "a44": (52.4135, -3.846), "m4": (51.5975, -3.001), "m48": (51.6097, -2.642), "a48m": (51.532, -3.101),
    "a40": (51.824, -3.017), "a4042": (51.70, -3.03), "a4232": (51.47, -3.205), "a449": (51.70, -2.90),
    "a465": (51.78, -3.32), "a468": (51.592, -3.20), "a470": (51.60, -3.33), "a477": (51.73, -4.70),
    "a48": (51.80, -4.13), "a487": (52.594, -3.854), "a494": (53.20, -3.05), "a55": (53.293, -3.727),
    "a550": (53.215, -3.01),
}

TOPR_PLACES = {
    "mors": (49.2016, 20.0713), "momn": (49.2016, 20.0713), "psps": (49.2132, 20.049), "psdb": (49.2132, 20.049),
    "hala": (49.2433, 20.0072), "hgkw": (49.2433, 20.0072), "kwgs": (49.2319, 19.9817), "kwgr": (49.2319, 19.9817),
    "dcho": (49.2357, 19.7894), "dch2": (49.2357, 19.7894), "kscw": (49.29, 19.887), "czgr": (49.398, 20.11),
}

AODOS_PLACES = {
    "cam128": (38.0225, 23.842), "cam231": (37.993, 23.797), "cam38": (38.0446, 23.7925),
    "cam053": (38.063, 23.755), "cam6": (37.915, 23.87), "cam88": (38.05, 23.57),
}

BRETTEN_PLACES = {"Mark": ("Webcam Marktplatz", "marktplatz", (49.0365, 8.7066)),
                  "Pfeif": ("Webcam Pfeiferturm", "pfeiferturm", (49.0375, 8.7046))}

BUKOVEL_PLACES = {"vitiag-5": ("Bukovel — lift 5 camera", (48.352, 24.402)),
                  "voda-club": ("Bukovel — Voda club camera", (48.362, 24.414))}


# ======================================================================================
# Builders: one per source, each returns {"status", "policy", "items"?, ...}
# ======================================================================================

def held_result(source_id, country, name, url, reason, until, evidence, refused_hosts=(), **extra):
    return {"status": "held", "country": country, "policy": held(source_id, name, url, reason, until, evidence, country),
            "refused_hosts": list(refused_hosts), **extra}


def build_chmi(out):
    body = read_raw(out, "chmi", "webcams.json")
    if body is None:
        return held_result("chmi", "CZ", "ČHMÚ webcam network", CHMI_MAP, "camera list not fetched", "a fresh list", [CHMI_LIST])
    when = raw_receipt(out, "chmi", "webcams.json")["observed_at"]
    rows = parse_chmi(body)
    items = []
    for r in rows:
        # Every row carries a ČHMÚ branch code (pobocka): the images are ČHMÚ products. A row without one stays a page link.
        viewable = bool(r["branch"])
        items.append(item("chmi", r["file"], r["name"], r["lat"], r["lng"], "CZ", r["region"] or "",
                          format_="snapshot" if viewable else "official_page",
                          snapshot_url=CHMI_IMAGE.format(file=r["file"]), official_page=CHMI_DETAIL.format(file=r["file"]),
                          source_page=CHMI_MAP, source_catalog=CHMI_LIST, observed_at=when,
                          coordinate_role="station_location", coordinate_crs="unspecified_geographic",
                          coordinate_note="Station latitude/longitude published by ČHMÚ (datum not stated).",
                          direction=r["direction"], altitude_m=r["altitude_m"], provider_branch=r["branch"]))
    pol = policy(
        "chmi", name="Český hydrometeorologický ústav — webcam network", url=CHMI_MAP, catalog_url=CHMI_LIST,
        terms_url="https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti",
        license_="CC-BY-4.0 (ČHMÚ products on its websites)", license_url=CC_BY_4,
        media_rights=("ČHMÚ applies CC BY 4.0 to the products on its websites and the webcam map carries the CC BY 4.0 "
                      "badge; every camera in webcams.json carries a ČHMÚ branch code (pobocka), no third-party operator. "
                      "The licence is site-wide, not webcam-specific: one confirmation e-mail to ČHMÚ is recommended before launch."),
        attribution="Zdroj: ČHMÚ (Český hydrometeorologický ústav), CC BY 4.0",
        evidence=["https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti",
                  "https://www.chmi.cz/-/jak-mohu-pou%C5%BE%C3%ADvat-otev%C5%99en%C3%A1-data-%C4%8Dhm%C3%BA-", CHMI_MAP],
        formats=["snapshot", "official_page"], countries=["CZ"], media_hosts=["produkty.chmi.cz"],
        page_hosts=["produkty.chmi.cz"], minimum_refresh_seconds=300, coordinate_role="station_location",
        raw=raw_files(out, "chmi", "webcams.json"))
    return {"status": "integrated", "country": "CZ", "items": items, "policy": pol, "supersedes": ["chmi"],
            "robots": "produkty.chmi.cz: no robots.txt (404), list allowed",
            "changes": ["upgrade page_only -> snapshot (CC BY 4.0, register rank 6)", "coordinate_role approximate -> station_location",
                        "provider_ids kept (webcams.json 'file')"],
            "overlap": "upgrades the 99 existing chmi records in place; 1 OSM record also links produkty.chmi.cz"}


def build_geneva_sitg(out):
    body = read_raw(out, "geneva_sitg", "infomob_camera.json")
    if body is None:
        return held_result("geneva_sitg", "CH", "SITG Genève", SITG_DATASET, "camera list not fetched", "a fresh list", [SITG_QUERY])
    when = raw_receipt(out, "geneva_sitg", "infomob_camera.json")["observed_at"]
    items = []
    for r in parse_sitg(body):
        extra = {}
        if r["image_retour"] and r["image_retour"] != r["image_aller"]:
            extra["reference_snapshot_url"] = r["image_retour"]
        items.append(item("geneva_sitg", str(r["objectid"]), r["name"], r["lat"], r["lng"], "CH", "Genève",
                          format_="snapshot", snapshot_url=r["image_aller"], official_page=GE_TRAFFIC_MAP,
                          source_page=SITG_DATASET, source_catalog=SITG_QUERY, observed_at=when,
                          coordinate_role="camera_location", coordinate_crs="EPSG:4326",
                          coordinate_note="ArcGIS query response declares wkid 4326 (server transformation).",
                          original_coordinate_crs="EPSG:2056", coordinate_transformation="Official ArcGIS query outSR=4326",
                          direction=" / ".join(x for x in (r["direction_aller"], r["direction_retour"]) if x) or None, **extra))
    day = when[:10]
    pol = policy(
        "geneva_sitg", name="SITG Genève — caméras de surveillance du trafic (INFOMOB_CAMERA)", url=SITG_DATASET,
        catalog_url=SITG_QUERY, terms_url="https://sitg.ge.ch/ressources/conditions-utilisation-donnees",
        license_="SITG niveau A — open data, commercial reuse with source/extraction-date/transformation attribution",
        media_rights=("The images are attributes of the level-A dataset itself (IMAGE_ALLER/IMAGE_RETOUR); level A allows "
                      "copying, publishing and commercial use with source and extraction-date attribution. The dataset warns "
                      "that the images are not updated in real time."),
        attribution=f"Données SITG (INFOMOB_CAMERA), extraction {day}; server transformation EPSG:2056 → EPSG:4326. Images: État de Genève.",
        provider_notice="SITG: les images de ce jeu de données ne sont pas mises à jour en temps réel (images are not real time).",
        evidence=[SITG_DATASET, "https://sitg.ge.ch/ressources/conditions-utilisation-donnees"],
        formats=["snapshot", "official_page"], countries=["CH"], media_hosts=["app2.ge.ch"], page_hosts=["ge.ch"],
        minimum_refresh_seconds=600, coordinate_role="camera_location", official_map_url=GE_TRAFFIC_MAP,
        raw=raw_files(out, "geneva_sitg", "infomob_camera.json"))
    return {"status": "integrated", "country": "CH", "items": items, "policy": pol, "supersedes": ["geneva_sitg"],
            "robots": "vector.sitg.ge.ch: no robots.txt (404); app2.ge.ch read at check time",
            "changes": ["upgrade page_only -> snapshot (SITG level A)", "provider_notice 'not real time' + minimum refresh 600 s",
                        "provider_ids kept (OBJECTID)"],
            "overlap": "upgrades the 9 existing geneva_sitg records in place"}


ROUNDSHOT_HOSTS = ("backend.roundshot.com", "storage2.roundshot.com")
ROUNDSHOT_SAMPLES = {"backend.roundshot.com": "https://backend.roundshot.com/cams/00000000000000000000000000000000/thumbnail",
                     "storage2.roundshot.com": "https://storage2.roundshot.com/x/2026-11-14/07-40-00/2026-11-14-07-40-00_thumbnail.jpg"}


def robots_allow(body, url):
    """RFC 9309 reading (webcam_fetch.Robots: our product token, else '*'; wildcards; longest match)."""
    return F.Robots(text(body)).allows(url)


def meteoswiss_viewable(out):
    """Viewable only when the robots.txt of every image host (the thumbnail URL and its redirect target) allows the
    image path and the open-data terms read CC BY 4.0."""
    terms = read_raw(out, "meteoswiss_weathercams", "opendata-terms-of-use.html")
    for host in ROUNDSHOT_HOSTS:
        robots = read_raw(out, "meteoswiss_weathercams", f"{host}.robots.txt")
        if robots is None:
            return False, f"robots.txt of {host} not read"
        if not robots_allow(robots, ROUNDSHOT_SAMPLES[host]):
            return False, (f"the thumbnail URL redirects (302) to {host}, whose robots.txt disallows all agents "
                           "('User-agent: * / Disallow: /')")
    if terms is None or "Creative Commons Licence CC BY 4.0" not in clean(text(terms)):
        return False, "open-data terms not read or no longer CC BY 4.0"
    return True, "image hosts allow the path in robots.txt; open-data terms: CC BY 4.0"


def build_meteoswiss_weathercams(out):
    body = read_raw(out, "meteoswiss_weathercams", "messnetz-webcams_en.json")
    if body is None:
        return held_result("meteoswiss_weathercams", "CH", "MeteoSwiss weather cameras", METEOSWISS_GEOJSON,
                           "camera list not fetched", "a fresh list", [METEOSWISS_GEOJSON])
    when = raw_receipt(out, "meteoswiss_weathercams", "messnetz-webcams_en.json")["observed_at"]
    viewable, why = meteoswiss_viewable(out)
    items = []
    for r in parse_meteoswiss(body):
        if r["owner"] != "MeteoSwiss" or not r["page"]:
            continue
        snap = viewable and bool(r["image"])
        items.append(item("meteoswiss_weathercams", r["station"], f"{r['name']} — MeteoSwiss weather camera", r["lat"], r["lng"],
                          "CH", "Switzerland", format_="snapshot" if snap else "official_page",
                          snapshot_url=r["image"], official_page=r["page"], source_page="https://opendata.swiss/en/dataset/wetterkameras",
                          source_catalog=METEOSWISS_GEOJSON, observed_at=when, coordinate_role="camera_location",
                          coordinate_crs="EPSG:4326", coordinate_transform_applied=True, original_coordinate_crs="EPSG:2056",
                          coordinate_transformation="swisstopo approximate formulas LV95 → WGS84 (about 1 m)",
                          original_coordinates={"E": r["east"], "N": r["north"]}, altitude=r["altitude"]))
    formats = ["snapshot", "official_page"] if viewable else ["official_page"]
    pol = policy(
        "meteoswiss_weathercams", name="MeteoSwiss weather cameras (Wetterkameras)",
        url="https://www.meteoswiss.admin.ch/services-and-publications/applications/measurement-values-and-measuring-networks.html#param=messnetz-webcams",
        catalog_url=METEOSWISS_GEOJSON, terms_url=METEOSWISS_TERMS, license_="CC-BY-4.0 (MeteoSwiss Open Data, art. 10 EMOTA)",
        license_url=CC_BY_4,
        media_rights=("MeteoSwiss publishes the data it procures or generates for its legal tasks as Open Data under CC BY 4.0 "
                      "(commercial use allowed, source 'MeteoSwiss'). The weather-camera layer on the federal FSDI names "
                      "MeteoSwiss as data owner of each camera and embeds its image link, served from backend.roundshot.com "
                      "(camera vendor host). Tier B: the terms cover MeteoSwiss data generally; the layer's own licence link "
                      "(legal-basis page) answered 404 on 2026-11-14. Confirm with MeteoSwiss before launch."
                      if viewable else
                      "MeteoSwiss Open Data are CC BY 4.0, but whether that covers the vendor-hosted camera images is not "
                      "established; station links only."),
        attribution="Source: MeteoSwiss (CC BY 4.0). Metadata normalized by QGlobe; coordinates converted from LV95.",
        evidence=[METEOSWISS_TERMS, METEOSWISS_GEOJSON, "https://opendata.swiss/en/dataset/wetterkameras"],
        formats=formats, countries=["CH"], media_hosts=["backend.roundshot.com"] if viewable else [],
        page_hosts=["www.meteoswiss.admin.ch"], minimum_refresh_seconds=600, coordinate_role="camera_location",
        raw=raw_files(out, "meteoswiss_weathercams", "messnetz-webcams_en.json", "backend.roundshot.com.robots.txt",
                      "storage2.roundshot.com.robots.txt", "opendata-terms-of-use.html", "legal-basis.html"))
    return {"status": "integrated", "country": "CH", "items": items, "policy": pol,
            "robots": f"data.geo.admin.ch: no robots.txt, list allowed; backend.roundshot.com allows all; {why}",
            "changes": ["integrated as viewable" if viewable else f"page links only instead of viewable: {why}",
                        "LV95 → WGS84 by the swisstopo approximate formulas", "the layer's licence link (legal-basis.html) is 404"],
            "etiquette": ("the single image sample followed the 302 from backend.roundshot.com to storage2.roundshot.com before "
                          "that host's robots.txt (Disallow: /) was read; 18,552 bytes sampled, nothing kept; the event is kept "
                          "as raw/meteoswiss_weathercams/image_check_event.json, not as a snapshot check")
            if (raw_dir(out, "meteoswiss_weathercams") / "image_check_event.json").exists() else None,
            "overlap": "109 OSM + 2 Wikidata records link meteoschweiz.roundshot.com viewers (same cameras, community links)"}


def build_arso_webcams(out):
    r = refused(out, "arso_webcams")
    return held_result(
        "arso_webcams", "SI", "ARSO meteorological station webcams (meteo.si)", "https://meteo.arso.gov.si/met/sl/",
        f"camera list could not be assembled: the webcam directory answered {r['reason'] if r else 'nothing'}; only 6 cameras "
        "are linked from the home page and no machine-readable index exists",
        "an official camera index (or ARSO's confirmation by e-mail to gp.arso@gov.si) with station coordinates",
        [ARSO_DIR, "https://meteo.arso.gov.si/uploads/meteo/help/en/notice.html"],
        refused_hosts=[{"host": "meteo.arso.gov.si", "reason": r["reason"]}] if r else [],
        robots="meteo.arso.gov.si: no robots.txt (404); directory /observ/webcam/ HTTP 403")


def build_dwd_webcams(out):
    readme = read_raw(out, "dwd_webcams", "README.txt")
    pointer = "the server README defers to the legal notice on www.dwd.de" if readme and b"legal_notice" in readme else "README not read"
    return held_result(
        "dwd_webcams", "DE", "Deutscher Wetterdienst webcams (opendata.dwd.de/weather/webcam)", "https://opendata.dwd.de/weather/webcam/",
        f"licence of the webcam directory not confirmed: CC BY 4.0 is documented only for the CDC area; {pointer}, "
        "whose robots.txt disallows all generic agents, so the clause cannot be read; no station coordinates in the directory",
        "the DWD terms for /weather/webcam read (CC BY 4.0 or GeoNutzV) and a station-coordinate join",
        [DWD_README, "https://opendata.dwd.de/climate_environment/CDC/Nutzungsbedingungen_German.pdf",
         "https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html"],
        robots="opendata.dwd.de: no robots.txt (404); www.dwd.de: Disallow / for generic agents (not fetched)")


def build_hamburg_verkehrskameras(out):
    body = read_raw(out, "hamburg_verkehrskameras", "items.json")
    fields = set()
    if body:
        for f in json.loads(text(body)).get("features", []):
            fields |= set((f.get("properties") or {}).keys())
    return held_result(
        "hamburg_verkehrskameras", "DE", "Verkehrskameras Hamburg", "https://api.hamburg.de/datasets/v1/verkehrskameras",
        f"no image or stream URL in the official API (OGC API Features, 18 items, properties {sorted(fields)}); "
        "the camera page shows a consent-gated embed only",
        "the official image/stream host published in the API or dataset (DL-DE-BY-2.0 already covers the images)",
        [HAMBURG_ITEMS, "https://metaver.de/trefferanzeige?cmd=doShowDocument&docuuid=6E28E698-F4FA-4231-A8C5-CC44441FF2A7"],
        robots="api.hamburg.de: only 'spatineo' disallowed; collections and items read")


def build_cita_luxembourg(out):
    body = read_raw(out, "cita_luxembourg", "cameras.kml")
    if body is None:
        return held_result("cita_luxembourg", "LU", "CITA cameras", CITA_DATASET, "list not fetched", "a fresh list", [CITA_KML])
    when = raw_receipt(out, "cita_luxembourg", "cameras.kml")["observed_at"]
    items = [item("cita_luxembourg", r["camera"], r["name"], r["lat"], r["lng"], "LU", "Luxembourg",
                  format_="official_page", official_page=r["page"], source_page=CITA_DATASET, source_catalog=CITA_KML,
                  observed_at=when, coordinate_role="camera_location", coordinate_crs="EPSG:4326", road=r["road"])
             for r in parse_cita_kml(body)]
    pol = policy(
        "cita_luxembourg", name="CITA — caméras autoroute (Administration des Ponts et Chaussées)", url=CITA_DATASET,
        catalog_url=CITA_KML, terms_url=CITA_DATASET, license_="CC0-1.0 (dataset 'Cita : Caméras autoroute')",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        media_rights="CC0 covers the camera-location KML; the images on cita.lu are not separately licensed. Page links only.",
        attribution="Administration des Ponts et Chaussées / CITA, data.public.lu (CC0). Camera pages on www.cita.lu.",
        evidence=[CITA_DATASET], formats=["official_page"], countries=["LU"], page_hosts=["www.cita.lu"],
        coordinate_role="camera_location", raw=raw_files(out, "cita_luxembourg", "cameras.kml"))
    return {"status": "integrated", "country": "LU", "items": items, "policy": pol,
            "robots": "www.cita.lu: 'User-agent: *' without Disallow",
            "overlap": "2 Wikidata records link cita.lu motorway pages (a1.html); no per-camera duplicates",
            "notes": "upgrade path: ask the Administration des Ponts et Chaussées whether CC0 extends to the images"}


def build_foto_webcam_eu(out):
    body = read_raw(out, "foto_webcam_eu", "metadata.json")
    if body is None:
        return held_result("foto_webcam_eu", "AT", "foto-webcam.eu", "https://www.foto-webcam.eu/", "list not fetched",
                           "a fresh list", [FOTO_WEBCAM_META])
    when = raw_receipt(out, "foto_webcam_eu", "metadata.json")["observed_at"]
    rows, skipped = parse_foto_webcam(body)
    regions = {"AT": "Austria", "DE": "Germany", "IT": "Italy", "CH": "Switzerland", "LI": "Liechtenstein", "SI": "Slovenia",
               "CZ": "Czechia"}
    items = [item("foto_webcam_eu", r["camera"], r["title"] or r["name"], r["lat"], r["lng"], r["country"], regions[r["country"]],
                  format_="official_page", official_page=r["page"], source_page="https://www.foto-webcam.eu/",
                  source_catalog=FOTO_WEBCAM_META, observed_at=when, coordinate_role="camera_location",
                  coordinate_crs="EPSG:4326", elevation_m=r["elevation_m"], view_direction_deg=r["direction_deg"])
             for r in rows]
    pol = policy(
        "foto_webcam_eu", name="foto-webcam.eu — high-resolution mountain webcams", url="https://www.foto-webcam.eu/",
        catalog_url=FOTO_WEBCAM_META, terms_url="https://www.foto-webcam.eu/impressum/",
        license_="All rights reserved (operator copyright); links to the site and its subpages explicitly permitted",
        media_rights=("Images may not be distributed, modified or copied without prior written consent; 'Links auf diese "
                      "Website und deren Unterseiten sind generell gestattet und auch erwünscht.' Page links only."),
        attribution="foto-webcam.eu; images © the respective camera operators (link to the camera page)",
        evidence=["https://www.foto-webcam.eu/impressum/"], formats=["official_page"],
        countries=sorted({r["country"] for r in rows}), page_hosts=["www.foto-webcam.eu"], coordinate_role="camera_location",
        raw=raw_files(out, "foto_webcam_eu", "metadata.json"))
    return {"status": "integrated", "country": "AT", "items": items, "policy": pol,
            "robots": "www.foto-webcam.eu: disallows /wiki/ (all agents) and /webcam/ for Googlebot-Image only; metadata allowed",
            "changes": [f"skipped: {skipped} (partner cameras on other hosts, hidden/offline, outside the Alpine countries)"],
            "overlap": "283 OSM + 10 Wikidata + 1 opendatahub records link foto-webcam.eu pages (community links kept separately)",
            "notes": "register recommends a courtesy e-mail to the operators before listing the full directory (EU database right)"}


def build_faroe_landsverk(out):
    body = read_raw(out, "faroe_landsverk", "vevmyndatol.html")
    if body is None:
        return held_result("faroe_landsverk", "FO", "Landsverk", LANDSVERK_PAGE, "list not fetched", "a fresh list", [LANDSVERK_PAGE])
    when = raw_receipt(out, "faroe_landsverk", "vevmyndatol.html")["observed_at"]
    pages = collections.OrderedDict()
    for v in parse_landsverk(body):
        pages.setdefault(v["link"], []).append(v)
    items, unplaced = [], []
    for link, views in pages.items():
        if link not in LANDSVERK_PLACES:
            unplaced.append(link)
            continue
        name, place = LANDSVERK_PLACES[link]
        pid = ("page-" + link.split("id=")[1]) if "id=" in link else slug(link.rsplit("/", 2)[-2] + "-" + link.rsplit("/", 1)[-1])
        captions = list(dict.fromkeys(v["caption"] for v in views if v["caption"]))
        items.append(hand_placed("faroe_landsverk", pid, f"{name} — Landsverk webcam", place, "FO", views[0]["area"] or "Føroyar",
                                 page=iri(urljoin(LANDSVERK_PAGE, link)), source_page=LANDSVERK_PAGE,
                                 source_catalog=LANDSVERK_PAGE, observed_at=when, views=captions, view_count=len(views)))
    pol = policy(
        "faroe_landsverk", name="Landsverk — Vevmyndatól (Faroese road webcams)", url=LANDSVERK_PAGE, terms_url="https://www.landsverk.fo/fo-fo/soela/vedurdatur",
        license_="None; Landsverk data is sold ('ein ávís upphædd skal gjaldast fyri allar dátur frá Landsverki')",
        media_rights="No reuse licence for the images; links to the official location pages only.",
        attribution="Landsverk (www.landsverk.fo)", evidence=["https://www.landsverk.fo/fo-fo/soela/vedurdatur", LANDSVERK_PAGE],
        formats=["official_page"], countries=["FO"], page_hosts=["www.landsverk.fo"], coordinate_role="approximate",
        raw=raw_files(out, "faroe_landsverk", "vevmyndatol.html"))
    return {"status": "integrated", "country": "FO", "items": items, "policy": pol,
            "robots": "www.landsverk.fo: only file/cart paths disallowed",
            "changes": ["one record per official location page (views grouped), positions hand-placed (approximate)"]
            + ([f"pages without a hand-placed position skipped: {unplaced}"] if unplaced else []),
            "overlap": "no FO records in the catalogue"}


def slug(value):
    value = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value.strip()).strip("-.:_")
    return value[:120] or "x"


def build_dir_centre_est_webcams(out):
    body = read_raw(out, "dir_centre_est_webcams", "index.html")
    if body is None:
        return held_result("dir_centre_est_webcams", "FR", "DIR Centre-Est webcams", DIRCE_HOME, "list not fetched", "a fresh list", [DIRCE_HOME])
    when = raw_receipt(out, "dir_centre_est_webcams", "index.html")["observed_at"]
    items = [item("dir_centre_est_webcams", r["camera"], f"{r['description']} ({r['direction']})", r["lat"], r["lng"], "FR",
                  "Auvergne-Rhône-Alpes / Bourgogne-Franche-Comté", format_="official_page", official_page=DIRCE_HOME,
                  source_page=DIRCE_HOME, source_catalog=DIRCE_HOME, observed_at=when, coordinate_role="camera_location",
                  coordinate_crs="EPSG:4326", road=r["road"], direction=r["direction"], heading_deg=r["heading_deg"])
             for r in parse_dirce(body)]
    pol = policy(
        "dir_centre_est_webcams", name="DIR Centre-Est — webcams du réseau routier national", url=DIRCE_HOME,
        terms_url=DIRCE_HOME + " (Mentions légales)", license_="No open licence (ministry site, all rights reserved)",
        media_rights=("Media reuse is non-commercial only and third-party video needs an FTP agreement; 'Tout site public ou "
                      "privé est autorisé à établir, sans autorisation préalable, un lien' (no framing). Page links only."),
        attribution="DIR Centre-Est — webcams du réseau routier national (lien vers la page officielle)",
        evidence=[DIRCE_HOME], formats=["official_page"], countries=["FR"],
        page_hosts=["www.webcams-dir.centre-est.developpement-durable.gouv.fr"], coordinate_role="camera_location",
        official_map_url=DIRCE_HOME, raw=raw_files(out, "dir_centre_est_webcams", "index.html"))
    return {"status": "integrated", "country": "FR", "items": items, "policy": pol,
            "robots": "no robots.txt (404)", "overlap": "2 OSM records link a DIR CE .mp4 clip as page (repaired by the build)"}


def build_traffic_wales_cctv(out):
    body = read_raw(out, "traffic_wales_cctv", "road-cameras.html")
    if body is None:
        return held_result("traffic_wales_cctv", "GB", "Traffic Wales", WALES_ROADS, "list not fetched", "a fresh list", [WALES_ROADS])
    when = raw_receipt(out, "traffic_wales_cctv", "road-cameras.html")["observed_at"]
    items, unplaced = [], []
    for road, label in parse_wales_roads(body):
        if road not in WALES_ROADS_PLACES:
            unplaced.append(road)
            continue
        items.append(hand_placed("traffic_wales_cctv", road, f"{label} traffic cameras — Traffic Wales", WALES_ROADS_PLACES[road],
                                 "GB", "Wales", page=f"https://traffic.wales/cctv-cameras/{road}", source_page=WALES_ROADS,
                                 source_catalog=WALES_ROADS, observed_at=when, role="associated_feature", road=label,
                                 note="Representative point on this road in Wales (hand-placed); the page lists every camera on the road."))
    pol = policy(
        "traffic_wales_cctv", name="Traffic Wales / Traffig Cymru — road camera pages", url=WALES_ROADS,
        terms_url="https://traffic.wales/developers",
        license_="OGL v3 for website information; CCTV images and camera locations restricted-access (additional terms)",
        media_rights=("Still images and camera locations are on a restricted-access server under additional terms; 'The Welsh "
                      "Government is content for users to establish hyperlinks to this site' (no framing). Road page links only."),
        attribution="Traffic Wales (Welsh Government)", evidence=["https://traffic.wales/developers"],
        formats=["official_page"], countries=["GB"], page_hosts=["traffic.wales"], coordinate_role="associated_feature",
        raw=raw_files(out, "traffic_wales_cctv", "road-cameras.html"))
    return {"status": "integrated", "country": "GB", "items": items, "policy": pol,
            "robots": "traffic.wales: Drupal default (core/admin paths only)",
            "changes": ["one record per road page (17 /cctv-cameras/ pages; the A483 link is a taxonomy page, skipped)",
                        "road positions hand-placed (associated_feature)"] + ([f"unplaced: {unplaced}"] if unplaced else []),
            "overlap": "23 OSM records link members.traffic.wales camera images"}


def build_topr_pogoda_cams(out):
    body = read_raw(out, "topr_pogoda_cams", "index.html")
    if body is None:
        return held_result("topr_pogoda_cams", "PL", "TOPR", TOPR_HOME, "list not fetched", "a fresh list", [TOPR_HOME])
    when = raw_receipt(out, "topr_pogoda_cams", "index.html")["observed_at"]
    items = [hand_placed("topr_pogoda_cams", r["code"], f"{r['name']} — TOPR" + (f" ({r['view']})" if r["view"] else ""),
                         TOPR_PLACES[r["code"]], "PL", "Tatry (Małopolskie)", page=r["page"], source_page=TOPR_HOME,
                         source_catalog=TOPR_HOME, observed_at=when)
             for r in parse_topr(body) if r["code"] in TOPR_PLACES]
    pol = policy(
        "topr_pogoda_cams", name="TOPR — Tatra mountain webcams (pogoda.topr.pl)", url=TOPR_HOME, terms_url=TOPR_HOME,
        license_="All rights reserved (© TOPR)", media_rights="'Copyright © TOPR. All rights reserved.' Page links only.",
        attribution="TOPR — Tatrzańskie Ochotnicze Pogotowie Ratunkowe (pogoda.topr.pl)", evidence=[TOPR_HOME],
        formats=["official_page"], countries=["PL"], page_hosts=["new.pogoda.topr.pl"], coordinate_role="approximate",
        official_map_url=TOPR_HOME, raw=raw_files(out, "topr_pogoda_cams", "index.html"))
    return {"status": "integrated", "country": "PL", "items": items, "policy": pol,
            "robots": "pogoda.topr.pl: no Anthropic or path rules affecting the page",
            "changes": ["official pages are the per-camera pages on new.pogoda.topr.pl linked from the list"]}


def build_attiki_odos_live(out):
    body = read_raw(out, "attiki_odos_live", "live-streaming.html")
    if body is None:
        return held_result("attiki_odos_live", "GR", "Attiki Odos", AODOS_LIVE, "list not fetched", "a fresh list", [AODOS_LIVE])
    when = raw_receipt(out, "attiki_odos_live", "live-streaming.html")["observed_at"]
    items = [hand_placed("attiki_odos_live", r["camera"], f"{r['name']} — Attiki Odos live camera", AODOS_PLACES[r["camera"]],
                         "GR", "Attica", page=AODOS_LIVE, source_page=AODOS_LIVE, source_catalog=AODOS_LIVE, observed_at=when,
                         road="Attiki Odos", view_note=r["description"])
             for r in parse_aodos(body) if r["camera"] in AODOS_PLACES]
    pol = policy(
        "attiki_odos_live", name="Attiki Odos — live traffic cameras", url=AODOS_LIVE, terms_url="https://www.aodos.gr/oroi_xrisis/",
        license_="All rights reserved", media_rights="Reproduction, republication and transmission are prohibited; link only.",
        attribution="Αττική Οδός / Attiki Odos", evidence=["https://www.aodos.gr/oroi_xrisis/"], formats=["official_page"],
        countries=["GR"], page_hosts=["www.aodos.gr"], coordinate_role="approximate", official_map_url=AODOS_LIVE,
        raw=raw_files(out, "attiki_odos_live", "live-streaming.html"))
    return {"status": "integrated", "country": "GR", "items": items, "policy": pol,
            "robots": "www.aodos.gr: Yoast default (wp-admin, ?ver=)", "changes": ["interchange positions hand-placed"]}


def build_bretten_webcams(out):
    body = read_raw(out, "bretten_webcams", "webcams.html")
    if body is None:
        return held_result("bretten_webcams", "DE", "Stadt Bretten", BRETTEN_PAGE, "page not fetched", "a fresh page", [BRETTEN_PAGE])
    when = raw_receipt(out, "bretten_webcams", "webcams.html")["observed_at"]
    page = parse_bretten(body)
    items = []
    for kind in dict.fromkeys(page["views"]):
        name, pid, place = BRETTEN_PLACES[kind]
        items.append(hand_placed("bretten_webcams", pid, f"{name} — Stadt Bretten", place, "DE", "Baden-Württemberg",
                                 page=BRETTEN_PAGE, source_page=BRETTEN_PAGE, source_catalog=BRETTEN_PAGE, observed_at=when,
                                 role="associated_feature", note="Hand-placed at the square/tower named by the city page."))
    pol = policy(
        "bretten_webcams", name="Stadt Bretten — Webcams Marktplatz und Pfeiferturm", url=BRETTEN_PAGE,
        terms_url="https://www.govdata.de/ (dataset 'webcams-bretten', Open Data Baden-Württemberg)",
        license_="CC-BY-4.0 on the metadata record (resource = link to the city page)", license_url=CC_BY_4,
        media_rights="The open licence covers the link record, not the images; page links only.",
        attribution="Stadt Bretten (CC BY 4.0 metadata)", evidence=["https://www.govdata.de/"], formats=["official_page"],
        countries=["DE"], page_hosts=["www.bretten.de"], coordinate_role="associated_feature",
        raw=raw_files(out, "bretten_webcams", "webcams.html"))
    return {"status": "integrated", "country": "DE", "items": items, "policy": pol,
            "robots": "www.bretten.de: page path allowed",
            "overlap": "2 OSM records already link this exact page (Marktplatz)"}


def build_ua_bukovel_cams(out):
    body = read_raw(out, "ua_bukovel_cams", "sitemap.xml")
    if body is None:
        return held_result("ua_bukovel_cams", "UA", "Bukovel", "https://bukovel.com/cams", "sitemap not fetched", "a fresh list", [BUKOVEL_SITEMAP])
    when = raw_receipt(out, "ua_bukovel_cams", "sitemap.xml")["observed_at"]
    items = []
    for url in parse_sitemap_cams(body):
        key = url.rsplit("/", 1)[1]
        if key in BUKOVEL_PLACES:
            name, place = BUKOVEL_PLACES[key]
            items.append(hand_placed("ua_bukovel_cams", key, name, place, "UA", "Ivano-Frankivsk oblast", page=url,
                                     source_page="https://bukovel.com/cams", source_catalog=BUKOVEL_SITEMAP, observed_at=when))
    pol = policy(
        "ua_bukovel_cams", name="Bukovel resort official webcams", url="https://bukovel.com/cams", terms_url="https://bukovel.com/",
        license_="Not stated", media_rights="No reuse licence; links to the resort's own camera pages only (wartime caution: no street or road cameras).",
        attribution="Bukovel (bukovel.com)", evidence=["https://bukovel.com/cams"], formats=["official_page"], countries=["UA"],
        page_hosts=["bukovel.com"], coordinate_role="approximate", raw=raw_files(out, "ua_bukovel_cams", "sitemap.xml"))
    return {"status": "integrated", "country": "UA", "items": items, "policy": pol,
            "robots": "bukovel.com: auth/basket/account/admin paths disallowed only",
            "notes": "kept by the ua-martial-law rule only because the page host is bukovel.com (keep_hosts)"}


def build_orleans_metropole_webcams(out):
    r = refused(out, "orleans_metropole_webcams")
    return held_result(
        "orleans_metropole_webcams", "FR", "Webcam — Orléans Métropole", "https://www.data.gouv.fr/datasets/webcam-orleans-metropole",
        "the only camera-list routes are Opendatasoft exports under data.orleans-metropole.fr/api/, which robots.txt "
        "disallows for all agents" + (f" ({r['reason']})" if r else ""),
        "a list outside /api/ (static data.gouv.fr resource) or the publisher's permission",
        [ORLEANS_DATASET, "https://data.orleans-metropole.fr/robots.txt"],
        refused_hosts=[{"host": "data.orleans-metropole.fr", "reason": "robots.txt Disallow: /api/"}],
        robots="www.data.gouv.fr: /api/1/datasets/ allowed; data.orleans-metropole.fr: Disallow /api/")


def build_loire_atlantique_bridge_ferry_cams(out):
    return held_result(
        "loire_atlantique_bridge_ferry_cams", "FR", "Webcams du pont de Saint-Nazaire et des bacs de Loire",
        "https://www.data.gouv.fr/datasets/webcams-du-pont-de-saint-nazaire-et-des-bacs-de-loire-temps-reel",
        "low confidence in the register: image file ids may change per refresh, the publisher's /api/ is robots-disallowed, no coordinates",
        "a stable image URL outside /api/ or the publisher's confirmation",
        ["https://www.etalab.gouv.fr/wp-content/uploads/2017/04/ETALAB-Licence-Ouverte-v2.0.pdf"])


def low_confidence(source_id, country, name, url, evidence, reason="low confidence in the register"):
    def build(out):
        return held_result(source_id, country, name, url, reason, "a re-check raising confidence "
                           "(camera list, coordinates and terms read)", evidence)
    return build


def build_trafikverket_cameras(out):
    return held_result("trafikverket_cameras", "SE", "Trafikverket — Camera object (open traffic API)",
                       "https://api.trafikinfo.trafikverket.se/v2/data.json",
                       "API key required (not registered); CC0 coverage of the real-time images unconfirmed",
                       "the user registers a free API key and the Camera images are confirmed under the CC0 terms",
                       ["https://bransch.trafikverket.se/contentassets/697793c5366a46369c10efdbd0080cbd/termsofuse_hvd.json"])


def build_tfl_jamcam(out):
    return held_result("tfl_jamcam", "GB", "Transport for London JamCams", "https://api.tfl.gov.uk/Place/Type/JamCam",
                       "upgrade to viewable held: the TfL Transport Data Service licence applies from the user's free API-portal "
                       "registration, which has not been made; the existing page_only policy stays as it is",
                       "the user's TfL API-portal registration; pin the S3 path /jamcams.tfl.gov.uk/",
                       ["https://tfl.gov.uk/corporate/terms-and-conditions/transport-data-service"])


SOURCES = {
    "chmi": {"fetch": fetch_chmi, "build": build_chmi},
    "geneva_sitg": {"fetch": fetch_geneva_sitg, "build": build_geneva_sitg},
    "meteoswiss_weathercams": {"fetch": fetch_meteoswiss_weathercams, "build": build_meteoswiss_weathercams},
    "arso_webcams": {"fetch": fetch_arso_webcams, "build": build_arso_webcams},
    "dwd_webcams": {"fetch": fetch_dwd_webcams, "build": build_dwd_webcams},
    "hamburg_verkehrskameras": {"fetch": fetch_hamburg_verkehrskameras, "build": build_hamburg_verkehrskameras},
    "loire_atlantique_bridge_ferry_cams": {"build": build_loire_atlantique_bridge_ferry_cams},
    "cita_luxembourg": {"fetch": fetch_cita_luxembourg, "build": build_cita_luxembourg},
    "foto_webcam_eu": {"fetch": fetch_foto_webcam_eu, "build": build_foto_webcam_eu},
    "faroe_landsverk": {"fetch": fetch_faroe_landsverk, "build": build_faroe_landsverk},
    "dir_centre_est_webcams": {"fetch": fetch_dir_centre_est_webcams, "build": build_dir_centre_est_webcams},
    "traffic_wales_cctv": {"fetch": fetch_traffic_wales_cctv, "build": build_traffic_wales_cctv},
    "topr_pogoda_cams": {"fetch": fetch_topr_pogoda_cams, "build": build_topr_pogoda_cams},
    "orleans_metropole_webcams": {"fetch": fetch_orleans_metropole_webcams, "build": build_orleans_metropole_webcams},
    "attiki_odos_live": {"fetch": fetch_attiki_odos_live, "build": build_attiki_odos_live},
    "bretten_webcams": {"fetch": fetch_bretten_webcams, "build": build_bretten_webcams},
    "ua_bukovel_cams": {"fetch": fetch_ua_bukovel_cams, "build": build_ua_bukovel_cams},
    "promet_si_cameras": {"build": low_confidence("promet_si_cameras", "SI", "promet.si / NAP Slovenia traffic cameras",
                                                  "https://www.promet.si/sl/kamere", ["https://promet.si/en/kolofon"])},
    "grenoble_metromobilite_cams": {"build": low_confidence("grenoble_metromobilite_cams", "FR", "Métromobilité (Grenoble-Alpes) traffic cameras",
                                                            "https://data.mobilites-m.fr/donnees", ["https://data.mobilites-m.fr/donnees"])},
    "lapalma_webcam_directory": {"build": low_confidence("lapalma_webcam_directory", "ES", "Cabildo de La Palma — webcam directory",
                                                         "https://datos.gob.es/catalogo/l03380010-webcam",
                                                         ["https://www.opendatalapalma.es/pages/avisolegal"])},
    "ru_krasnaya_polyana": {"build": low_confidence("ru_krasnaya_polyana", "RU", "Krasnaya Polyana resort webcams (Sochi)",
                                                    "https://krasnayapolyanaresort.ru/webcams", ["https://krasnayapolyanaresort.ru/webcams"])},
    "ru_isp_city_cams": {"build": low_confidence("ru_isp_city_cams", "RU", "Russian ISP 'smart city' public cameras",
                                                 "https://stream.is74.ru/", ["https://stream.is74.ru/", "https://maps.ufanet.ru/"])},
    "ru_rosa_khutor": {"build": low_confidence("ru_rosa_khutor", "RU", "Rosa Khutor resort webcams", "https://rosaski.com/",
                                               ["https://rosaski.com/"])},
    "ru_moscow_city": {"build": low_confidence("ru_moscow_city", "RU", "Moscow city services (data.mos.ru, transport.mos.ru)",
                                               "https://data.mos.ru/", ["https://data.mos.ru/"],
                                               "low confidence in the register, which rejects it: no public reusable official "
                                               "source reached; mos.ru robots.txt disallows Anthropic agents")},
    "trafikverket_cameras": {"build": build_trafikverket_cameras},
    "tfl_jamcam": {"build": build_tfl_jamcam},
}

CHECKS = {"chmi": check_snapshot, "geneva_sitg": check_snapshot, "meteoswiss_weathercams": check_snapshot}

ETIQUETTE = [
    "Robots re-check after the webcam_fetch.Robots fix (RFC 9309 wildcards): every list, page and image URL fetched for this "
    "family and collect_italy.py (46 URLs) is allowed by its host's robots.txt, except the MeteoSwiss image redirect below; "
    "the two refused URLs (Orléans /api/ export, meteo.fvg.it) were never requested. The re-check re-read each host's "
    "robots.txt once (no other request).",
    "meteoswiss_weathercams: the one image sample followed a 302 from backend.roundshot.com (robots allow all) to "
    "storage2.roundshot.com, whose robots.txt (read afterwards) is 'Disallow: /'; 18,552 bytes sampled, nothing kept. "
    "The source is page-only because of it; the event is kept as raw/meteoswiss_weathercams/image_check_event.json.",
    "orleans_metropole_webcams: the data.gouv.fr dataset record was requested twice (a re-run), one request over plan.",
    "The first fetch pass ran the same fetch functions from a scratch runner, so per-source request_log.json files were not "
    "written; every response has its receipt (URL, time, status, SHA-256) under raw/<source>/.",
]


def main(argv=None):
    return run(FAMILY, SOURCES, main_args(argv), CHECKS, ETIQUETTE)


if __name__ == "__main__":
    sys.exit(main())
