#!/usr/bin/env python3
"""Collect US federal webcam sources (USGS, NOAA) for the Q-Globe catalogue (stdlib only).

Sources (ids as in the 2026-11 Americas register):
  usgs_hivis_nims       USGS HIVIS/NIMS stream-gauge cameras: snapshots (time-stamped S3 JPEGs)
  usgs_volcview_ashcam  USGS VolcView/Ashcam: snapshots only for cameras a USGS observatory publishes
                        on its own usgs.gov host; other cameras without a stated owner as links to
                        the USGS Ashcam page; FAA, NPS and third-party cameras left out
  noaa_ndbc_buoycams    NOAA NDBC BuoyCAMs: stable per-station snapshot, links when no current image
  noaa_glerl_metcams    NOAA GLERL Great Lakes station webcams, coordinates from GLERL's station pages

Network goes only through webcam_fetch.PoliteClient (robots.txt, 1 s per host, HTTPS, no bypass);
only the camera lists and the terms/station pages are requested, plus at most one image sample
per provider. Parsing is in pure functions (tests/test_collect_us_federal.py runs them offline).

  python scripts/collect_us_federal.py --out <dir>      # writes <dir>/<source>.json, raw/, policies/, checks/, reports/
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import quote, urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as W  # noqa: E402

FAMILY = "us_federal"
REVIEWED_AT = "2026-11-14"
MAX_IMAGE_AGE_DAYS = 30
USGS_TERMS = "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits"
NWS_TERMS = "https://www.weather.gov/disclaimer"
GLERL_TERMS = "https://www.glerl.noaa.gov/home/notice.html"

# ---------------------------------------------------------------- USGS HIVIS / NIMS
NIMS_CATALOG = "https://api.waterdata.usgs.gov/nims/v0/cameras"
NIMS_LIST = (NIMS_CATALOG + "?returnFields=camId,nwisId,camName,camDesc,lat,lng,stateAbrv,tz,newestImageDT,"
             "hideCam,overlayDir,smallDir,modifiedDate,ingest")
NIMS_OPENAPI = "https://api.waterdata.usgs.gov/nims/v0/openapi.json"
NIMS_HOST = "usgs-nims-images.s3.amazonaws.com"
HIVIS_PAGE = "https://apps.usgs.gov/hivis/"
# Cameras whose own description names a non-USGS operator or partner programme: public domain
# (17 USC 105) is only claimed for USGS-produced imagery, so these stay out.
NIMS_PARTNER = re.compile(r"partner|operated by|butterfly monitoring project|can be deleted", re.I)
NIMS_TEST = re.compile(r"test", re.I)
US_TERRITORIES = {"PR": "PR", "GU": "GU", "VI": "VI", "AS": "AS", "MP": "MP"}

# ---------------------------------------------------------------- USGS VolcView / Ashcam
VOLCVIEW_LIST = "https://volcview.wr.usgs.gov/ashcam-api/webcamApi/webcams"
VOLCVIEW_HOST = "volcview.wr.usgs.gov"
ASHCAM_GUI = "https://volcview.wr.usgs.gov/ashcam-gui/"
ASHCAM_PAGE = "https://volcview.wr.usgs.gov/ashcam-gui/webcam.html?webcam={code}"
MEDIA_PATH = re.compile(r"\.(?:jpe?g|png|gif|mp4|m3u8)$", re.I)

# ---------------------------------------------------------------- NOAA NDBC
NDBC_LIST = "https://www.ndbc.noaa.gov/buoycams.php"
NDBC_PAGE = "https://www.ndbc.noaa.gov/buoycams.shtml"
NDBC_IMAGE = "https://www.ndbc.noaa.gov/buoycam.php?station={id}"
NDBC_STATION = "https://www.ndbc.noaa.gov/station_page.php?station={id}"
NDBC_BASINS = {"41": "Atlantic", "44": "Atlantic", "42": "Gulf of Mexico", "45": "Great Lakes",
               "46": "Pacific", "51": "Pacific (Hawaii)", "52": "Pacific (Marianas)"}

# ---------------------------------------------------------------- NOAA GLERL
GLERL_INDEX = "https://www.glerl.noaa.gov/metdata/"
GLERL_HOST = "www.glerl.noaa.gov"


def utc(value):
    """ISO 8601 / RFC 2822-free UTC parse used by the NIMS and VolcView fields."""
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def coords(lat, lng):
    lat, lng = float(lat), float(lng)
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError("no usable coordinates")
    return round(lat, 6), round(lng, 6)


def safe_id(value):
    """The official id, with characters outside the catalogue's id alphabet replaced by '_' (deterministic)."""
    out = re.sub(r"[^A-Za-z0-9:_.-]", "_", str(value).strip())
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,150}", out):
        raise ValueError("unusable official id")
    return out


def base_item(provider, provider_id, name, lat, lng, country, region, observed_at, **extra):
    item = {"provider": provider, "provider_id": provider_id, "id": f"{provider}:{provider_id}",
            "name": name, "lat": lat, "lng": lng, "country": country, "region": region,
            "stream_url": None, "snapshot_url": None, "observed_at": observed_at,
            "health": {"status": "unverified"}}
    item.update(extra)
    return item


# ================================================================= parsers (pure)
def nims_image_name(cam_id, newest):
    """NIMS file name: '<camId>___<newestImageDT with ':' as '-' and no fraction>Z.jpg' (checked with /listFiles)."""
    return f"{cam_id}___{utc(newest):%Y-%m-%dT%H-%M-%S}Z.jpg"


def parse_nims(rows, observed_at, now=None):
    """NIMS /cameras rows -> (items, excluded counts)."""
    now = now or utc(observed_at)
    items, excluded, seen = [], {}, set()

    def skip(reason):
        excluded[reason] = excluded.get(reason, 0) + 1

    for r in rows:
        cam = r.get("camId") or ""
        text = " ".join(str(r.get(k) or "") for k in ("camId", "camName", "camDesc"))
        if r.get("hideCam"):
            skip("hidden")
            continue
        if NIMS_TEST.search(cam) or NIMS_TEST.search(str(r.get("camName") or "")):
            skip("test_camera")
            continue
        if NIMS_PARTNER.search(text):
            skip("partner_or_non_usgs_operator")
            continue
        newest = r.get("newestImageDT")
        if not newest:
            skip("no_image")
            continue
        taken = utc(newest)
        if (now - taken).days > MAX_IMAGE_AGE_DAYS:
            skip("image_older_than_30_days")
            continue
        try:
            lat, lng = coords(r.get("lat"), r.get("lng"))
            pid = safe_id(cam)
        except (TypeError, ValueError):
            skip("no_coordinates_or_bad_id")
            continue
        small = r.get("smallDir") or ""
        if not small.startswith(f"https://{NIMS_HOST}/") or pid in seen:
            skip("unexpected_image_host_or_duplicate")
            continue
        seen.add(pid)
        state = str(r.get("stateAbrv") or "").upper()
        interval = (r.get("ingest") or {}).get("intr")
        items.append(base_item(
            "usgs_hivis_nims", pid, str(r.get("camName") or cam).strip(), lat, lng,
            US_TERRITORIES.get(state, "US"), state, observed_at,
            format="snapshot", rights_status="official_public_feed",
            snapshot_url=quote(small + nims_image_name(cam, newest), safe=":/"),
            official_page=HIVIS_PAGE + "camera/" + quote(cam, safe=""),
            source_page=HIVIS_PAGE, source_catalog=NIMS_CATALOG, coordinate_role="camera_location",
            requires_catalog_refresh=True, image_observed_at=iso(taken),
            image_interval_minutes=interval if isinstance(interval, int) else None,
            camera_description=str(r.get("camDesc") or "").strip()[:300] or None,
            nwis_site_id=r.get("nwisId") or None, provider_in_service=True,
            note="The NIMS image URL names one capture time; a catalogue refresh moves it to the newest image."))
    return items, excluded


def volcview_region(lat, lng):
    if lat > 50 and (lng < -129 or lng > 170):
        return "AK"
    if lat < 23 and lng < -150:
        return "HI"
    if 44 <= lat <= 45.2 and -111.2 <= lng <= -109.8:
        return "WY"
    if lat >= 45.7:
        return "WA"
    if lat >= 42:
        return "OR"
    return "CA"


def classify_volcview(cam, now):
    """('viewable'|'page'|'excluded', reason) for one Ashcam webcam row."""
    code, name = str(cam.get("webcamCode") or ""), str(cam.get("webcamName") or "")
    ext = cam.get("externalUrl") or ""
    if re.search(r"test|\bbad\b|^bad$", code + " " + name, re.I) or (ext and "://" not in ext):
        return "excluded", "test_or_placeholder"
    try:
        coords(cam.get("latitude"), cam.get("longitude"))
        safe_id(code)
    except (TypeError, ValueError):
        return "excluded", "no_coordinates_or_bad_id"
    last = cam.get("lastImageTimestamp")
    if not last or (now - utc(last)).days > MAX_IMAGE_AGE_DAYS:
        return "excluded", "image_older_than_30_days"
    if cam.get("faaInd") == "Y":
        return "excluded", "faa_weathercam_left_to_livetraf_faa_links"
    host = (urlsplit(ext).hostname or "").lower() if ext else ""
    if host.endswith("nps.gov"):
        return "excluded", "nps_camera_left_to_nps_source"
    if host and not host.endswith(".usgs.gov"):
        return "excluded", "third_party_camera"
    current = cam.get("currentImageUrl") or ""
    if host and current.startswith(f"https://{VOLCVIEW_HOST}/"):
        return "viewable", "usgs_observatory_host"
    return "page", "owner_not_stated"


def parse_volcview(doc, observed_at, now=None):
    """Ashcam webcams document -> (items, excluded counts)."""
    now = now or utc(observed_at)
    items, excluded, seen = [], {}, set()
    for cam in doc.get("webcams", []):
        kind, reason = classify_volcview(cam, now)
        if kind == "excluded":
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        code = cam["webcamCode"]
        pid = safe_id(code)
        if pid in seen:
            excluded["duplicate"] = excluded.get("duplicate", 0) + 1
            continue
        seen.add(pid)
        lat, lng = coords(cam["latitude"], cam["longitude"])
        page = ASHCAM_PAGE.format(code=quote(code, safe=""))
        volcano = cam.get("vName")
        common = dict(source_page=ASHCAM_GUI, source_catalog=VOLCVIEW_LIST, coordinate_role="station_location",
                      volcano=volcano, bearing_deg=cam.get("bearingDeg"),
                      image_observed_at=iso(utc(cam["lastImageTimestamp"])), provider_in_service=True)
        name = str(cam.get("webcamName") or code).strip()
        if volcano and volcano.lower() not in name.lower():
            name = f"{volcano} — {name}"
        if kind == "viewable":
            ext = cam["externalUrl"]
            official = ext if urlsplit(ext).hostname == "volcanoes.usgs.gov" and not MEDIA_PATH.search(urlsplit(ext).path) else page
            items.append(base_item("usgs_volcview_ashcam", pid, name, lat, lng, "US", volcview_region(lat, lng), observed_at,
                                   format="snapshot", rights_status="official_public_feed",
                                   snapshot_url=cam["currentImageUrl"], official_page=official,
                                   reference_url=page if official != page else None,
                                   requires_catalog_refresh=False, ownership_basis="usgs_observatory_host", **common))
        else:
            items.append(base_item("usgs_volcview_ashcam", pid, name, lat, lng, "US", volcview_region(lat, lng), observed_at,
                                   format="official_page", rights_status="official_page_only", official_page=page,
                                   ownership_basis="owner_not_stated_link_only", **common))
    return items, excluded


def ndbc_image_time(name):
    m = re.search(r"_(\d{4})_(\d{2})_(\d{2})_(\d{2})(\d{2})\.jpg$", name or "")
    return iso(dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc)) if m else None


def parse_ndbc(rows, observed_at):
    items, excluded = [], {}
    for r in rows:
        try:
            sid = safe_id(r["id"])
            lat, lng = coords(r["lat"], r["lng"])
        except (KeyError, TypeError, ValueError):
            excluded["no_coordinates_or_bad_id"] = excluded.get("no_coordinates_or_bad_id", 0) + 1
            continue
        common = dict(official_page=NDBC_STATION.format(id=quote(sid)), source_page=NDBC_PAGE, source_catalog=NDBC_LIST,
                      coordinate_role="station_location", station_id=sid, provider_in_service=True)
        name = f"NDBC {sid} — {re.sub(r'\s+', ' ', str(r.get('name') or '')).strip()}"
        region = NDBC_BASINS.get(sid[:2], "Offshore")
        if r.get("img"):
            items.append(base_item("noaa_ndbc_buoycams", sid, name, lat, lng, "US", region, observed_at,
                                   format="snapshot", rights_status="official_public_feed",
                                   snapshot_url=NDBC_IMAGE.format(id=quote(sid)), image_observed_at=ndbc_image_time(r["img"]),
                                   image_width=r.get("width"), image_height=r.get("height"), requires_catalog_refresh=False,
                                   note="Six-direction panorama (about 2880x300): scale to the viewer width.", **common))
        else:
            items.append(base_item("noaa_ndbc_buoycams", sid, name, lat, lng, "US", region, observed_at,
                                   format="official_page", rights_status="official_page_only",
                                   note="No current BuoyCAM image at collection time: station page link only.", **common))
    return items, excluded


GLERL_ROW = re.compile(r'<td colspan="\d+">\s*<a href="([^"]+)">([^<]+)</a>\s*</td>'
                       r'|<a href="cams/([a-z0-9][a-z0-9-]*)\.jpg\?(\d{10})"')
GLERL_DMS = re.compile(r"\(([A-Z0-9]{4,6})\)(?:&nbsp;|\s)*(\d+)&deg;\s*(\d+)&acute;\s*(\d+)&quot;\s*([NS]),(?:&nbsp;|\s)*"
                       r"(\d+)&deg;\s*(\d+)&acute;\s*(\d+)&quot;\s*([EW])")
GLERL_DM = re.compile(r"Location:\s*(\d+)&deg;\s*([\d.]+)&acute;\s*([NS]),(?:&nbsp;|\s)*(\d+)&deg;\s*([\d.]+)&acute;\s*([EW])")
GLERL_LISTING = re.compile(r"\['([^']+)',\s*(-?\d+\.\d+),\s*(-?\d+\.\d+),\s*'([^']+)'")


def glerl_station_url(href):
    url = urljoin(GLERL_INDEX, href)
    path = urlsplit(url).path
    return url if path.endswith("/") or "." in path.rsplit("/", 1)[-1] else url + "/"


def parse_glerl_index(text):
    """Index page -> (cameras [(cam, stamp, station_url, station_name)], listing {station key: (lat, lng)})."""
    cams, station = [], (None, None)
    start = text.find("Latest Webcam Images")
    for m in GLERL_ROW.finditer(text, max(start, 0)):
        if m.group(1):
            station = (glerl_station_url(m.group(1)), html.unescape(m.group(2)).strip())
        elif station[0]:
            cams.append((m.group(3), m.group(4), station[0], station[1]))
    listing = {}
    for name, lat, lng, url in GLERL_LISTING.findall(text):
        listing[glerl_station_url(url)] = (float(lat), float(lng))
    return cams, listing


def parse_glerl_station(text):
    """{'lat', 'lng', 'ndbc_id', 'title'} from a GLERL station page; lat/lng None when it publishes no position."""
    title = re.search(r"<title>\s*([^<|]+)", text)
    found = {"lat": None, "lng": None, "ndbc_id": None,
             "title": html.unescape(title.group(1)).strip() if title else None}
    heading = text[text.find("<h1"):] if "<h1" in text else ""
    sid = re.search(r"\(([A-Z0-9]{4,6})\)", heading)
    found["ndbc_id"] = sid.group(1) if sid else None
    m = GLERL_DMS.search(text)
    if m:
        _, d1, m1, s1, ns, d2, m2, s2, ew = m.groups()
        found["lat"] = round((int(d1) + int(m1) / 60 + int(s1) / 3600) * (-1 if ns == "S" else 1), 6)
        found["lng"] = round((int(d2) + int(m2) / 60 + int(s2) / 3600) * (-1 if ew == "W" else 1), 6)
        return found
    m = GLERL_DM.search(text)
    if m:
        d1, m1, ns, d2, m2, ew = m.groups()
        found["lat"] = round((int(d1) + float(m1) / 60) * (-1 if ns == "S" else 1), 6)
        found["lng"] = round((int(d2) + float(m2) / 60) * (-1 if ew == "W" else 1), 6)
    return found


def glerl_stamp(stamp):
    """'2611140700' (YYMMDDHHMM, the page's cache-busting version; local time) -> date for the 30-day rule."""
    return dt.datetime.strptime(stamp, "%y%m%d%H%M").replace(tzinfo=dt.timezone.utc)


def parse_glerl(index_text, station_pages, observed_at, now=None):
    """station_pages: {station_url: page html}. -> (items, excluded counts)."""
    now = now or utc(observed_at)
    cams, listing = parse_glerl_index(index_text)
    items, excluded = [], {}
    for cam, stamp, station_url, station_name in cams:
        if (now - glerl_stamp(stamp)).days > MAX_IMAGE_AGE_DAYS:
            excluded["image_older_than_30_days"] = excluded.get("image_older_than_30_days", 0) + 1
            continue
        found = parse_glerl_station(station_pages.get(station_url) or "")
        on_page = found["lat"] is not None
        lat_lng = (found["lat"], found["lng"]) if on_page else listing.get(station_url)
        if not lat_lng:
            excluded["no_station_coordinates"] = excluded.get("no_station_coordinates", 0) + 1
            continue
        state = re.search(r",\s*([A-Z]{2})\b", found["title"] or "")
        number = int(re.search(r"(\d+)$", cam).group(1))
        items.append(base_item(
            "noaa_glerl_metcams", cam, f"{station_name} — webcam {number}", lat_lng[0], lat_lng[1], "US",
            state.group(1) if state else "", observed_at, format="snapshot", rights_status="official_public_feed",
            snapshot_url=f"https://{GLERL_HOST}/metdata/cams/{cam}.jpg", official_page=station_url,
            source_page=GLERL_INDEX, source_catalog=GLERL_INDEX, coordinate_role="station_location",
            station_ndbc_id=found["ndbc_id"],
            coordinate_source=station_url if on_page else GLERL_INDEX + " (station map on the page)",
            image_version=stamp, requires_catalog_refresh=False, provider_in_service=True))
    return items, excluded


# ================================================================= policies
def viewable_source(sid, name, url, catalog, terms, licence, licence_url, media_rights, attribution, hosts,
                    refresh, evidence, note=None):
    return {"id": sid, "name": name, "url": url, "catalog_url": catalog, "terms_url": terms,
            "metadata_license": licence, "license": licence, "license_url": licence_url,
            "media_rights": media_rights, "rights_note": note or media_rights, "attribution": attribution,
            "rights_status": "official_public_feed", "allowed_hosts": hosts, "minimum_refresh_seconds": refresh,
            "review_status": "reviewed_for_snapshot_and_reference_use", "reviewed_at": REVIEWED_AT,
            "evidence": evidence}


def policies():
    usgs_pd = "US Government work in the public domain (17 USC 105); USGS Copyrights and Credits"
    return {
        "usgs_hivis_nims": {
            "source": viewable_source(
                "usgs_hivis_nims", "USGS HIVIS / NIMS stream-gauge cameras", HIVIS_PAGE, NIMS_CATALOG, USGS_TERMS,
                usgs_pd, USGS_TERMS,
                "'USGS-authored or produced data and information are considered to be in the U.S. Public Domain' "
                "(USGS Copyrights and Credits, re-read 2026-11-14); NIMS delivers imagery from USGS gaging stations "
                "'for public consumption' (NIMS OpenAPI, licence: US Government work in the public domain). Cameras "
                "whose description names a partner programme or another operator are left out.",
                "Image: U.S. Geological Survey, HIVIS/NIMS (public domain)", [NIMS_HOST], 3600,
                [USGS_TERMS, NIMS_OPENAPI],
                "Credit requested by USGS: 'Credit: U.S. Geological Survey'. Image URLs name one capture time: the "
                "catalogue must be refreshed to show newer images (records carry requires_catalog_refresh)."),
            "media_hosts": [NIMS_HOST], "page_hosts": ["apps.usgs.gov"], "formats": ["snapshot"],
            "countries": ["US", "PR", "GU", "VI", "AS", "MP"], "operator_hints": [], "coordinate_role": "camera_location"},
        "usgs_volcview_ashcam": {
            "source": {**viewable_source(
                "usgs_volcview_ashcam", "USGS VolcView / Ashcam volcano webcams", ASHCAM_GUI, VOLCVIEW_LIST, USGS_TERMS,
                "USGS Ashcam webcam list (factual metadata); USGS-produced images are US public domain", USGS_TERMS,
                "Snapshots only for cameras that a USGS observatory publishes on its own usgs.gov host (HVO "
                "volcanoes.usgs.gov, CVO cvo-valve/tahoma.wr.usgs.gov): USGS-produced, public domain. Cameras with no "
                "stated owner (AVO stations run with UAF-GI/ADGGS, other Cascades/Yellowstone stations) are links to "
                "the USGS Ashcam page only. FAA (faaInd=Y), NPS-hosted and third-party cameras are not included.",
                "USGS Volcano Hazards Program (HVO, CVO, YVO) / Alaska Volcano Observatory, via USGS Ashcam",
                [VOLCVIEW_HOST], 600, [USGS_TERMS, VOLCVIEW_LIST, ASHCAM_GUI]),
                "review_status": "reviewed_for_snapshot_and_reference_use"},
            "media_hosts": [VOLCVIEW_HOST], "page_hosts": [VOLCVIEW_HOST, "volcanoes.usgs.gov"],
            "formats": ["snapshot", "official_page"], "countries": ["US"], "operator_hints": [],
            "coordinate_role": "station_location"},
        "noaa_ndbc_buoycams": {
            "source": viewable_source(
                "noaa_ndbc_buoycams", "NOAA NDBC BuoyCAMs", NDBC_PAGE, NDBC_LIST, NWS_TERMS,
                "US federal public domain (NOAA/NWS)", NWS_TERMS,
                "'The information on National Weather Service (NWS) Web pages are in the public domain, unless "
                "specifically noted otherwise, and may be used without charge for any lawful purpose' (NWS disclaimer, "
                "re-read 2026-11-14; NDBC's disclaimer page redirects to it). Do not imply NOAA endorsement.",
                "NOAA National Data Buoy Center BuoyCAM (public domain)", ["www.ndbc.noaa.gov"], 3600,
                [NWS_TERMS, NDBC_LIST],
                "Offshore stations: country is the operator (US), position is the buoy station. Images are 2880x300 "
                "six-direction panoramas."),
            "media_hosts": ["www.ndbc.noaa.gov"], "page_hosts": ["www.ndbc.noaa.gov"],
            "formats": ["snapshot", "official_page"], "countries": ["US"], "operator_hints": [],
            "coordinate_role": "station_location", "force_coordinate_role": "station_location"},
        "noaa_glerl_metcams": {
            "source": viewable_source(
                "noaa_glerl_metcams", "NOAA GLERL Great Lakes meteorological station webcams", GLERL_INDEX, GLERL_INDEX,
                GLERL_TERMS, "US federal public domain (NOAA)", GLERL_TERMS,
                "'Information presented on these pages is considered public information and may be distributed or "
                "copied. Use of appropriate byline/photo/image credits is requested.' (GLERL Disclaimer and IP Notice, "
                "read 2026-11-14). Station positions from GLERL's own station pages.",
                "NOAA GLERL (public domain)", [GLERL_HOST], 1800, [GLERL_TERMS, GLERL_INDEX, NWS_TERMS]),
            "media_hosts": [GLERL_HOST], "page_hosts": [GLERL_HOST], "formats": ["snapshot"], "countries": ["US"],
            "operator_hints": [], "coordinate_role": "station_location", "force_coordinate_role": "station_location"},
    }


# ================================================================= network run
def run(out, client=None):
    out = Path(out)
    client = client or W.PoliteClient()
    pols, checks, report, refused = policies(), {}, {"family": FAMILY, "sources": [], "held": [], "hosts_refused": []}, []

    def save(source, name, response):
        return W.save_raw(out / "raw" / source, name, response)

    def emit(source, items, excluded, check_item, notes):
        W.write_catalog(out / f"{source}.json", [source], items)
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{source}.json").write_text(json.dumps({source: pols[source]}, ensure_ascii=False, indent=1), encoding="utf-8")
        event = None
        if check_item:
            event = client.check_image(check_item["snapshot_url"], source, check_item["id"], pols[source]["media_hosts"])
            (out / "checks").mkdir(parents=True, exist_ok=True)
            (out / "checks" / f"{source}.snapshot.json").write_text(json.dumps([event], indent=1), encoding="utf-8")
        counts = {"viewable": sum(i["format"] == "snapshot" for i in items),
                  "page_only": sum(i["format"] == "official_page" for i in items)}
        report["sources"].append({
            "id": source, "status": "integrated", "countries": sorted({i["country"] for i in items}), "records": counts,
            "excluded": excluded, "input_file": f"{source}.json", "policy_file": f"policies/{source}.json",
            "check": event and {k: event.get(k) for k in ("record_id", "status", "http_status", "signature", "content_type")},
            "notes": notes})
        print(source, counts, excluded, event and event.get("status"))

    def fail(source, reason):
        refused.append({"source": source, "reason": reason})
        report["held"].append({"id": source, "reason": reason})
        pols[source] = {"status": "held", "held_reason": reason, "held_until": "the host answers the list request politely",
                        "evidence": pols[source]["source"]["evidence"],
                        "source": {k: pols[source]["source"][k] for k in ("id", "name", "url")}}
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{source}.json").write_text(json.dumps({source: pols[source]}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(source, "HELD", reason)

    # USGS terms first: the gauges and VolcView are integrated only if the page is readable now.
    usgs_error = "page did not state the public-domain clause"
    try:
        terms = client.get(USGS_TERMS)
        save("usgs_hivis_nims", "usgs_copyrights_and_credits.html", terms)
        usgs_ok = b"Public Domain" in terms["body"] and terms["status"] == 200
    except (W.Refused, OSError) as e:
        usgs_ok, usgs_error = False, str(e)[:160]
    for source in ("usgs_hivis_nims", "usgs_volcview_ashcam"):
        if not usgs_ok:
            fail(source, f"USGS Copyrights and Credits page not readable now ({usgs_error}); public-domain basis not re-read")
            continue
        try:
            if source == "usgs_hivis_nims":
                rows, r = client.get_json(NIMS_LIST)
                save(source, "nims_cameras.json", r)
                items, excluded = parse_nims(rows, r["observed_at"])
                notes = ["USGS copyright page re-read 2026-11-14: USGS-authored data are U.S. Public Domain."]
            else:
                doc, r = client.get_json(VOLCVIEW_LIST)
                save(source, "volcview_webcams.json", r)
                items, excluded = parse_volcview(doc, r["observed_at"])
                notes = ["Changed from the register: FAA cameras (faaInd=Y) not integrated (FAA per-site ownership "
                         "unreadable, FAA API 401; duplicates livetraf_faa_links)."]
        except (W.Refused, OSError, ValueError) as e:
            fail(source, f"camera list not readable: {str(e)[:160]}")
            continue
        sample = next((i for i in items if i["format"] == "snapshot"), None)
        emit(source, items, excluded, sample, notes)

    try:
        rows, r = client.get_json(NDBC_LIST)
        save("noaa_ndbc_buoycams", "buoycams.json", r)
        terms = client.get(NWS_TERMS)
        save("noaa_ndbc_buoycams", "nws_disclaimer.html", terms)
        items, excluded = parse_ndbc(rows, r["observed_at"])
        emit("noaa_ndbc_buoycams", items, excluded, next((i for i in items if i["format"] == "snapshot"), None), [])
    except (W.Refused, OSError, ValueError) as e:
        fail("noaa_ndbc_buoycams", f"camera list not readable: {str(e)[:160]}")

    try:
        r = client.get(GLERL_INDEX)
        save("noaa_glerl_metcams", "glerl_metdata.html", r)
        notice = client.get(GLERL_TERMS)
        save("noaa_glerl_metcams", "glerl_notice.html", notice)
        index = r["body"].decode("utf-8", "replace")
        cams, _ = parse_glerl_index(index)
        now = utc(r["observed_at"])
        pages = {}
        for url in sorted({c[2] for c in cams if (now - glerl_stamp(c[1])).days <= MAX_IMAGE_AGE_DAYS}):
            try:
                page = client.get(url)
            except (W.Refused, OSError) as e:
                print("station page skipped", url, e)
                continue
            name = "station_" + re.sub(r"[^a-z0-9]+", "_", urlsplit(url).path.lower()).strip("_") + ".html"
            save("noaa_glerl_metcams", name, page)
            pages[url] = page["body"].decode("utf-8", "replace")
        items, excluded = parse_glerl(index, pages, r["observed_at"])
        emit("noaa_glerl_metcams", items, excluded, items[0] if items else None,
             ["Coordinates from GLERL's station pages (official NOAA source), fallback to the metdata station map."])
    except (W.Refused, OSError, ValueError) as e:
        fail("noaa_glerl_metcams", f"camera list not readable: {str(e)[:160]}")

    report["hosts_refused"] = refused
    report["robots"] = {base: (rule if isinstance(rule, str) else "robots.txt read and honoured")
                        for base, rule in client.robots.items()}
    report["generated_at"] = W.now()
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output folder (normalized inputs, raw/, policies/, checks/, reports/)")
    args = ap.parse_args(argv)
    run(args.out)


if __name__ == "__main__":
    main()
