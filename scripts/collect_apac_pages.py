#!/usr/bin/env python3
"""Collect official webcam PAGE links (no media) in Asia-Pacific, Antarctica and South Africa (2026-11-14).

  hong_kong_observatory_weather_photos  HKO weather photo pages; HKO forbids commercial use of the photos
                                        without written authorisation, so links only. Positions come from
                                        HKO's own station list, matched by station code (HKO's page script
                                        maps each camera to its weather station) or by identical site name;
                                        cameras at sites with no published station position are left out.
  aad_antarctic_webcams                 Australian Antarctic Division station webcams; non-commercial terms,
                                        so links only. Positions from the AAD station pages; the Nuyina
                                        icebreaker (moving) and the Kingston krill aquarium (no published
                                        position) are left out.
  south_africa_saao                     Update of the existing page-only provider (supersedes it): the four
                                        SAAO live-page cameras (same provider ids) plus the two all-sky
                                        cameras on the Sutherland weather page the live page now embeds.
Held policy fragments (no items) for the key-gated or unverified sources of this region.

Network only through webcam_fetch.PoliteClient. --offline rebuilds outputs from the saved raw responses.
  python scripts/collect_apac_pages.py --out <SCRATCH>/webcam-inputs-2026-11 [--catalog data/webcams.json]
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as F  # noqa: E402

FAMILY = "apac_pages"
REVIEWED_AT = "2026-11-14"

HKO = "https://www.hko.gov.hk"
HKO_INDEX = HKO + "/en/wxinfo/ts/index_webcam.htm"
HKO_STATIONS = HKO + "/en/cis/stn.htm"
HKO_SCRIPT = HKO + "/en/wxinfo/ts/webcam/files/wxphoto_e.js"
HKO_TERMS = HKO + "/en/readme/readme.htm"

AAD = "https://www.antarctica.gov.au"
AAD_INDEX = AAD + "/antarctic-operations/webcams/"
AAD_STATIONS = AAD + "/antarctic-operations/stations-and-field-locations/"
AAD_STATION = AAD_STATIONS + "{}/"
AAD_TERMS = AAD + "/about-us/copyright/"

SAAO_LIVE = "https://www.saao.ac.za/explore/media/saao-live/"
SAAO_SITE = "https://www.saao.ac.za/astronomers/sutherland/"
SAAO_WEATHER = "https://suthweather.saao.ac.za/"
SAAO_NAMES = {"lcogt": "LCOGT CPT Site Webcam", "domecam330": "SALT DomeCam330", "domecam190": "SALT DomeCam190",
              "solaris": "Solaris observatory webcam"}

POLICIES = {
    "hong_kong_observatory_weather_photos": {
        "source": {
            "id": "hong_kong_observatory_weather_photos", "name": "Hong Kong Observatory weather photos",
            "url": HKO_INDEX, "catalog_url": HKO_INDEX, "terms_url": HKO_TERMS,
            "metadata_license": "No open licence; factual links to the official HKO weather photo pages only",
            "license": "HKSAR Government copyright (Hong Kong Observatory conditions of use)",
            "media_rights": "Official page links only: HKO strictly prohibits commercial use of its materials without "
                            "prior written authorisation, so this paid app neither embeds nor fetches the photos.",
            "rights_note": ("「the use of the Materials for commercial purposes is strictly prohibited unless …」 prior "
                            "written authorisation of the Observatory. Robots: /wxinfo/ (the image path) is "
                            "disallowed; the /en/wxinfo/ photo pages are not. Positions are HKO weather-station "
                            "positions (station list), not surveyed camera mounts."),
            "attribution": "Hong Kong Observatory",
            "provider_notice": "Opens the official Hong Kong Observatory photo page. The marker is the HKO weather "
                               "station the camera belongs to.",
            "rights_status": "official_page_only", "allowed_hosts": [],
            "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT,
            "evidence": [HKO_TERMS, HKO_INDEX, HKO_STATIONS, HKO + "/robots.txt"],
        },
        "media_hosts": [], "page_hosts": ["www.hko.gov.hk"], "formats": ["official_page"], "countries": ["HK"],
        "operator_hints": ["hong kong observatory"], "coordinate_role": "station_location",
    },
    "aad_antarctic_webcams": {
        "source": {
            "id": "aad_antarctic_webcams", "name": "Australian Antarctic Division station webcams",
            "url": AAD_INDEX, "catalog_url": AAD_INDEX, "terms_url": AAD_TERMS,
            "metadata_license": "No open licence; factual links to the official AAD webcam pages only",
            "license": "Commonwealth of Australia copyright; personal, non-commercial use only",
            "media_rights": "Official page links only: the AAD allows personal non-commercial use and forbids "
                            "re-transmitting, distributing or commercialising the material without written approval.",
            "rights_note": ("「You are not permitted to re-transmit, distribute or commercialise the information or "
                            "material」 without 「prior written approval from the Commonwealth.」 Positions are the "
                            "station positions published on the AAD station pages."),
            "attribution": "Australian Antarctic Division",
            "provider_notice": "Opens the official Australian Antarctic Division webcam page. The marker is the "
                               "research station, not a surveyed camera mount.",
            "rights_status": "official_page_only", "allowed_hosts": [],
            "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT,
            "evidence": [AAD_TERMS, AAD_INDEX],
        },
        "media_hosts": [], "page_hosts": ["www.antarctica.gov.au"], "formats": ["official_page"], "countries": ["AQ"],
        "operator_hints": ["australian antarctic division"], "coordinate_role": "station_location",
        "force_coordinate_role": "station_location",
    },
    # Upgrade of the existing entry in scripts/webcam_source_policies.json (kept fields, new page host).
    "south_africa_saao": {
        "source": {
            "id": "south_africa_saao",
            "name": "South African Astronomical Observatory — public Sutherland webcams",
            "url": SAAO_LIVE, "catalog_url": SAAO_LIVE, "terms_url": "https://www.saao.ac.za/explore/media/",
            "metadata_license": "No explicit open media licence located; factual links to the official public "
                                "outreach pages only",
            "media_rights": "Official page links only; in-app media reuse not authorized by this adapter.",
            "attribution": "South African Astronomical Observatory (SAAO) / National Research Foundation (NRF); "
                           "Las Cumbres Observatory (LCOGT); Southern African Large Telescope (SALT)",
            "allowed_hosts": [], "rights_status": "official_page_only",
            "rights_note": ("The observatory deliberately publishes webcam animations on its public outreach page "
                            "(only statement: 「Copyright NRF | SAAO 2019」) and all-sky images on the Sutherland "
                            "weather page it embeds. This adapter does not copy or embed clips or images. The "
                            "published 1.0-m telescope coordinates identify the observing site, not the webcams."),
            "provider_notice": ("The official pages publish webcam animations and all-sky images. These are not "
                                "verified live streams. The marker identifies the Sutherland observing site, not a "
                                "surveyed camera location."),
            "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT,
            "review_note": "Approved scope is limited to the formats and origins in this registry; no upstream "
                           "liveness claim is accepted.",
            "evidence": [SAAO_LIVE, SAAO_SITE, SAAO_WEATHER],
        },
        "media_hosts": [], "page_hosts": ["www.saao.ac.za", "suthweather.saao.ac.za"], "formats": ["official_page"],
        "countries": ["ZA"], "operator_hints": [], "coordinate_role": "station_location",
        "force_coordinate_role": "station_location",
    },
}


def held(source_id, name, url, reason, until, evidence):
    return {source_id: {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
                        "source": {"id": source_id, "name": name, "url": url}, "reviewed_at": REVIEWED_AT}}


HELD = {}
for _entry in [
    held("korea_its_cctv", "Korea National Transport Information Center (ITS) CCTV open API",
         "https://www.data.go.kr/data/15040466/openapi.do",
         "API key required (free registration at its.go.kr); its.go.kr was unreachable from the research network; "
         "stream URLs may be http or short-lived.",
         "The user's decision to register a key, then proof that stream URLs are https, stable and key-free.",
         ["https://www.data.go.kr/data/15040466/openapi.do", "https://www.kogl.or.kr/info/licenseType1.do"]),
    held("korea_utic_police_cctv", "Korean National Police Agency urban traffic CCTV (UTIC) open API",
         "https://www.data.go.kr/data/15148511/openapi.do",
         "API key with approval (심의승인) required; count and stream format unknown.",
         "The user's decision to apply for a key, then a check of stream format, https and expiry.",
         ["https://www.data.go.kr/data/15148511/openapi.do"]),
    held("singapore_lta_datamall", "Singapore LTA DataMall Traffic Images", "https://datamall.lta.gov.sg/",
         "AccountKey required; image links are short-lived signed URLs, unsuitable for a static catalogue.",
         "A key plus a key-holding resolver that never exposes the key; the existing singapore_lta provider stays.",
         ["https://data.gov.sg/open-data-licence"]),
    held("taiwan_freeway_cctv", "Taiwan Freeway Bureau CCTV (national freeways)", "https://tisvcloud.freeway.gov.tw/",
         "Host timed out twice from the research network; nothing verified.",
         "A reachable CCTV list (no alternate host to dodge the block) and one image check.",
         ["https://data.gov.tw/license"]),
    held("taichung_transport_snapshot_upgrade", "Taichung real-time road images — snapshot upgrade of the existing "
         "page-only provider taichung_transport", "https://data.gov.tw/dataset/83750",
         "OGDL v1.0 plausibly covers the images, but the dataset's url field is a viewer page; no stable HTTPS "
         "image or HLS URL found. The existing page-only policy taichung_transport is unchanged.",
         "A stable HTTPS JPEG or HLS URL per camera exposed by the official viewer.",
         ["https://data.gov.tw/dataset/83750", "https://data.gov.tw/license"]),
    held("india_temple_live_darshan", "India - official temple trust live darshan streams",
         "https://shrikashivishwanath.org/online/live_darshan",
         "Pages exist but each trust's terms were not read; streams are YouTube embeds (outside HLS/snapshot).",
         "Terms read per trust and an official page per temple with its position.", []),
    held("israel_western_wall_cameras", "Western Wall (Kotel) live cameras", "https://thekotel.org/en/",
         "Partially verified: the camera page was not found (old URL 404) and no terms were located.",
         "The current official camera page and its terms.", ["https://thekotel.org/en/"]),
    held("seoul_topis", "Seoul TOPIS traffic CCTV", "https://topis.seoul.go.kr/",
         "Not verified (search summary only); the Open API is non-commercial and needs approval.",
         "Terms read on the TOPIS site and a decision on a single official map link.", []),
    held("wa_main_roads", "Main Roads Western Australia traffic cameras", "https://www.mainroads.wa.gov.au/",
         "Terms verified (no commercial reuse, so links only), but no camera list was found to link.",
         "An official camera list with per-camera pages and positions.",
         ["https://www.mainroads.wa.gov.au/disclaimer-copyright/"]),
    held("windy_webcams_api", "Windy Webcams API", "https://api.windy.com/webcams",
         "API key required; free-plan image URLs expire after 15 minutes and offsets stop at 1,000; the "
         "Professional plan is paid (9,990 EUR/year).",
         "A paid-plan decision and a server-side resolver; not suitable for a static catalogue.",
         ["https://api.windy.com/webcams/terms"]),
]:
    HELD.update(_entry)


ETIQUETTE = {
    "robots": "Collector ran in a fresh process after the RFC 9309 fix of webcam_fetch (class Robots). "
              "www.hko.gov.hk disallows /wxinfo/ (camera images) and /cis/: only /en/wxinfo/ts/ pages and "
              "/en/cis/stn.htm were requested, never an image. www.antarctica.gov.au disallows /search/ and "
              "/form-builder/ only; suthweather.saao.ac.za has no robots.txt.",
    "exploration": "Before the collector existed, 18 sequential exploration GETs through the same PoliteClient "
                   "(www.antarctica.gov.au 10, www.hko.gov.hk 5, www.saao.ac.za 2, suthweather.saao.ac.za 1), "
                   "re-checked with webcam_fetch.Robots after the fix: none disallowed, nothing deleted.",
    "image_checks": "None: every source of this family is page-only.",
}


# ---------------------------------------------------------------- helpers
def text_of(body):
    if isinstance(body, str):
        return body
    m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', body[:4000])
    for enc in ([m.group(1).decode("ascii", "ignore")] if m else []) + ["utf-8"]:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def page_item(provider, provider_id, name, lat, lng, country, region, page, observed_at, **extra):
    item = {"provider": provider, "provider_id": provider_id, "id": f"{provider}:{provider_id}", "name": name,
            "lat": round(lat, 6), "lng": round(lng, 6), "country": country, "region": region,
            "format": "official_page", "stream_url": None, "snapshot_url": None, "official_page": page,
            "rights_status": "official_page_only", "observed_at": observed_at, "health": {"status": "unverified"},
            "provider_in_service": None, "coordinate_role": "station_location"}
    item.update(extra)
    return item


# ---------------------------------------------------------------- HKO (pure)
def parse_hko_index(text):
    """[(code, site, view, page_url)]: site is the place name, view the parenthesised direction."""
    rows = []
    for number, code, label in re.findall(r'<span>(\d+[A-Z]?)\)</span><a name="([A-Z0-9]{2,4})"></a>(.*?)</div>', text, re.S):
        label = clean(re.sub(r"<br\s*/?>", " ", label)).replace("\xa0", " ").strip()
        site, _, view = label.partition("(")
        rows.append((code, site.strip(), view.rstrip(") ").strip(), urljoin(HKO_INDEX, f"webcam/{code}_photo.htm")))
    links = set(re.findall(r'webcam/([A-Z0-9]{2,4})_photo\.htm', text))
    if links != {r[0] for r in rows}:
        raise ValueError(f"HKO index entries and photo links differ: {sorted(links ^ {r[0] for r in rows})}")
    return rows


def dms_value(text):
    """'22°18'07"' or, for older stations, minutes only ('22°18'')."""
    m = re.fullmatch(r"\s*(\d+)°(\d+)'(?:(\d+(?:\.\d+)?)\")?\s*", clean(text))
    if not m:
        raise ValueError(f"Unreadable station coordinate {text!r}")
    d, mi, s = (float(x or 0) for x in m.groups())
    return d + mi / 60 + s / 3600


def parse_hko_stations(text):
    """{code: [(name, lat, lng, open)]} from the HKO station list (latitude N, longitude E in DMS)."""
    out = collections.defaultdict(list)
    for name, lat, lng in re.findall(r'<td class="td1_year_class">(.*?)</td>\s*<td class="td1_normal_class">(.*?)</td>\s*'
                                     r'<td class="td1_normal_class">(.*?)</td>', text, re.S):
        parts = [clean(p) for p in re.split(r"<br\s*/?>", name)]
        code = next((p.strip("()") for p in parts if re.fullmatch(r"\([A-Z0-9]{2,4}\)", p)), None)
        dates = next((p for p in parts if re.fullmatch(r"\(\d\d/\d\d/\d{4}(?: - \d\d/\d\d/\d{4})?\)", p)), "")
        if not code or not lat.strip():
            continue
        out[code].append((parts[0].rstrip("*").strip(), dms_value(lat), dms_value(lng), " - " not in dates))
    return dict(out)


def parse_hko_aws_map(script):
    """HKO's own camera -> weather-station mapping in wxphoto_e.js (cameras with weather data)."""
    listed = set(re.findall(r'stn == "([a-z0-9]{2,4})"', script.split("aws_stn = stn;", 1)[0]))
    remap = dict(re.findall(r'if \(stn == "([a-z0-9]{2,4})"\) \{ aws_stn = "([a-z0-9]{2,4})"; \}', script))
    return {code.upper(): remap.get(code, code).upper() for code in listed}


def parse_hko_photo_title(text):
    m = re.search(r"<h1>(.*?)</h1>", text, re.S)
    return clean(m.group(1)) if m else None


def hko_station_for(code, site, stations, aws_map):
    """(station code, (name, lat, lng), basis) or None. Only open stations; contradictory positions refuse."""
    def usable(station_code):
        rows = [r for r in stations.get(station_code, []) if r[3]]
        if not rows:
            return None
        if any(distance_m(rows[0][1], rows[0][2], r[1], r[2]) > 200 for r in rows[1:]):
            return None
        return rows[0]
    if code in aws_map and usable(aws_map[code]):
        return aws_map[code], usable(aws_map[code]), "HKO page script maps the camera to this weather station"
    if usable(code):
        return code, usable(code), "same code in the HKO station list"
    matches = {c for c, rows in stations.items() for r in rows if r[3] and r[0].lower() == site.lower()}
    if len(matches) == 1:
        c = next(iter(matches))
        if usable(c):
            return c, usable(c), "identical site name in the HKO station list"
    return None


def hko_items(index_text, stations_text, script_text, titles, observed_at):
    stations, aws_map = parse_hko_stations(stations_text), parse_hko_aws_map(script_text)
    items, left_out = [], []
    for code, site, view, page in parse_hko_index(index_text):
        found = hko_station_for(code, site, stations, aws_map)
        name = f"{site} ({view})" if view else site
        if not found:
            left_out.append({"provider_id": code, "name": name,
                             "reason": "no HKO-published position for this camera site (not a listed weather station)"})
            continue
        station, (station_name, lat, lng, _), basis = found
        title = titles.get(code)
        confirmed = bool(title and station_name.lower() in title.lower())
        items.append(page_item(
            "hong_kong_observatory_weather_photos", code, f"HKO weather photo: {name}", lat, lng, "HK", "Hong Kong",
            page, observed_at, source_page=HKO_INDEX, source_catalog=HKO_INDEX,
            coordinate_reference_system="unspecified_geographic", coordinate_source=HKO_STATIONS,
            coordinate_role="station_location" if confirmed else "associated_feature",
            coordinate_note=(f"Position of HKO station {station_name} ({station}); {basis}. "
                             + ("The photo page names this station as the camera site." if confirmed else
                                f"The photo page names another site ({title}), so the marker is only associated.")
                             + " Not a surveyed camera mount."),
            station_code=station, photo_page_title=title, view=view or None,
            station_confirmed_by_page_title=confirmed,
            link_scope="official_camera_page", operator="Hong Kong Observatory"))
    return items, left_out


# ---------------------------------------------------------------- AAD (pure)
def parse_aad_index(text):
    """[(slug, label)] of webcam pages in index order; the label is the shortest link text (the menu entry)."""
    labels = collections.OrderedDict()
    for href, label in re.findall(r"""href=["']/antarctic-operations/webcams/([a-z0-9-]+)/["'][^>]*>(.*?)</a>""", text, re.S):
        if not href.startswith("faq") and clean(label):
            labels.setdefault(href, []).append(clean(label))
    return [(href, min(names, key=len)) for href, names in labels.items()]


def parse_aad_station_slugs(text):
    """Station-page slugs linked from the AAD 'stations and field locations' overview."""
    return set(re.findall(r"""href=["']/antarctic-operations/stations-and-field-locations/([a-z0-9-]+)/["']""", text))


def parse_aad_station(text):
    """(lat, lng) from 'Location: … (−66.2822, 110.5266)' on an AAD station page."""
    m = re.search(r"<strong>Location:</strong>(.*?)</p>", html.unescape(text), re.S)
    if not m:
        return None
    dec = re.search(r"\(\s*([−-]?\d+\.\d+)°?\s*,\s*([−-]?\d+\.\d+)°?\s*\)", m.group(1))
    if not dec:
        return None
    lat, lng = (float(x.replace("−", "-")) for x in dec.groups())
    return (lat, lng) if -90 <= lat <= -60 and -180 <= lng <= 180 else None


def aad_items(index_text, stations_text, station_texts, observed_at):
    cams, station_slugs = parse_aad_index(index_text), parse_aad_station_slugs(stations_text or "")
    items, left_out = [], []
    for cam_slug, label in cams:
        page = urljoin(AAD_INDEX, cam_slug + "/")
        if cam_slug.startswith("rsv-"):
            left_out.append({"provider_id": cam_slug, "name": label, "reason": "camera on a moving vessel (no fixed position)"})
            continue
        position = parse_aad_station(station_texts[cam_slug]) if station_texts.get(cam_slug) else None
        if cam_slug not in station_slugs or not position:
            left_out.append({"provider_id": cam_slug, "name": label,
                             "reason": "not at a station with a published position (e.g. the Kingston krill aquarium)"})
            continue
        items.append(page_item(
            "aad_antarctic_webcams", cam_slug, f"{label} (Australian Antarctic Division)", position[0], position[1],
            "AQ", "Australian Antarctic Territory", page, observed_at, source_page=AAD_INDEX, source_catalog=AAD_INDEX,
            coordinate_reference_system="unspecified_geographic", coordinate_source=AAD_STATION.format(cam_slug),
            coordinate_note="Station position published on the AAD station page; not a surveyed camera mount.",
            link_scope="official_camera_page", operator="Australian Antarctic Division"))
    return items, left_out


# ---------------------------------------------------------------- SAAO (pure)
def parse_saao_site(text):
    """The 1.0-m telescope position: '20° 48´ 38.5” E; 32° 22´ 46” S'."""
    m = re.search(r"(\d+)°\s*(\d+)[´'′]\s*([\d.]+)[”\"″]\s*E;\s*(\d+)°\s*(\d+)[´'′]\s*([\d.]+)[”\"″]\s*S", html.unescape(text))
    if not m:
        raise ValueError("SAAO site position not found")
    e = [float(x) for x in m.groups()]
    return -(e[3] + e[4] / 60 + e[5] / 3600), e[0] + e[1] / 60 + e[2] / 3600


def parse_saao_live(text):
    """[(camera dir, clip URL as published)] in page order."""
    return re.findall(r'<source src="(https?://www\.saao\.ac\.za/webcams/([a-z0-9]+)/anim/latest_anim\.webm)"', text)


def parse_saao_weather(text):
    """[(label, image file)] of the all-sky images on the Sutherland weather page."""
    out = []
    for table in re.findall(r"<table.*?</table>", text, re.S):
        if "all-sky" not in table:
            continue
        labels = [clean(x) for x in re.findall(r"<font[^>]*>([^<]*all-sky[^<]*)</font>", table)]
        images = re.findall(r'<img src="([^"]+\.(?:jpe?g|JPE?G|png))"', table)
        out.extend(zip(labels, images))
    return out


def saao_items(live_text, site_text, weather_text, observed_at):
    lat, lng = parse_saao_site(site_text)
    items, seen = [], set()
    common = dict(source_page=SAAO_LIVE, source_catalog=SAAO_LIVE, coordinate_reference_system="unspecified_geographic",
                  coordinate_source=SAAO_SITE, location_group_id="south_africa_saao:sutherland",
                  coordinate_note="Coordinates of SAAO's 1.0-m telescope used to identify the observing station; "
                                  "individual webcam mounts are not located by this source.")
    for clip, cam in parse_saao_live(live_text):
        if cam in seen:
            continue
        seen.add(cam)
        extra = {"reported_clip_url": clip, "published_format": "webm_animation"} if clip.startswith("https://") else {
            "published_format": "webm_animation", "clip_note": "the page links this animation over http only; not kept"}
        items.append(page_item("south_africa_saao", cam, SAAO_NAMES.get(cam, f"SAAO webcam {cam}"), lat, lng, "ZA",
                               "Sutherland, Northern Cape", SAAO_LIVE, observed_at, link_scope="station_gallery",
                               **common, **extra))
    if weather_text:
        for label, image in parse_saao_weather(weather_text):
            pid = "allsky-" + slug(label.replace("all-sky image", ""))
            items.append(page_item("south_africa_saao", pid, f"Sutherland {label} (SAAO weather page)", lat, lng, "ZA",
                                   "Sutherland, Northern Cape", SAAO_WEATHER, observed_at,
                                   link_scope="station_weather_page", published_format="still_image",
                                   published_image_name=image, **common))
    return items


# ---------------------------------------------------------------- overlaps (offline, informative)
def overlap_report(items, catalog_path, radius=300.0):
    if not catalog_path or not Path(catalog_path).exists():
        return {"checked": False}
    rows = json.loads(Path(catalog_path).read_text(encoding="utf-8")).get("items", [])
    found = collections.defaultdict(list)
    for item in items:
        for row in rows:
            if row.get("provider") == item["provider"] or not isinstance(row.get("lat"), (int, float)):
                continue
            if abs(row["lat"] - item["lat"]) < 0.01 and abs(row["lng"] - item["lng"]) < 0.01:
                d = distance_m(item["lat"], item["lng"], row["lat"], row["lng"])
                if d <= radius:
                    found[item["id"]].append({"existing": row["id"], "provider": row.get("provider"),
                                              "name": row.get("name"), "distance_m": round(d, 1)})
    return {"checked": True, "radius_m": radius, "records_with_nearby_existing": len(found),
            "nearby_by_existing_provider": dict(collections.Counter(m["provider"] for v in found.values() for m in v)),
            "examples": {k: v[:2] for k, v in sorted(found.items())[:10]}}


# ---------------------------------------------------------------- acquisition / build
class Acquirer:
    def __init__(self, out):
        self.out, self.client, self.refused = Path(out), F.PoliteClient(delay=1.2), []

    def get(self, source, name, url):
        try:
            r = self.client.get(url, max_bytes=8 * 1024 * 1024)
        except F.Refused as e:
            self.refused.append({"source": source, "url": url, "host": urlsplit(url).hostname, "reason": str(e)})
            return None
        except OSError as e:
            self.refused.append({"source": source, "url": url, "host": urlsplit(url).hostname,
                                 "reason": f"{type(e).__name__}: {str(e)[:160]}"})
            return None
        if r["status"] != 200:
            self.refused.append({"source": source, "url": url, "host": urlsplit(url).hostname,
                                 "reason": f"HTTP {r['status']} (not saved)"})
            return None
        target = self.out / "raw" / source / name
        F.save_raw(target.parent, target.name, r)
        return r


def read_raw(out, source, name):
    path = Path(out) / "raw" / source / name
    if not path.exists():
        return None, None
    receipt = json.loads((path.parent / (path.name + ".receipt.json")).read_text(encoding="utf-8"))
    return text_of(path.read_bytes()), receipt


def acquire(out):
    a = Acquirer(out)
    src = "hong_kong_observatory_weather_photos"
    if a.get(src, "index_webcam.htm", HKO_INDEX):
        a.get(src, "stn.htm", HKO_STATIONS)
        a.get(src, "wxphoto_e.js", HKO_SCRIPT)
        for code, _, _, page in parse_hko_index(read_raw(out, src, "index_webcam.htm")[0]):
            a.get(src, f"photo/{code}_photo.htm", page)
    src = "aad_antarctic_webcams"
    if a.get(src, "webcams_index.html", AAD_INDEX) and a.get(src, "stations_index.html", AAD_STATIONS):
        stations = parse_aad_station_slugs(read_raw(out, src, "stations_index.html")[0])
        for cam_slug, _ in parse_aad_index(read_raw(out, src, "webcams_index.html")[0]):
            if cam_slug in stations:
                a.get(src, f"stations/{cam_slug}.html", AAD_STATION.format(cam_slug))
    src = "south_africa_saao"
    a.get(src, "saao-live.html", SAAO_LIVE)
    a.get(src, "sutherland.html", SAAO_SITE)
    a.get(src, "suthweather.html", SAAO_WEATHER)
    return a


def build(out, catalog=None, refused=()):
    out = Path(out)
    report = {"family": FAMILY, "generated_at": F.now(), "sources": [], "held": [], "hosts_refused": list(refused),
              "etiquette": ETIQUETTE}
    # HKO
    src = "hong_kong_observatory_weather_photos"
    index_text, receipt = read_raw(out, src, "index_webcam.htm")
    titles = {}
    for code, _, _, _ in parse_hko_index(index_text):
        photo, _ = read_raw(out, src, f"photo/{code}_photo.htm")
        titles[code] = parse_hko_photo_title(photo) if photo else None
    hko, hko_out = hko_items(index_text, read_raw(out, src, "stn.htm")[0], read_raw(out, src, "wxphoto_e.js")[0],
                             titles, receipt["observed_at"])
    F.write_catalog(out / f"{src}.json", [src], hko)
    report["sources"].append({
        "id": src, "country": "HK", "input_file": f"{src}.json", "records": {"viewable": 0, "page_only": len(hko)},
        "index_cameras": len(titles), "left_out": hko_out,
        "photo_pages_fetched": sum(1 for v in titles.values() if v),
        "robots": "robots.txt read: /wxinfo/ (image path) and /cis/ disallowed; /en/wxinfo/ and /en/cis/ pages fetched",
        "changes_from_register": ["34 photo pages on the index; only cameras at HKO weather stations with a published "
                                  "position are placed (station_location); the rest are left out."],
        "overlaps": overlap_report(hko, catalog)})
    # AAD
    src = "aad_antarctic_webcams"
    index_text, receipt = read_raw(out, src, "webcams_index.html")
    cams = parse_aad_index(index_text)
    stations = {s: read_raw(out, src, f"stations/{s}.html")[0] for s, _ in cams}
    aad, aad_out = aad_items(index_text, read_raw(out, src, "stations_index.html")[0], stations, receipt["observed_at"])
    F.write_catalog(out / f"{src}.json", [src], aad)
    report["sources"].append({
        "id": src, "country": "AQ", "input_file": f"{src}.json", "records": {"viewable": 0, "page_only": len(aad)},
        "left_out": aad_out, "robots": "robots.txt: Disallow /search/ and /form-builder/ only",
        "changes_from_register": ["The index now lists Casey, Davis, Mawson, RSV Nuyina and the krill cam (no "
                                  "Macquarie Island); the moving icebreaker and the Kingston aquarium have no "
                                  "published fixed position and are left out."],
        "overlaps": overlap_report(aad, catalog)})
    # SAAO
    src = "south_africa_saao"
    live_text, receipt = read_raw(out, src, "saao-live.html")
    saao = saao_items(live_text, read_raw(out, src, "sutherland.html")[0], read_raw(out, src, "suthweather.html")[0],
                      receipt["observed_at"])
    F.write_catalog(out / f"{src}.json", [src], saao, supersedes=[src])
    report["sources"].append({
        "id": src, "country": "ZA", "input_file": f"{src}.json", "records": {"viewable": 0, "page_only": len(saao)},
        "supersedes": [src], "provider_ids": [x["provider_id"] for x in saao],
        "robots": "www.saao.ac.za and suthweather.saao.ac.za robots.txt honoured by the client",
        "changes_from_register": [
            "The 'six images' are four camera title images (with their webm animations), one untitled image and the "
            "Sutherland weather overview; the camera set on the live page is unchanged (lcogt, domecam330, "
            "domecam190, solaris kept with their ids).",
            "Added the two all-sky cameras of the Sutherland weather page the live page now embeds "
            "(page host suthweather.saao.ac.za added to the policy).",
            "http-only .webm references dropped; https ones kept as reported_clip_url."],
        "overlaps": overlap_report(saao, catalog)})
    for pid, policy in {**POLICIES, **HELD}.items():
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{pid}.json").write_text(json.dumps({pid: policy}, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    report["held"] = [{"id": k, "reason": v["held_reason"]} for k, v in sorted(HELD.items())]
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--catalog", type=Path, help="current data/webcams.json, for the overlap report only")
    ap.add_argument("--offline", action="store_true", help="rebuild from saved raw responses; no network")
    args = ap.parse_args()
    refused = [] if args.offline else acquire(args.out).refused
    report = build(args.out, args.catalog, refused)
    previous = args.out / "reports" / f"{FAMILY}.json"
    if args.offline and previous.exists():
        report["hosts_refused"] = json.loads(previous.read_text(encoding="utf-8")).get("hosts_refused", [])
    report["sample_checks"] = "none: page-only sources get no media check"
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({s["id"]: s["records"] for s in report["sources"]}, ensure_ascii=False))
    print("held:", [h["id"] for h in report["held"]], "refused:", report["hosts_refused"])


if __name__ == "__main__":
    main()
