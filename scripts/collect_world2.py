#!/usr/bin/env python3
"""Collect the round-2 "world" webcam sources (Pacific, Antarctica, Africa, Middle East, South Asia) for Q-Globe.

Register: webcam-research/world-2.{md,json} (2026-11-14). Japan is handled by another family.

Viewable (snapshot), hand-placed at positions published by the operator or an agency table:
  noaa_gml_observatory_webcams  Mauna Loa, South Pole, Utqiagvik stills (public domain). The image folder
                                /webdata/ is disallowed by robots.txt: no build-time request, viewer fetch on tap.
  gemini_north_webcams          Gemini North cloud cameras (NOIRLab image policy, CC BY 4.0)
  gemini_south_cloud_cameras    Gemini South cloud and all-sky cameras (same policy)
  cfht_maunakea_webcams         CFHT Nana ao all-sky still (GNU FDL 1.3 notice shown) + the StarCam page link
Page links (official_page), positions from the operator's own pages/maps or an agency station table:
  kenya_aeroclub_webcams, india_temple_live_darshan_round2, iraq_karbala_shrine_live,
  sri_lanka_dalada_maligawa_live, namibia_nwr_okaukuejo, usap_antarctic_webcams,
  reunion_irt_viewsurf_webcams, maunakea_mkwc_other_observatory_cams
Everything else of the brief is written as a held policy with its reason (no records).

  python scripts/collect_world2.py --out <dir> [--reuse-raw]

--reuse-raw reads a page already saved under <dir>/raw/<source>/ (same URL, HTTP 200, with its receipt)
instead of requesting it again, and keeps an existing image-check file: re-runs cost no new requests.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as W  # noqa: E402

FAMILY = "world2"
REVIEWED_AT = "2026-11-14"
SLOW_HOSTS = {"www.gemini.edu": 10}  # robots.txt Crawl-delay

# ---------------------------------------------------------------- URLs
GML_PAGES = {"MLO": "https://gml.noaa.gov/obop/mlo/livecam/livecam.html",
             "SPO": "https://gml.noaa.gov/obop/spo/livecamera.html",
             "BRW": "https://gml.noaa.gov/obop/brw/livecamera.html"}
GML_SITES = "https://gml.noaa.gov/dv/site/"
GML_TERMS = "https://gml.noaa.gov/about/disclaimer.html"

GEMINI_CLOUD = "https://www.gemini.edu/observing/telescopes-and-sites/sites/cloud-cameras"
GEMINI_SITES = "https://www.gemini.edu/observing/telescopes-and-sites/sites"
GEMINI_GN = "https://www.gemini.edu/sciops/schedules/obsStatus/GN_Instrument.html"
GEMINI_GS = "https://www.gemini.edu/sciops/schedules/obsStatus/GS_Instrument.html"
GEMINI_GS_ALLSKY = GEMINI_CLOUD + "/gemini-south-all-sky-camera"
GEMINI_POLICY = "https://www.gemini.edu/node/14"
NOIRLAB_TERMS = "https://noirlab.edu/public/copyright/"
CC_BY = "https://creativecommons.org/licenses/by/4.0/"

CFHT_WEBCAMS = "https://www.cfht.hawaii.edu/en/gallery/webcams.php"
CFHT_NANAAO = "https://www.cfht.hawaii.edu/en/gallery/nanaao.php"
CFHT_STARCAM = "https://www.cfht.hawaii.edu/en/gallery/starcam.php"
CFHT_MANUAL = "https://www.cfht.hawaii.edu/Instruments/ObservatoryManual/CFHT_ObservatoryManual_(Sec_1).html"
GFDL = "https://www.gnu.org/licenses/fdl-1.3.html"

ACEA_INDEX = "https://webcams.aeroclubea.com/"
ACEA_MAP = "https://webcams.aeroclubea.com/map.html"
ACEA_KML = "https://www.google.com/maps/d/kml?mid=1-jKp3FFsfqZ7rqExMt3E2C6QT54&forcekml=1"
ACEA_MYMAP = "https://www.google.com/maps/d/viewer?mid=1-jKp3FFsfqZ7rqExMt3E2C6QT54"

AMBAJI_LIVE = "https://www.ambajitemple.in/live-darshan"
AMBAJI_CONTACT = "https://www.ambajitemple.in/contact-us"
MAHALAXMI_LIVE = "https://mahalakshmi-temple.com/live-darshan"
MAHALAXMI_REACH = "https://mahalakshmi-temple.com/how-to-reach"

ALKAFEEL_STREAM = "https://alkafeel.net/stream"
ALKAFEEL_APP = "https://alkafeel.net/js/app.64a7040e.js?3324f74e07618953d67f"
ALKAFEEL_CONTACT_JS = "https://alkafeel.net/js/contact.5f98b45b.js"
IMAM_HUSSAIN_LIVE = "https://imamhussain.org/arabic/live"

DALADA_LIVE = "https://sridaladamaligawa.lk/live/"
DALADA_CONTACT = "https://sridaladamaligawa.lk/contact/"

NWR_ARTICLE = "https://www.nwr.com.na/nwr-launches-live-waterhole-camera-in-etosha/"
NWR_RESORT = "https://www.nwr.com.na/resorts/okaukuejo-resort/"

USAP_PAGES = {"south-pole": ("https://www.usap.gov/videoclipsandmaps/spwebcam.cfm", "SPO", "South Pole Station"),
              "mcmurdo": ("https://www.usap.gov/videoclipsandmaps/mcmwebcam.cfm", "MCM", "McMurdo Station"),
              "palmer": ("https://www.usap.gov/videoclipsandmaps/palwebcam.cfm", "PSA", "Palmer Station")}
USAP_INDEX = "https://www.usap.gov/videoclipsandmaps/"

REUNION_INDEX = "https://www.reunion.fr/organisez/webcams/"

MKWC_INDEX = "http://mkwc.ifa.hawaii.edu/current/cams/"  # plain HTTP only (443 refused in research)


# ================================================================= small helpers (pure)
def text_of(fragment):
    fragment = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def decoded(body):
    return body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body


def coords(lat, lng, box=None):
    lat, lng = float(lat), float(lng)
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError("no usable coordinates")
    if box and not (box[0] <= lat <= box[1] and box[2] <= lng <= box[3]):
        raise ValueError(f"coordinates {lat},{lng} outside the expected area")
    return round(lat, 6), round(lng, 6)


def sexagesimal(value):
    """'-30:14:26.700' or '19:49:25.7016' -> decimal degrees."""
    sign = -1 if value.strip().startswith("-") else 1
    d, m, s = (float(x) for x in value.strip().lstrip("+-").split(":"))
    return sign * (d + m / 60 + s / 3600)


def item(provider, pid, name, lat, lng, country, region, role, fmt, observed_at, *, page, source_page, catalog,
         snapshot=None, coordinate_source=None, coordinate_note=None, crs="unspecified_geographic", **extra):
    record = {"provider": provider, "provider_id": pid, "id": f"{provider}:{pid}", "name": name, "lat": lat, "lng": lng,
              "country": country, "region": region, "coordinate_role": role, "format": fmt,
              "stream_url": None, "snapshot_url": snapshot if fmt == "snapshot" else None,
              "official_page": page, "source_page": source_page, "source_catalog": catalog,
              "rights_status": "official_public_feed" if fmt == "snapshot" else "official_page_only",
              "observed_at": observed_at, "health": {"status": "unverified"},
              "coordinate_reference_system": crs,
              "coordinate_source": coordinate_source, "coordinate_note": coordinate_note}
    record.update(extra)
    return {k: v for k, v in record.items() if v is not None or k in ("stream_url", "snapshot_url")}


# ================================================================= NOAA GML (pure)
def parse_gml_sites(doc, codes):
    """Rows of GML's site table: code -> (lat, lng, site name)."""
    doc, out = decoded(doc), {}
    for code in codes:
        m = re.search(r"(?s)<tr>\s*<td><a href='/dv/site/index\.php\?stacode=" + code + r"'>" + code +
                      r"</a></td>\s*<td>([^<]*)</td>\s*<td>[^<]*</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>", doc)
        if m:
            out[code] = (*coords(m.group(2), m.group(3)), m.group(1).strip())
    return out


def parse_gml_livecam(doc, page_url):
    """Live camera blocks of a GML observatory page (commented-out cameras are skipped): image URL, title, caption."""
    doc = re.sub(r"(?s)<!--.*?-->", "", decoded(doc))
    cams, seen = [], set()
    for m in re.finditer(r'(?is)<img[^>]+src="(/webdata/[a-z]+/webcam/[A-Za-z0-9_]+\.jpg)"[^>]*>', doc):
        src = m.group(1)
        if src in seen:
            continue
        seen.add(src)
        before, after = doc[max(0, m.start() - 600):m.start()], doc[m.end():m.end() + 900]
        heading = re.findall(r"(?is)<h2[^>]*>(.*?)</h2>", before)
        caption = re.search(r'(?is)class="caption[^"]*"[^>]*>(.*?)</div>', after)
        tail = re.search(r"(?is)</a>\s*(?:<br\s*/?>)?(.*?)</div>", after)
        alt = re.search(r'alt="([^"]*)"', m.group(0))
        text = text_of(caption.group(1)) if caption else (text_of(tail.group(1))[:300] if tail else None)
        cams.append({"cam": src.rsplit("/", 1)[1][:-4], "folder": src.split("/")[2], "image_url": urljoin(page_url, src),
                     "title": text_of(heading[-1]) if heading else None,
                     "caption": None if not text or "reduced in size" in text else text,
                     "alt": alt.group(1) if alt else None})
    return cams


GML_REGIONS = {"MLO": ("US", "Hawaii", "Mauna Loa Observatory"), "SPO": ("AQ", "Antarctica", "South Pole (ARO)"),
               "BRW": ("US", "Alaska", "Barrow Observatory, Utqiagvik")}


def gml_items(pages, sites, observed):
    """pages: code -> (page_url, html). Only cameras whose image folder is the page's own observatory are kept
    (the MLO page also shows the South Pole camera, kept once from the SPO page). mkcam sits on Maunakea
    (Submillimeter Array), not at Mauna Loa: no published position for it, left out."""
    items, left_out = [], []
    for code, (url, doc) in pages.items():
        lat, lng, site_name = sites[code]
        country, region, label = GML_REGIONS[code]
        for cam in parse_gml_livecam(doc, url):
            if cam["folder"] != code.lower():
                continue
            if cam["cam"] == "mkcam":
                left_out.append({"provider_id": "mlo:mkcam", "reason": "camera mounted at the Submillimeter Array on "
                                 "Maunakea (page text), not at Mauna Loa; no official position read for it"})
                continue
            title = cam["title"] or cam["caption"] or cam["alt"] or cam["cam"]
            name = f"{label} — {title}" if code != "SPO" else "South Pole — NOAA Atmospheric Research Observatory camera"
            items.append(item("noaa_gml_observatory_webcams", f"{code.lower()}:{cam['cam']}", name, lat, lng, country,
                              region, "station_location", "snapshot", observed[code], snapshot=cam["image_url"],
                              page=url, source_page=url, catalog=url,
                              coordinate_source=GML_SITES,
                              coordinate_note=f"NOAA GML site table position for {code} ({site_name}); the camera is on "
                                              "or beside the observatory, not a surveyed mount.",
                              caption=cam["caption"], minimum_refresh_seconds=900,
                              media_fetch="viewer_on_tap_only",
                              media_fetch_note="robots.txt disallows /webdata/: no build-time request or sample check"))
    return items, left_out


# ================================================================= Gemini (pure)
def parse_gemini_sites(doc):
    """'The Gemini South telescope ... at latitude -30:14:26.700 and longitude -70:44:12.096 in the WGS84 system'."""
    t, out = text_of(decoded(doc)), {}
    for site in ("South", "North"):
        m = re.search(r"Gemini " + site + r" telescope is situated[^.]*?at latitude ([-+0-9:.]+) and longitude "
                      r"([-+0-9:.]+) in the WGS84 system", t)
        if m:
            out[site] = coords(sexagesimal(m.group(1)), sexagesimal(m.group(2)))
    return out


def parse_gemini_status(doc, page_url):
    """Still images on a Gemini status page with the label row above each: [(label, url)] (commented-out
    images skipped). Video posters are the cameras' current stills."""
    doc = re.sub(r"(?s)<!--.*?-->", "", decoded(doc))
    found, seen = [], set()
    for m in re.finditer(r'(?is)<(?:img|video)\b[^>]*?(?:src|poster)="\.?/?((?:currentstill_|latestGS_|allsky)[A-Za-z_]*'
                         r'\.(?:png|jpg))"', doc):
        url = urljoin(page_url, m.group(1))
        if url in seen:
            continue
        seen.add(url)
        labels = re.findall(r"(?is)<td[^>]*>\s*([A-Za-z][A-Za-z -]{2,40}?Camera)\s*(?:</td>|<tr>)", doc[max(0, m.start() - 700):m.start()])
        found.append((labels[-1].strip() if labels else None, url))
    return found


GN_WANTED = {"currentstill_Hilo.png": "east", "currentstill_South.png": "south", "currentstill_West.png": "west",
             "currentstill_North.png": "north", "currentstill_Up.png": "up"}
GS_WANTED = {"latestGS_NE.jpg": "northeast", "latestGS_SW.jpg": "southwest"}


def gemini_items(gn_doc, gs_doc, allsky_doc, sites, observed):
    gn, gs = [], []
    for label, url in parse_gemini_status(gn_doc, GEMINI_GN):
        key = url.rsplit("/", 1)[1]
        if key in GN_WANTED:
            gn.append(item("gemini_north_webcams", GN_WANTED[key], f"Gemini North (Maunakea) — {label or key}",
                           *sites["North"], "US", "Hawaii", "station_location", "snapshot", observed["gn"], snapshot=url,
                           page=GEMINI_GN, source_page=GEMINI_CLOUD, catalog=GEMINI_GN, coordinate_source=GEMINI_SITES,
                           coordinate_note="Gemini North telescope position (WGS84) published on Gemini's Sites page; "
                                           "the cloud cameras are on the telescope site.", crs="WGS84",
                           minimum_refresh_seconds=300))
    for label, url in parse_gemini_status(gs_doc, GEMINI_GS):
        key = url.rsplit("/", 1)[1]
        if key in GS_WANTED:
            gs.append(item("gemini_south_cloud_cameras", GS_WANTED[key], f"Gemini South (Cerro Pachón) — {label or key}",
                           *sites["South"], "CL", "Coquimbo", "station_location", "snapshot", observed["gs"], snapshot=url,
                           page=GEMINI_GS, source_page=GEMINI_CLOUD, catalog=GEMINI_GS, coordinate_source=GEMINI_SITES,
                           coordinate_note="Gemini South telescope position (WGS84) published on Gemini's Sites page.",
                           crs="WGS84", minimum_refresh_seconds=300))
    m = re.search(r'<img[^>]+src="(https://www\.gemini\.edu/sciops/schedules/obsStatus/allsky\.png)"', decoded(allsky_doc))
    if m:
        gs.append(item("gemini_south_cloud_cameras", "allsky", "Gemini South (Cerro Pachón) — All Sky Camera",
                       *sites["South"], "CL", "Coquimbo", "station_location", "snapshot", observed["allsky"],
                       snapshot=m.group(1), page=GEMINI_GS_ALLSKY, source_page=GEMINI_CLOUD, catalog=GEMINI_GS_ALLSKY,
                       coordinate_source=GEMINI_SITES,
                       coordinate_note="Gemini South telescope position (WGS84) published on Gemini's Sites page.",
                       crs="WGS84", minimum_refresh_seconds=300))
    return gn, gs


# ================================================================= CFHT (pure)
GFDL_CLAUSE = re.compile(r"Copyright © Canada France Hawaii Telescope Corporation\. Permission is granted to copy, "
                         r"distribute and/or modify these images under the terms of the GNU Free Documentation License ?, "
                         r"Version 1\.3, or any later version, published by the Free Software Foundation\.")


def parse_cfht_position(doc):
    """CFHT observatory manual: 'at latitude +19 o 49' 41.86" and longitude 155 o 28' 18.00"' (west longitude)."""
    t = text_of(decoded(doc))
    m = re.search(r"latitude \+?(\d+) ?o (\d+)' ([\d.]+)\" and longitude (\d+) ?o (\d+)' ([\d.]+)\"", t)
    if not m:
        raise ValueError("CFHT position not found")
    lat = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600
    lng = -(int(m.group(4)) + int(m.group(5)) / 60 + float(m.group(6)) / 3600)  # Hawaii: west of Greenwich
    return coords(lat, lng, (18.5, 22.5, -161, -154))


def parse_cfht_nanaao(doc):
    """The Nana ao page: mosaic still URL (cache-busting query dropped) and the GFDL notice printed on the page."""
    doc = decoded(doc)
    m = re.search(r'<img src="(https://software\.cfht\.hawaii\.edu/webloop/nanaao\.jpg)(?:\?\d+)?" width=660px>', doc)
    notice = GFDL_CLAUSE.search(text_of(doc))
    if not m or not notice:
        raise ValueError("Nana ao still or its GFDL notice not found on the page")
    hours = re.search(r"operates between sunset and sunrise, Hawaii Standard Time", text_of(doc))
    return {"image_url": m.group(1), "notice": notice.group(0), "night_only": bool(hours)}


def parse_cfht_starcam(doc):
    doc = decoded(doc)
    m = re.search(r'href="(https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11})"', doc)
    if not m or not GFDL_CLAUSE.search(text_of(doc)):
        raise ValueError("StarCam stream link or notice not found")
    return m.group(1)


CFHT_NOTICE = ("Images Copyright © Canada France Hawaii Telescope Corporation. Permission is granted to copy, distribute "
               "and/or modify these images under the terms of the GNU Free Documentation License, Version 1.3, or any "
               "later version, published by the Free Software Foundation. A copy of the licence: " + GFDL)


def cfht_items(nanaao, starcam_url, position, observed):
    common = dict(coordinate_source=CFHT_MANUAL, coordinate_note="CFHT telescope position from the CFHT Observatory "
                  "Manual (section 1); the cameras are on the CFHT building.")
    night = ("Nānā ao operates between sunset and sunrise (Hawaii time); by day the image is from the last night."
             if nanaao["night_only"] else None)
    return [item("cfht_maunakea_webcams", "nanaao", "CFHT Nānā ao all-sky camera (mosaic), Maunakea", *position, "US",
                 "Hawaii", "station_location", "snapshot", observed["nanaao"], snapshot=nanaao["image_url"],
                 page=CFHT_NANAAO, source_page=CFHT_NANAAO, catalog=CFHT_NANAAO, minimum_refresh_seconds=60,
                 provider_notice=night, licence_notice_on_page=nanaao["notice"], **common),
            item("cfht_maunakea_webcams", "starcam", "CFHT-Asahi StarCam (4K live stream, western sky), Maunakea",
                 *position, "US", "Hawaii", "station_location", "official_page", observed["starcam"], page=CFHT_STARCAM,
                 source_page=CFHT_STARCAM, catalog=CFHT_WEBCAMS, stream_platform="YouTube", stream_page=starcam_url,
                 **common)]


# ================================================================= Aero Club of East Africa (pure)
def parse_acea_index(doc, base=ACEA_INDEX):
    """Camera cards of the club's index (HTML comments removed): page, image folder, title, altitude, direction."""
    doc = re.sub(r"(?s)<!--.*?-->", "", decoded(doc))
    cards = []
    for chunk in re.split(r'<div class="card"', doc)[1:]:
        page = re.search(r'<a href="([^"]+\.html)"', chunk)
        img = re.search(r'<img src="(https?://kenyawebcams?\.com/([A-Za-z0-9_]+)/pic/[A-Za-z0-9_]+\.jpg)"', chunk)
        title = re.search(r"(?s)<h6 class=\"card-title\">(.*?)</h6>", chunk)
        cells = [text_of(c) for c in re.findall(r"(?s)<td>(.*?)</td>", chunk)]
        if not page or not img:
            continue
        cards.append({"page": urljoin(base, page.group(1)), "folder": img.group(2), "image_url": img.group(1),
                      "title": re.sub(r"\s*\bNEW\b\s*$", "", text_of(title.group(1))).strip() if title else None,
                      "cells": cells})
    return cards


def parse_kml_points(doc):
    """Placemark name -> (lat, lng) from the club's My Maps KML (KML order is lng,lat)."""
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    root = ET.fromstring(doc if isinstance(doc, (bytes, bytearray)) else doc.encode("utf-8"))
    out = {}
    for pm in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
        name = re.sub(r"\s+", " ", (pm.findtext("k:name", default="", namespaces=ns) or "").replace("\xa0", " ")).strip()
        c = pm.find(".//k:Point/k:coordinates", ns)
        if name and c is not None and c.text:
            lng, lat = c.text.strip().split(",")[:2]
            out.setdefault(name.lower(), coords(lat, lng, (-5, 5.5, 33.5, 42.5)))
    return out


# Camera image folder -> placemark of the club's map (matched by site name; the map has 40 sites, several
# cameras per site). Cameras whose site is not on the map are left out (no published position).
ACEA_SITE = {
    "wilsoncam": "wilson", "wilsonsouth": "wilson", "ngongcam": "ngong hills", "orlycam2": "orly airpark",
    "machakoscam": "machakos", "tatu1": "tatu city", "tatu2": "tatu city", "tatu3": "tatu city", "tatu4": "tatu city",
    "brackenhurstn": "brakenhurst", "brackenhurstsnew": "brakenhurst", "karikicam2": "kariki",
    "nyerihk1": "nyeri north", "nyerihk2": "nyeri south", "soamescam": "soames", "olnaishucam": "ol naishu",
    "oldonyo": "ol donyo south", "oldonyo2": "ol donyo south", "oldonyo3": "ol donyo south", "maraniacam": "marania",
    "kopjecam1": "elsa kopje", "naivashacam2": "lake naivasha", "naivashacam2NE": "lake naivasha",
    "kinagop": "kinangop south", "eburu": "kinangop", "gilgilcam1": "gilgil", "gilgilcam2": "gilgil",
    "gilgilcam3": "gilgil", "gilgilcam4": "gilgil", "gilgilcam5": "gilgil", "turiwebcam": "turi",
    "siriacam": "mara siria", "finlayscam": "finlays", "elgoncam": "mount elgon",
    "kanzi33": "campi ya kanzi", "kanzi34": "campi ya kanzi", "kanzi35": "campi ya kanzi", "kanzi36": "campi ya kanzi",
    "kanzi37": "campi ya kanzi", "satao": "satao", "kilagunicam": "kilaguni", "lamucam": "lamu", "watamucam": "watamu",
    "watamucamne": "watamu", "vipingo": "vipingo ridge", "diani33": "diani", "chale33": "chale island"}
# Sites whose cameras stand at clearly different spots (altitudes 1,220-4,400 ft on one placemark).
ACEA_APPROXIMATE = {"campi ya kanzi"}
ACEA_REGIONS = {"NAIROBI": "Nairobi", "MT. KENYA": "Mt. Kenya", "RIFT VALLEY": "Rift Valley", "WESTERN": "Western",
                "CHYULU": "Tsavo/Chyulu", "TSAVO": "Tsavo/Chyulu", "MAASAI MARA": "Maasai Mara", "COAST": "Coast"}


def card_dms(cells):
    """'0°8'17" S 37°4'26" E' printed on a card -> (lat, lng), else None."""
    for c in cells:
        m = re.search(r"(\d+)°(\d+)'([\d.]+)\" ?([NS]) (\d+)°(\d+)'([\d.]+)\" ?([EW])", c)
        if m:
            lat = (int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600) * (-1 if m.group(4) == "S" else 1)
            lng = (int(m.group(5)) + int(m.group(6)) / 60 + float(m.group(7)) / 3600) * (-1 if m.group(8) == "W" else 1)
            return coords(lat, lng, (-5, 5.5, 33.5, 42.5))
    return None


def acea_items(cards, sites, observed):
    items, left_out, seen = [], [], set()
    for card in cards:
        folder = card["folder"]
        if folder in seen:
            continue
        seen.add(folder)
        title = card["title"] or ""
        m = re.match(r"^\s*([A-Z][A-Z .]+?)\s*-\s*(.+)$", title)
        region = ACEA_REGIONS.get(m.group(1).strip(), m.group(1).strip().title()) if m else None
        name = (m.group(2) if m else title).strip(" -,")
        position, role, source, note = card_dms(card["cells"]), "station_location", ACEA_INDEX, None
        if position:
            note = "Position printed on the camera's card in the club's camera list."
        elif folder in ACEA_SITE and ACEA_SITE[folder] in sites:
            position, source = sites[ACEA_SITE[folder]], ACEA_KML
            role = "approximate" if ACEA_SITE[folder] in ACEA_APPROXIMATE else "station_location"
            note = (f"Site placemark '{ACEA_SITE[folder]}' on the club's camera map (Google My Maps KML), matched by "
                    "site name" + ("; the conservancy's cameras stand at different altitudes, so the marker is the "
                                   "camp, not each camera." if role == "approximate" else "; not a surveyed mount."))
        if not position or not title:
            left_out.append({"provider_id": folder, "name": title or None,
                             "reason": "site not on the club's map and no position on the card" if title else "untitled card"})
            continue
        altitude = next((c for c in card["cells"] if re.search(r"[\d,]+\s*ftt?\b", c)), None)
        direction = next((c for c in card["cells"] if c != altitude and not re.search(r"\d+°\d+(?:\.\d+)?['’]", c)), None)
        items.append(item("kenya_aeroclub_webcams", folder, f"{name} — Aero Club of East Africa webcam", *position, "KE",
                          region or "Kenya", role, "official_page", observed, page=card["page"], source_page=ACEA_INDEX,
                          catalog=ACEA_INDEX, coordinate_source=source, coordinate_note=note, crs="EPSG:4326",
                          direction=direction, camera_altitude=altitude, link_scope="official_camera_page"))
    return items, left_out


# ================================================================= Reunion tourism board (pure)
def parse_reunion_index(doc):
    """Pins of the webcam map (name, lat, lon, post id) joined to the cards' page links by post id."""
    doc = decoded(doc)
    cfg = re.search(r'(?s)<script type="application/json" data-config>\s*(\{\s*"woody_config".*?)</script>', doc)
    if not cfg:
        raise ValueError("webcam map configuration not found")
    pins = json.loads(cfg.group(1))["woody_config"]["marker_model"]["pins"]
    links = {pid: htmllib.unescape(href) for pid, href in
             re.findall(r'data-postid="(\d+)"[^>]*>\s*<a class="card-link[^"]*" href="([^"]+)"', doc)}
    out = []
    for pin in pins:
        pid = str(pin["properties"]["post_id"])
        out.append({"post_id": pid, "name": htmllib.unescape(pin["name"]), "lat": pin["lat"], "lon": pin["lon"],
                    "page": links.get(pid)})
    return out


def reunion_items(pins, observed):
    items, left_out = [], []
    for pin in pins:
        page = pin["page"]
        if not page or urlsplit(page).hostname != "www.reunion.fr" or "/organisez/webcams/" not in page:
            left_out.append({"provider_id": pin["post_id"], "name": pin["name"], "reason": "no webcam page linked on the index"})
            continue
        slug = urlsplit(page).path.rstrip("/").rsplit("/", 1)[1]
        items.append(item("reunion_irt_viewsurf_webcams", slug, f"{pin['name']} (Île de La Réunion Tourisme)",
                          *coords(pin["lat"], pin["lon"], (-21.5, -20.8, 55.1, 55.9)), "RE", "La Réunion",
                          "associated_feature", "official_page", observed, page=page, source_page=REUNION_INDEX,
                          catalog=REUNION_INDEX, coordinate_source=REUNION_INDEX,
                          coordinate_note="Pin of this webcam on the tourism board's webcam map (index page); it marks "
                                          "the beach or site, not a surveyed mount.", crs="EPSG:4326",
                          tourism_post_id=pin["post_id"], link_scope="official_camera_page"))
    return items, left_out


# ================================================================= hand-placed pages: position extractors (pure)
def maps_embed_center(doc, place_hint):
    """Centre of a Google Maps embed (pb=...!2d<lng>!3d<lat>...!2s<place>) whose place name contains place_hint."""
    for m in re.finditer(r"maps/embed\?pb=([^\"'\s]+)", decoded(doc)):
        pb = htmllib.unescape(m.group(1))
        c = re.search(r"!2d(-?[0-9.]+)!3d(-?[0-9.]+)", pb)
        name = re.search(r"!2s([^!]+)", pb)
        if c and name and place_hint.lower() in name.group(1).replace("%20", " ").lower():
            return coords(c.group(2), c.group(1)), name.group(1).replace("%20", " ")
    raise ValueError(f"no map of {place_hint!r} on the page")


def maps_place(doc, place_hint):
    """Place coordinates of a Google Maps place link: /maps/place/<name>/...!3d<lat>!4d<lng>."""
    for m in re.finditer(r"/maps/place/([^/\"]+)/[^\"]*?!3d(-?[0-9.]+)!4d(-?[0-9.]+)", decoded(doc)):
        if place_hint.lower() in m.group(1).replace("+", " ").lower():
            return coords(m.group(2), m.group(3))
    raise ValueError(f"no map link for {place_hint!r}")


def dalada_position(doc):
    m = re.search(r"([0-9]{2}\.[0-9]+)° E, ([0-9]\.[0-9]+)° N", text_of(decoded(doc)))
    if not m:
        raise ValueError("no position on the contact page")
    return coords(m.group(2), m.group(1), (5.8, 10, 79.5, 82))


def vue_map_center(doc):
    m = re.search(r"center:\{lat:(-?[0-9.]+),lng:(-?[0-9.]+)\}", decoded(doc))
    if not m:
        raise ValueError("no map centre in the contact bundle")
    return coords(m.group(1), m.group(2))


def vue_route(doc, name):
    m = re.search(r'\{path:"(/[a-z]+)",name:"' + re.escape(name) + r'"', decoded(doc))
    if not m:
        raise ValueError(f"route {name!r} not found")
    return m.group(1)


def youtube_embed(doc):
    m = re.search(r'<iframe[^>]+src="https://www\.youtube\.com/embed/([A-Za-z0-9_-]{11}|live_stream\?channel=[A-Za-z0-9_-]+)',
                  decoded(doc))
    return m.group(1) if m else None


def page_title(doc):
    m = re.search(r"(?is)<title>(.*?)</title>", decoded(doc))
    return text_of(m.group(1)) if m else None


# ================================================================= policies
def viewable_policy(sid, name, url, catalog, terms, licence, licence_url, media_rights, note, attribution, hosts,
                    page_hosts, countries, evidence, formats=("snapshot",), refresh=None, **extra):
    source = {"id": sid, "name": name, "url": url, "catalog_url": catalog, "terms_url": terms,
              "metadata_license": licence, "license": licence, "license_url": licence_url, "media_rights": media_rights,
              "rights_note": note, "attribution": attribution, "rights_status": "official_public_feed",
              "allowed_hosts": list(hosts), "review_status": "reviewed_for_snapshot_and_reference_use",
              "reviewed_at": REVIEWED_AT, "evidence": evidence}
    if refresh:
        source["minimum_refresh_seconds"] = refresh
    source.update({k: v for k, v in extra.items() if k in ("provider_notice", "robots_note")})
    policy = {"source": source, "media_hosts": list(hosts), "page_hosts": list(page_hosts), "formats": list(formats),
              "countries": countries, "operator_hints": [], "coordinate_role": "station_location"}
    policy.update({k: v for k, v in extra.items() if k not in ("provider_notice", "robots_note")})
    return policy


def page_policy(sid, name, url, catalog, terms, licence, media_rights, note, attribution, page_hosts, countries, evidence,
                role="associated_feature", **extra):
    source = {"id": sid, "name": name, "url": url, "catalog_url": catalog, "terms_url": terms,
              "metadata_license": licence, "license": licence, "media_rights": media_rights, "rights_note": note,
              "attribution": attribution, "rights_status": "official_page_only", "allowed_hosts": [],
              "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT, "evidence": evidence}
    source.update({k: v for k, v in extra.items() if k in ("provider_notice", "robots_note")})
    policy = {"source": source, "media_hosts": [], "page_hosts": list(page_hosts), "formats": ["official_page"],
              "countries": countries, "operator_hints": [], "coordinate_role": role}
    policy.update({k: v for k, v in extra.items() if k not in ("provider_notice", "robots_note")})
    return policy


NOIRLAB_CLAUSE = ("'Unless specifically noted, the images, and videos distributed on the public NOIRLab website ... are "
                  "licensed under a Creative Commons Attribution 4.0 International License, and hence may on a "
                  "non-exclusive basis be reproduced without fee provided the credit is clear and visible.' Gemini's "
                  "Cloud Cameras page links its 'Image Usage Policy' (gemini.edu/node/14), which redirects to this "
                  "NOIRLab page (re-read 2026-11-14).")
NOIRLAB_NOTE = ("No use implying endorsement by NOIRLab; images with identifiable persons may not be used commercially "
                "(sky and summit cameras). The PNG stills are large (0.7-2.8 MB): load on tap, at most every 5 minutes. "
                "A one-line confirmation from NOIRLab that the policy covers the operational stills is still advisable.")


def policies():
    return {
        "noaa_gml_observatory_webcams": viewable_policy(
            "noaa_gml_observatory_webcams",
            "NOAA Global Monitoring Laboratory observatory webcams (Mauna Loa, South Pole, Utqiaġvik/Barrow)",
            GML_PAGES["MLO"], GML_PAGES["MLO"], GML_TERMS, "US Government work, public domain (17 USC 105)", GML_TERMS,
            "'The information on government servers are in the public domain, unless specifically annotated otherwise, "
            "and may be used freely by the public so long as you do not 1) claim it is your own ..., 2) use it in a "
            "manner that implies an endorsement or affiliation with NOAA, or 3) modify it in content and then present "
            "it as official government material.' (GML disclaimer, re-read 2026-11-14)",
            "No endorsement or affiliation implied. Images update every 15 minutes (page text); positions are the GML "
            "site-table positions of the three observatories.",
            "Image provided by NOAA Global Monitoring Laboratory, Boulder, Colorado, USA (https://gml.noaa.gov)",
            ["gml.noaa.gov"], ["gml.noaa.gov"], ["US", "AQ"],
            [GML_TERMS, GML_SITES, *GML_PAGES.values()], refresh=900,
            robots_note="gml.noaa.gov/robots.txt disallows /webdata/ (the image folder) for all agents: the build "
                        "must not request or sample these images; the viewer loads an image only when a user opens "
                        "the card (user-initiated view, as decided for PhenoCam in round 1). No sample check was made."),
        "gemini_north_webcams": viewable_policy(
            "gemini_north_webcams", "Gemini North (Maunakea) cloud cameras", GEMINI_CLOUD, GEMINI_GN, NOIRLAB_TERMS,
            "CC-BY-4.0", CC_BY, NOIRLAB_CLAUSE, NOIRLAB_NOTE,
            "International Gemini Observatory/NOIRLab/NSF/AURA (CC BY 4.0)", ["www.gemini.edu"], ["www.gemini.edu"],
            ["US"], [GEMINI_CLOUD, GEMINI_POLICY, NOIRLAB_TERMS, GEMINI_GN, GEMINI_SITES], refresh=300),
        "gemini_south_cloud_cameras": viewable_policy(
            "gemini_south_cloud_cameras", "Gemini South (Cerro Pachón) cloud and all-sky cameras", GEMINI_CLOUD,
            GEMINI_GS, NOIRLAB_TERMS, "CC-BY-4.0", CC_BY, NOIRLAB_CLAUSE, NOIRLAB_NOTE,
            "International Gemini Observatory/NOIRLab/NSF/AURA (CC BY 4.0)", ["www.gemini.edu"], ["www.gemini.edu"],
            ["CL"], [GEMINI_CLOUD, GEMINI_POLICY, NOIRLAB_TERMS, GEMINI_GS, GEMINI_GS_ALLSKY, GEMINI_SITES], refresh=300),
        "cfht_maunakea_webcams": viewable_policy(
            "cfht_maunakea_webcams", "Canada-France-Hawaii Telescope (CFHT) Nānā ao camera and StarCam, Maunakea",
            CFHT_WEBCAMS, CFHT_NANAAO, CFHT_NANAAO, "GFDL-1.3-or-later", GFDL,
            "'Nānā ao All-Sky Images Copyright © Canada France Hawaii Telescope Corporation. Permission is granted to "
            "copy, distribute and/or modify these images under the terms of the GNU Free Documentation License, "
            "Version 1.3, or any later version, published by the Free Software Foundation.' (Nānā ao page; the same "
            "notice covers the Webcam, CloudCam and StarCam pages, re-read 2026-11-14)",
            "GFDL: the copyright and licence notice must accompany every copy, so the card shows it as the provider "
            "notice with the licence link. The 4 dome webcams (image paths answered 404 in research) and the 2 "
            "CloudCams are not included in this round.",
            "Image © Canada-France-Hawaii Telescope Corporation, GNU FDL 1.3 (https://www.gnu.org/licenses/fdl-1.3.html)",
            ["software.cfht.hawaii.edu"], ["www.cfht.hawaii.edu"], ["US"],
            [CFHT_NANAAO, CFHT_WEBCAMS, CFHT_STARCAM, GFDL, CFHT_MANUAL], formats=("snapshot", "official_page"),
            refresh=60, provider_notice=CFHT_NOTICE),
        "kenya_aeroclub_webcams": page_policy(
            "kenya_aeroclub_webcams", "Aero Club of East Africa webcams (pilot weather cameras, Kenya)", ACEA_INDEX,
            ACEA_INDEX, ACEA_INDEX,
            "No licence stated (the site has only an 'as is' disclaimer); factual links to the club's camera pages",
            "No reuse terms for the images: page links only. Display would need the club's permission "
            "(webcams@aeroclubea.com), which would make about 117 cameras viewable.",
            "'The images provided are on an 'as is' and 'as available basis' with no warranty as to the accuracy, "
            "completeness and uninterrupted provision of the images.' Positions: the club's own camera map (KML).",
            "Aero Club of East Africa - webcams.aeroclubea.com", ["webcams.aeroclubea.com"], ["KE"],
            [ACEA_INDEX, ACEA_MAP, ACEA_KML], role="station_location", official_map_url=ACEA_MYMAP),
        "india_temple_live_darshan_round2": page_policy(
            "india_temple_live_darshan_round2", "India - official temple-trust live darshan pages (round 2)",
            AMBAJI_LIVE, AMBAJI_LIVE, "https://www.ambajitemple.in/terms-and-conditions",
            "No licence (trust copyright); factual links to the trusts' own live darshan pages",
            "The streams are the trusts' own YouTube lives with all rights reserved: links only.",
            "'© 2026 Shri Mahalaxmi Temple Trust, Mumbai. All rights reserved.' Positions from the maps on each trust's "
            "contact / how-to-reach page.",
            "Shri Arasuri Ambaji Mata Devasthan Trust; Shri Mahalaxmi Temple Trust, Mumbai",
            ["www.ambajitemple.in", "mahalakshmi-temple.com"], ["IN"],
            [AMBAJI_LIVE, AMBAJI_CONTACT, MAHALAXMI_LIVE, MAHALAXMI_REACH]),
        "iraq_karbala_shrine_live": page_policy(
            "iraq_karbala_shrine_live", "Al-Abbas Holy Shrine official live broadcast (Karbala)", "https://alkafeel.net/",
            ALKAFEEL_STREAM, "https://alkafeel.net/", "None stated; factual link to the shrine's own live page",
            "No terms or stream licence: link only.",
            "The live page is the site's 'live' route (/stream). Position: the map marker on the shrine's own contact "
            "page.", "Al-Abbas Holy Shrine (alkafeel.net)", ["alkafeel.net"], ["IQ"],
            ["https://alkafeel.net/", ALKAFEEL_STREAM, ALKAFEEL_CONTACT_JS], role="approximate"),
        "sri_lanka_dalada_maligawa_live": page_policy(
            "sri_lanka_dalada_maligawa_live", "Sri Dalada Maligawa (Temple of the Tooth) official live page",
            DALADA_LIVE, DALADA_LIVE, "https://sridaladamaligawa.lk/", "None (all rights reserved); factual link",
            "'© 2026 All Rights Reserved by Media Bureau of Sri Dalada Maligawa.' Link only.",
            "Position printed on the temple's contact page.", "Media Bureau of Sri Dalada Maligawa",
            ["sridaladamaligawa.lk"], ["LK"], [DALADA_LIVE, DALADA_CONTACT]),
        "namibia_nwr_okaukuejo": page_policy(
            "namibia_nwr_okaukuejo", "Namibia Wildlife Resorts - Okaukuejo waterhole live camera (Etosha)", NWR_ARTICLE,
            NWR_ARTICLE, NWR_ARTICLE, "Not stated; factual link to NWR's own page with the live stream",
            "YouTube stream of the state-owned NWR; no reuse licence: link only.",
            "The NWR page embeds the live waterhole stream. Position: Okaukuejo Camp on the map link of NWR's resort page.",
            "Namibia Wildlife Resorts (NWR)", ["www.nwr.com.na"], ["NA"], [NWR_ARTICLE, NWR_RESORT]),
        "usap_antarctic_webcams": page_policy(
            "usap_antarctic_webcams", "US Antarctic Program station webcams (South Pole, McMurdo, Palmer)", USAP_INDEX,
            USAP_INDEX, USAP_INDEX, "No rights statement on the webcam pages; factual links to the station pages",
            "Images come from a robots-disallowed endpoint (/components/) and are taken by the NSF support contractor, "
            "so public-domain status is not established: station page links only.",
            "Positions: NOAA GML site table (official agency station table) for the three stations.",
            "U.S. Antarctic Program / National Science Foundation", ["www.usap.gov"], ["AQ"],
            [*(v[0] for v in USAP_PAGES.values()), GML_SITES], role="station_location",
            robots_note="www.usap.gov/robots.txt disallows /components/ (the image endpoint): pages only."),
        "reunion_irt_viewsurf_webcams": page_policy(
            "reunion_irt_viewsurf_webcams", "Île de La Réunion Tourisme webcams (Viewsurf panoramas)", REUNION_INDEX,
            REUNION_INDEX, REUNION_INDEX, "Not stated; factual links to the tourism board's webcam pages",
            "Cameras supplied by a commercial provider (Viewsurf); no reuse licence: page links only.",
            "Positions are the pins of the tourism board's own webcam map on the index page.",
            "Île de La Réunion Tourisme / Viewsurf", ["www.reunion.fr"], ["RE"], [REUNION_INDEX]),
        "maunakea_mkwc_other_observatory_cams": page_policy(
            "maunakea_mkwc_other_observatory_cams", "Maunakea Weather Center summit webcam index (UH Hilo)", MKWC_INDEX,
            MKWC_INDEX, "https://keckobservatory.org/media/cosmic-cams/",
            "No open licence for the indexed cameras (Keck: all rights reserved; NAOJ: contract for sold products)",
            "One link to the index page only; no camera image is used.",
            "The host serves plain HTTP only (HTTPS refused in research): the card marks the link as unencrypted. "
            "Linked as 'Maunakea Weather Center Camera Compilation' from Gemini's Cloud Cameras page (read 2026-11-14).",
            "Maunakea Weather Center (UH Hilo) and the operating observatories", ["mkwc.ifa.hawaii.edu"], ["US"],
            [MKWC_INDEX, GEMINI_CLOUD], role="approximate"),
    }


def held(sid, name, url, reason, until, evidence):
    return {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
            "source": {"id": sid, "name": name, "url": url}, "reviewed_at": REVIEWED_AT}


HELD = {
    "israel_western_wall_cameras": held(
        "israel_western_wall_cameras", "Western Wall Heritage Foundation live cameras",
        "https://thekotel.org/en/connect-remotely-to-the-western-wall/#live",
        "Page found (re-read 2026-11-14): the three camera URLs (western-wall-cameras, cameras-prayer-plaza, "
        "camera-wilsons-arch) now redirect to one live page with three pop-up players (The Western Wall, Prayer Plaza, "
        "Wilson's Arch). No position is published on the foundation's pages read (live, directions, visitor centre); "
        "the register's 31.7767,35.2345 cites no source.",
        "an official position (operator or agency), or the coordinator accepting the register position as approximate",
        ["https://thekotel.org/en/connect-remotely-to-the-western-wall/",
         "https://thekotel.org/en/visitor_information/directions/"]),
    "brazil_transalvador_cameras": held(
        "brazil_transalvador_cameras", "Transalvador live traffic cameras portal (Salvador, BA)",
        "https://cameras-transalvador.salvador.ba.gov.br/",
        "Portal and terms answer, but no position: the camera list loads only after a Cloudflare Turnstile check "
        "(not bypassed), and neither the portal, its script nor the agency home page publishes a map or coordinates "
        "for the city-level link.", "an official position for a city-level marker (or a public camera list)",
        ["https://cameras-transalvador.salvador.ba.gov.br/termos.html", "https://transalvador.salvador.ba.gov.br/"]),
    "kz_shymbulak_webcams": held(
        "kz_shymbulak_webcams", "Shymbulak Mountain Resort webcams (Almaty)", "https://shymbulak.com/en/webcams/",
        "Page answers (script-rendered shell) but no official position was read; the register's 43.128,77.081 is "
        "marked 'to be confirmed' and cites no source.", "an official resort position", ["https://shymbulak.com/en/webcams/"]),
    "macau_dsat_realtime_cameras": held(
        "macau_dsat_realtime_cameras", "DSAT Macau real-time road condition cameras",
        "https://www.dsat.gov.mo/dsat/realtime.aspx",
        "Index re-read 2026-11-14: 111 cameras grouped by district, 'All rights reserved', no coordinates; the DSAT "
        "contact page publishes no position, so even the city-level link has no official position.",
        "an official position (camera list with coordinates, or an agency position for a city-level marker)",
        ["https://www.dsat.gov.mo/dsat/realtime.aspx", "https://www.dsat.gov.mo/dsat/subpage.aspx?a_id=1614843871"]),
    "ovpf_ipgp_piton_fournaise": held(
        "ovpf_ipgp_piton_fournaise", "OVPF-IPGP Piton de la Fournaise observatory cameras",
        "https://www.ipgp.fr/volcanoweb/reunion/html_static_webcam/cameras-ovpf.html",
        "IPGP's legal notice allows non-commercial reuse only; commercial use needs a public-information reuse licence "
        "(register: ask operator).", "an IPGP reuse licence (same request as OVSG/OVSM)", ["https://www.ipgp.fr/mentions-legales/"]),
    "noirlab_chile_sky_cameras": held(
        "noirlab_chile_sky_cameras", "NOIRLab CTIO / SOAR sky and exterior cameras",
        "https://noirlab.edu/science/observing-noirlab/weather-webcams",
        "CC BY 4.0 covers images 'distributed on the public NOIRLab website'; these science-site webcams need NOIRLab's "
        "confirmation (register: ask operator); interior dome cameras excluded (identifiable staff).",
        "NOIRLab confirmation that the image policy covers the CTIO/SOAR webcams", ["https://noirlab.edu/public/copyright/"]),
    "lco_camera_view": held(
        "lco_camera_view", "Las Cumbres Observatory camera views", "https://lco.global/camera/",
        "LCO images are CC BY-NC 2.0; commercial use only by explicit arrangement (image_use@lco.global).",
        "LCO's arrangement for a paid app", ["https://lco.global/gallery/image/5/"]),
    "sanparks_webcams": held(
        "sanparks_webcams", "SANParks rest-camp webcams", "https://www.sanparks.org/travel/webcams/overview",
        "Terms reserve all reproduction and invite permission requests 'including linking': ask before linking.",
        "SANParks' permission to link the webcam pages", ["https://www.sanparks.org/legal/terms-conditions"]),
    "africam_wildlife_cams": held(
        "africam_wildlife_cams", "Africam wildlife cameras", "https://africam.com/",
        "Terms forbid deep-linking to its video content and any automated or manual monitoring without written permission.",
        "Africam's written permission", ["https://africam.com/terms-of-service/"]),
    "cctv_livechina_scenic_streams": held(
        "cctv_livechina_scenic_streams", "CCTV 直播中国 scenic live streams", "https://livechina.cctv.com/",
        "CCTV.com forbids reposting or even linking its content without authorisation (未经本网授权…不得转载、链接…).",
        "CCTV.com's written authorisation", ["https://www.cctv.com/special/guanyunew/gongsijianjie/index.shtml#wzsm"]),
    "kz_kaztoll_live_broadcasts": held(
        "kz_kaztoll_live_broadcasts", "KazToll toll-plaza live views", "https://kaztoll.kz/",
        "No usable list: the 74 views open in a home-page dialog fed by /next-api/, which robots.txt disallows; no "
        "per-camera URL or licence.", "a public camera list (or per-camera pages) allowed by robots.txt", ["https://kaztoll.kz/"]),
    "indonesia_magma_volcano_cctv": held(
        "indonesia_magma_volcano_cctv", "MAGMA Indonesia volcano CCTV", "https://magma.esdm.go.id/v1/gunung-api/cctv",
        "robots.txt is 'Disallow: /' for all agents: no listing or probing allowed; no usable list.",
        "robots.txt allowing the CCTV list (or an official open list)", ["https://magma.esdm.go.id/robots.txt"]),
    "iran_141_road_cameras": held(
        "iran_141_road_cameras", "141.ir road cameras", "https://141.ir/",
        "No usable list: the camera data comes from /api/, which robots.txt disallows; no terms found; sanctions and "
        "legal constraints to check before even linking.", "a robots-allowed list and a legal/sanctions review",
        ["https://141.ir/robots.txt"]),
}
ALREADY_HELD = {"explore_org_africa": "explore_org_livecams (held: no list; terms allow deep links but not automated "
                                      "harvesting; only a hand-made list is possible)"}


# ================================================================= network run
class Reader:
    """Polite reads (robots first, HTTPS, refusals raise). With reuse, a page saved under raw/ for the same URL
    (HTTP 200, with its receipt) is read from disk instead of being requested again."""

    def __init__(self, out, reuse=False):
        self.out, self.reuse = Path(out), reuse
        self.client = W.PoliteClient()
        self.slow = {host: W.PoliteClient(delay=delay) for host, delay in SLOW_HOSTS.items()}
        self.reads = []

    def client_for(self, url):
        return self.slow.get(urlsplit(url).hostname, self.client)

    def get(self, source, url, name, max_bytes=4_000_000, partial=False):
        folder = self.out / "raw" / source
        path, receipt_path = folder / name, folder / (name + ".receipt.json")
        if self.reuse and path.exists() and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("url") == url and receipt.get("status") == 200:
                self.reads.append({"source": source, "url": url, "reused": True})
                return path.read_bytes(), receipt
        client = self.client_for(url)
        if urlsplit(url).scheme != "https":
            raise W.Refused(f"not HTTPS: {url}")
        if not client.allowed(url):
            raise W.Refused(f"robots.txt disallows {url}")
        r = client._open(url, max_bytes)  # sequential, spaced, robots-checked redirects (webcam_fetch)
        if r["status"] in (401, 403, 407, 429, 451) or r["status"] >= 500:
            raise W.Refused(f"HTTP {r['status']} for {url}")
        if r["status"] != 200:
            raise ValueError(f"HTTP {r['status']} for {url}")
        if r["truncated"] and not partial:
            raise W.Refused(f"response over {max_bytes} bytes: {url}")
        receipt = W.save_raw(folder, name, r)
        self.reads.append({"source": source, "url": url, "reused": False, "status": r["status"]})
        return r["body"], receipt

    def check_image(self, out, source, url, record_id, hosts):
        path = out / "checks" / f"{source}.snapshot.json"
        if self.reuse and path.exists():
            events = json.loads(path.read_text(encoding="utf-8"))
            if events and events[0].get("url") == url:
                return events[0]
        event = self.client_for(url).check_image(url, source, record_id, hosts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([event], ensure_ascii=False, indent=1), encoding="utf-8")
        return event

    def robots_allows(self, url):
        return self.client_for(url).allowed(url)


def run(out, reuse=False):
    out = Path(out)
    rd = Reader(out, reuse)
    pols = policies()
    report = {"family": FAMILY, "sources": [], "held": [], "already_held": ALREADY_HELD, "hosts_refused": []}

    def write_policy(source, entry):
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{source}.json").write_text(json.dumps({source: entry}, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")

    def hold(source, entry, host=None):
        write_policy(source, entry)
        report["held"].append({"id": source, "reason": entry["held_reason"]})
        if host:
            report["hosts_refused"].append({"source": source, "host": host, "reason": entry["held_reason"][:160]})
        print(source, "HELD")

    def integrate(source, items, country, check=None, left_out=(), notes=(), robots=None):
        if not items:
            raise ValueError("no usable records")
        W.write_catalog(out / f"{source}.json", [source], items)
        write_policy(source, pols[source])
        viewable = sum(1 for i in items if i["format"] == "snapshot")
        entry = {"id": source, "status": "integrated", "countries": sorted({i["country"] for i in items}),
                 "records": {"viewable": viewable, "page_only": len(items) - viewable}, "input_file": f"{source}.json",
                 "policy_file": f"policies/{source}.json", "check": check, "left_out": list(left_out),
                 "notes": list(notes), "robots": robots}
        report["sources"].append(entry)
        print(source, entry["records"], "left out", len(left_out))

    def attempt(sources, fn):
        try:
            fn()
        except (W.Refused, OSError, ValueError, KeyError) as e:
            host = None
            if isinstance(e, W.Refused):
                m = re.search(r"https://([^/\s]+)", str(e))
                host = m.group(1) if m else None
            for source in sources:
                if any(s["id"] == source for s in report["sources"]):
                    continue
                hold(source, held(source, pols[source]["source"]["name"], pols[source]["source"]["url"],
                                  f"list, page or position not usable now: {str(e)[:200]}", "the pages answer again",
                                  pols[source]["source"]["evidence"]), host=host)

    def short_check(event):
        return {k: event.get(k) for k in ("record_id", "url", "status", "http_status", "signature", "content_type",
                                          "bytes_read", "inconclusive_reason")}

    # ---- NOAA GML
    def noaa():
        sites_doc, sites_r = rd.get("noaa_gml_observatory_webcams", GML_SITES, "gml_sites.html")
        rd.get("noaa_gml_observatory_webcams", GML_TERMS, "gml_disclaimer.html")
        sites = parse_gml_sites(sites_doc, ["MLO", "SPO", "BRW"])
        pages, observed = {}, {}
        for code, url in GML_PAGES.items():
            name = {"MLO": "mlo_livecam.html", "SPO": "spo_livecamera.html", "BRW": "brw_livecamera.html"}[code]
            body, receipt = rd.get("noaa_gml_observatory_webcams", url, name)
            pages[code], observed[code] = (url, body), receipt["observed_at"]
        items, left_out = gml_items(pages, sites, observed)
        blocked = [i["snapshot_url"] for i in items if not rd.robots_allows(i["snapshot_url"])]
        if len(blocked) != len(items):
            raise ValueError("robots.txt status of the image folder changed: review the policy before integrating")
        integrate("noaa_gml_observatory_webcams", items, "US",
                  check={"status": "not_checked", "reason": "robots.txt disallows /webdata/ (verified for all "
                                                            f"{len(items)} image URLs); viewer fetch on tap only"},
                  left_out=left_out + [{"provider_id": "mlo:konacam, mlo:towercam", "reason": "commented out on the MLO "
                                        "page (not shown any more)"}],
                  notes=["Register said 13 (MLO 7): konacam and towercam are commented out on the page and mkcam is on "
                         "Maunakea, so MLO has 4; SPO 1; BRW 5.",
                         "Positions: GML site table (MLO 19.536,-155.576; SPO -89.98,-24.8; BRW 71.323,-156.611)."],
                  robots="gml.noaa.gov: /webdata/ disallowed (images); /obop/ and /dv/ pages allowed")

    # ---- Gemini
    def gemini():
        sites_doc, _ = rd.get("gemini_north_webcams", GEMINI_SITES, "gemini_sites.html")
        rd.get("gemini_north_webcams", GEMINI_CLOUD, "gemini_cloud_cameras.html")
        rd.get("gemini_north_webcams", GEMINI_POLICY, "gemini_image_usage_policy.html")
        gn_doc, gn_r = rd.get("gemini_north_webcams", GEMINI_GN, "GN_Instrument.html")
        gs_doc, gs_r = rd.get("gemini_south_cloud_cameras", GEMINI_GS, "GS_Instrument.html")
        allsky_doc, allsky_r = rd.get("gemini_south_cloud_cameras", GEMINI_GS_ALLSKY, "gemini_south_all_sky_camera.html")
        sites = parse_gemini_sites(sites_doc)
        gn, gs = gemini_items(gn_doc, gs_doc, allsky_doc, sites,
                              {"gn": gn_r["observed_at"], "gs": gs_r["observed_at"], "allsky": allsky_r["observed_at"]})
        for source, items, sample in (("gemini_north_webcams", gn, "north"), ("gemini_south_cloud_cameras", gs, "northeast")):
            rec = next(i for i in items if i["provider_id"] == sample)
            event = rd.check_image(out, source, rec["snapshot_url"], rec["id"], {"www.gemini.edu"})
            integrate(source, items, None, check=short_check(event),
                      notes=["Positions: WGS84 telescope coordinates on Gemini's Sites page.",
                             "Gemini South: the status page's all-sky image is commented out; the all-sky record "
                             "links the 'Gemini South All Sky Camera' page, which shows the same still."]
                      if source == "gemini_south_cloud_cameras" else
                      ["Positions: WGS84 telescope coordinates on Gemini's Sites page; the 'East' camera is the "
                       "currentstill_Hilo.png still."],
                      robots="www.gemini.edu: Crawl-delay 10 honoured; /sciops/ and /observing/ allowed")

    # ---- CFHT
    def cfht():
        rd.get("cfht_maunakea_webcams", CFHT_WEBCAMS, "cfht_webcams.html")
        nanaao_doc, n_r = rd.get("cfht_maunakea_webcams", CFHT_NANAAO, "cfht_nanaao.html")
        star_doc, s_r = rd.get("cfht_maunakea_webcams", CFHT_STARCAM, "cfht_starcam.html")
        manual_doc, _ = rd.get("cfht_maunakea_webcams", CFHT_MANUAL, "cfht_manual_sec1.html")
        items = cfht_items(parse_cfht_nanaao(nanaao_doc), parse_cfht_starcam(star_doc), parse_cfht_position(manual_doc),
                           {"nanaao": n_r["observed_at"], "starcam": s_r["observed_at"]})
        rec = items[0]
        event = rd.check_image(out, "cfht_maunakea_webcams", rec["snapshot_url"], rec["id"], {"software.cfht.hawaii.edu"})
        integrate("cfht_maunakea_webcams", items, "US", check=short_check(event),
                  notes=["Viewable record is the Nānā ao mosaic still shown on the Nānā ao page "
                         "(software.cfht.hawaii.edu/webloop/nanaao.jpg), whose GFDL notice is printed on that page; the "
                         "register's www.cfht.hawaii.edu/images/webcam/nanaao.jpg is not referenced by any page read.",
                         "Full GFDL notice in source.provider_notice + license_url; StarCam (YouTube) is a page link.",
                         "Not added: 2 CloudCams (same GFDL notice) and 4 dome webcams (404 in research)."],
                  robots="www.cfht.hawaii.edu: /~asiva/images/, /cgi-bin/ disallowed only")

    # ---- Kenya
    def kenya():
        index_doc, i_r = rd.get("kenya_aeroclub_webcams", ACEA_INDEX, "aeroclub_index.html")
        rd.get("kenya_aeroclub_webcams", ACEA_MAP, "aeroclub_map.html")
        kml_doc, _ = rd.get("kenya_aeroclub_webcams", ACEA_KML, "aeroclub_sites.kml")
        cards = parse_acea_index(index_doc)
        items, left_out = acea_items(cards, parse_kml_points(kml_doc), i_r["observed_at"])
        sample = items[0]["official_page"]
        rd.get("kenya_aeroclub_webcams", sample, "sample_camera_page.html", max_bytes=65536, partial=True)
        integrate("kenya_aeroclub_webcams", items, "KE", left_out=left_out,
                  notes=[f"Index lists {len(cards)} cameras; {len(items)} placed (KML site matched by name, or the "
                         f"position printed on the card); {len(left_out)} left out without a published position.",
                         "Tatu City cards print an invalid position (36°65'): the KML site is used.",
                         f"One camera page sampled ({sample}): answers 200."],
                  robots="webcams.aeroclubea.com: no robots.txt; google.com allows /maps/d/ (KML)")

    # ---- India temples
    def temples():
        a_doc, a_r = rd.get("india_temple_live_darshan_round2", AMBAJI_LIVE, "ambaji_live_darshan.html", 65536, True)
        ac_doc, _ = rd.get("india_temple_live_darshan_round2", AMBAJI_CONTACT, "ambaji_contact.html")
        m_doc, m_r = rd.get("india_temple_live_darshan_round2", MAHALAXMI_LIVE, "mahalakshmi_live_darshan.html", 65536, True)
        mr_doc, _ = rd.get("india_temple_live_darshan_round2", MAHALAXMI_REACH, "mahalakshmi_how_to_reach.html")
        if not youtube_embed(a_doc) or not youtube_embed(m_doc):
            raise ValueError("live darshan embed missing")
        gabbar, gabbar_name = maps_embed_center(ac_doc, "Gabbar")
        temple, temple_name = maps_embed_center(mr_doc, "Mahalakshmi")
        items = [
            item("india_temple_live_darshan_round2", "ambaji-gabbar-jyot", "Ambaji — Gabbar Jyot live darshan (official)",
                 *gabbar, "IN", "Gujarat", "associated_feature", "official_page", a_r["observed_at"], page=AMBAJI_LIVE,
                 source_page=AMBAJI_LIVE, catalog=AMBAJI_LIVE, coordinate_source=AMBAJI_CONTACT,
                 coordinate_note=f"Centre of the trust's embedded map of '{gabbar_name}' (the live stream shows the "
                                 "Gabbar jyot) on its contact page.", crs="EPSG:4326", stream_platform="YouTube"),
            item("india_temple_live_darshan_round2", "mahalaxmi-mumbai", "Shri Mahalakshmi Temple, Mumbai — live darshan",
                 *temple, "IN", "Maharashtra", "associated_feature", "official_page", m_r["observed_at"],
                 page=MAHALAXMI_LIVE, source_page=MAHALAXMI_LIVE, catalog=MAHALAXMI_LIVE,
                 coordinate_source=MAHALAXMI_REACH,
                 coordinate_note=f"Centre of the trust's embedded map of '{temple_name}' on its How to Reach page.",
                 crs="EPSG:4326", stream_platform="YouTube")]
        integrate("india_temple_live_darshan_round2", items, "IN",
                  left_out=[{"provider_id": "mayapur-tv", "name": "Mayapur TV (ISKCON Mayapur)",
                             "reason": "page answers, but no official position read (register value from OSM/Wikidata)"}],
                  notes=["Ambaji's live darshan is the Gabbar jyot stream: placed at the trust's Gabbar Tirtha map."],
                  robots="ambajitemple.in and mahalakshmi-temple.com allow all")

    # ---- Karbala
    def karbala():
        rd.get("iraq_karbala_shrine_live", IMAM_HUSSAIN_LIVE, "imamhussain_live.html", 65536, True)
        rd.get("iraq_karbala_shrine_live", "https://imamhussain.org/arabic/contact", "imamhussain_contact.html")
        app_doc, _ = rd.get("iraq_karbala_shrine_live", ALKAFEEL_APP, "alkafeel_app.js")
        contact_doc, _ = rd.get("iraq_karbala_shrine_live", ALKAFEEL_CONTACT_JS, "alkafeel_contact.js")
        _, s_r = rd.get("iraq_karbala_shrine_live", ALKAFEEL_STREAM, "alkafeel_stream.html", 65536, True)
        if vue_route(app_doc, "live") != "/stream":
            raise ValueError("live route moved")
        position = coords(*vue_map_center(contact_doc), box=(32.55, 32.68, 43.95, 44.1))
        items = [item("iraq_karbala_shrine_live", "al-abbas-shrine", "Al-Abbas Holy Shrine, Karbala — live broadcast",
                      *position, "IQ", "Karbala", "approximate", "official_page", s_r["observed_at"], page=ALKAFEEL_STREAM,
                      source_page="https://alkafeel.net/", catalog=ALKAFEEL_STREAM, coordinate_source=ALKAFEEL_CONTACT_JS,
                      coordinate_note="Map marker on the shrine's own contact page (alkafeel.net/contact); it may mark the "
                                      "shrine's office rather than the shrine itself.", crs="EPSG:4326")]
        integrate("iraq_karbala_shrine_live", items, "IQ",
                  left_out=[{"provider_id": "imam-hussain-shrine", "name": "Imam Hussain Holy Shrine live page",
                             "reason": "page answers (imamhussain.org/arabic/live), but the shrine site publishes no "
                                       "position (contact page read); register position cites no source"}],
                  notes=["Al-Abbas live page found: the site's 'live' route is /stream (app bundle)."],
                  robots="imamhussain.org and alkafeel.net allow all")

    # ---- Sri Lanka
    def dalada():
        live_doc, l_r = rd.get("sri_lanka_dalada_maligawa_live", DALADA_LIVE, "dalada_live.html", 65536, True)
        contact_doc, _ = rd.get("sri_lanka_dalada_maligawa_live", DALADA_CONTACT, "dalada_contact.html")
        if "Live" not in (page_title(live_doc) or ""):
            raise ValueError("live page title changed")
        items = [item("sri_lanka_dalada_maligawa_live", "live", "Sri Dalada Maligawa (Temple of the Tooth), Kandy — live",
                      *dalada_position(contact_doc), "LK", "Central Province", "associated_feature", "official_page",
                      l_r["observed_at"], page=DALADA_LIVE, source_page=DALADA_LIVE, catalog=DALADA_LIVE,
                      coordinate_source=DALADA_CONTACT, coordinate_note="Position printed on the temple's contact page.",
                      stream_platform="YouTube")]
        integrate("sri_lanka_dalada_maligawa_live", items, "LK", robots="sridaladamaligawa.lk: no disallow")

    # ---- Namibia
    def nwr():
        art_doc, a_r = rd.get("namibia_nwr_okaukuejo", NWR_ARTICLE, "nwr_waterhole_camera_full.html")
        resort_doc, _ = rd.get("namibia_nwr_okaukuejo", NWR_RESORT, "nwr_okaukuejo_resort.html")
        if not youtube_embed(art_doc):
            raise ValueError("live stream embed missing on the NWR page")
        items = [item("namibia_nwr_okaukuejo", "okaukuejo-waterhole", "Okaukuejo waterhole live camera, Etosha (NWR)",
                      *maps_place(resort_doc, "Okaukuejo"), "NA", "Etosha National Park", "associated_feature",
                      "official_page", a_r["observed_at"], page=NWR_ARTICLE, source_page=NWR_ARTICLE, catalog=NWR_ARTICLE,
                      coordinate_source=NWR_RESORT, coordinate_note="Okaukuejo Camp on the map link of NWR's resort "
                                                                    "page; the floodlit waterhole is at the camp.",
                      crs="EPSG:4326",
                      stream_platform="YouTube")]
        integrate("namibia_nwr_okaukuejo", items, "NA",
                  notes=["The NWR page embeds the live waterhole stream (YouTube)."], robots="nwr.com.na: pages allowed")

    # ---- USAP
    def usap():
        sites_doc, _ = rd.get("noaa_gml_observatory_webcams", GML_SITES, "gml_sites.html")
        sites = parse_gml_sites(sites_doc, ["SPO", "MCM", "PSA"])
        items = []
        for pid, (url, code, label) in USAP_PAGES.items():
            name = {"south-pole": "usap_spwebcam.html", "mcmurdo": "usap_mcmwebcam.html", "palmer": "usap_palwebcam.html"}[pid]
            body, receipt = rd.get("usap_antarctic_webcams", url, name, 65536, True)
            cams = sorted(set(re.findall(r"camLrg\.cfm\?station=[^&\"]+&(?:amp;)?cam=([A-Za-z]+)", decoded(body))))
            lat, lng, site_name = sites[code]
            items.append(item("usap_antarctic_webcams", pid, f"{label} webcams (US Antarctic Program)", lat, lng, "AQ",
                              "Antarctica", "station_location", "official_page", receipt["observed_at"], page=url,
                              source_page=USAP_INDEX, catalog=USAP_INDEX, coordinate_source=GML_SITES,
                              coordinate_note=f"NOAA GML site table position for {code} ({site_name}); station, not a "
                                              "surveyed camera mount.", cameras_on_page=cams))
        integrate("usap_antarctic_webcams", items, "AQ",
                  notes=["Wikidata links to the same three pages exist in the catalogue (community duplicates)."],
                  robots="www.usap.gov: /components/ disallowed (image endpoint)")

    # ---- Reunion
    def reunion():
        index_doc, i_r = rd.get("reunion_irt_viewsurf_webcams", REUNION_INDEX, "reunion_webcams_index.html")
        items, left_out = reunion_items(parse_reunion_index(index_doc), i_r["observed_at"])
        integrate("reunion_irt_viewsurf_webcams", items, "RE", left_out=left_out,
                  notes=["The index (1.25 MB, read once) carries the tourism board's webcam map with a pin per camera.",
                         "The volcano page is already in the catalogue via Wikidata (community duplicate)."],
                  robots="www.reunion.fr: /organisez/webcams/ allowed")

    # ---- MKWC (plain HTTP: not requested; linked from Gemini's page read above)
    def mkwc():
        cloud_doc, c_r = rd.get("gemini_north_webcams", GEMINI_CLOUD, "gemini_cloud_cameras.html")
        if MKWC_INDEX not in decoded(cloud_doc):
            raise ValueError("MKWC link no longer on Gemini's Cloud Cameras page")
        sites_doc, _ = rd.get("gemini_north_webcams", GEMINI_SITES, "gemini_sites.html")
        items = [item("maunakea_mkwc_other_observatory_cams", "summit-cams", "Maunakea summit webcams (Maunakea Weather "
                      "Center index)", *parse_gemini_sites(sites_doc)["North"], "US", "Hawaii", "approximate",
                      "official_page", c_r["observed_at"], page=MKWC_INDEX, source_page=MKWC_INDEX, catalog=MKWC_INDEX,
                      coordinate_source=GEMINI_SITES,
                      coordinate_note="Index of about 20 summit cameras: placed at the Gemini North position published "
                                      "by Gemini (summit ridge), approximate.", crs="WGS84", link_security="plain_http")]
        integrate("maunakea_mkwc_other_observatory_cams", items, "US",
                  notes=["Not requested: plain-HTTP host (the collector reads HTTPS only); the link is confirmed on "
                         "Gemini's Cloud Cameras page read on 2026-11-14."], robots="not requested (HTTP only)")

    for sources, fn in ((["noaa_gml_observatory_webcams"], noaa),
                        (["gemini_north_webcams", "gemini_south_cloud_cameras"], gemini),
                        (["cfht_maunakea_webcams"], cfht), (["kenya_aeroclub_webcams"], kenya),
                        (["india_temple_live_darshan_round2"], temples), (["iraq_karbala_shrine_live"], karbala),
                        (["sri_lanka_dalada_maligawa_live"], dalada), (["namibia_nwr_okaukuejo"], nwr),
                        (["usap_antarctic_webcams"], usap), (["reunion_irt_viewsurf_webcams"], reunion),
                        (["maunakea_mkwc_other_observatory_cams"], mkwc)):
        attempt(sources, fn)
    for source, entry in HELD.items():
        hold(source, entry)
    report["register_viewable_others"] = ("No other world-2 record is viewable + integrate_viewable without a condition: "
                                          "the only other one, japan_mlit_rivers, belongs to the Japan family.")
    report["changes_from_register"] = [
        "NOAA: 10 not 13 (MLO konacam/towercam commented out on the page; mkcam sits on Maunakea, no position read).",
        "CFHT: the viewable still is software.cfht.hawaii.edu/webloop/nanaao.jpg, shown with its GFDL notice on the "
        "Nānā ao page; the register's www.cfht.hawaii.edu/images/webcam/nanaao.jpg is on no page read.",
        "Gemini South all-sky: commented out on the status page; linked to the 'All Sky Camera' page instead.",
        "Kenya: index lists 117 cameras (register 76, a lower bound); 51 have a published position (club KML site "
        "or card), 66 left out.",
        "Western Wall: the 3 camera URLs now redirect to one live page; held for lack of an official position.",
        "India: Mayapur TV left out (no official position); Karbala: Al-Abbas /stream integrated, Imam Hussain left "
        "out (no official position); Transalvador, Shymbulak, DSAT Macau held (no official position).",
        "Réunion: 8 webcams on the map, 7 with a page (4 bacs Sainte-Rose has none).",
        "USAP and MKWC positions: NOAA GML site table and Gemini's published Gemini North position."]
    report["policy_files_replaced"] = ["policies/israel_western_wall_cameras.json: round-1 held fragment, same id, "
                                       "held reason updated (page found; position missing)"]
    report["robots_read"] = sorted({**rd.client.robots, **{k: v for c in rd.slow.values() for k, v in c.robots.items()}})
    report["requests"] = {"new": sum(1 for r in rd.reads if not r["reused"]), "reused_from_raw": sum(1 for r in rd.reads if r["reused"])}
    report["generated_at"] = W.now()
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output folder (normalized inputs, raw/, checks/, policies/, reports/)")
    ap.add_argument("--reuse-raw", action="store_true", help="read pages already saved under raw/ instead of requesting them")
    args = ap.parse_args(argv)
    run(args.out, args.reuse_raw)


if __name__ == "__main__":
    main()
