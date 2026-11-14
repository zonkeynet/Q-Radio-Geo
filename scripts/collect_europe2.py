#!/usr/bin/env python3
"""Collect the Europe round-2 webcam sources of 2026-11-14 (family europe2, stdlib only).

Register: SCRATCH/webcam-research/europe-2.{md,json}. Viewable: Land Oberösterreich (AT), Oulu (FI), DWD (DE),
DHMZ (HR), Stadt Wien (AT). Page links: the medium/high-confidence page_only sources the round assigned to
this family. Held: everything the register marks conditional or "cannot be integrated", the low-confidence
entries, the Moldovan border cameras at Ukraine-facing crossings and Gazprom Polyana (sanctions not assessed).

Stages, as in collect_europe_central.py (whose record/policy helpers this file reuses):

  python scripts/collect_europe2.py --out <dir> fetch [--only a,b]   # network, PoliteClient only
  python scripts/collect_europe2.py --out <dir> check [--only a,b]   # one image sample per viewable source
  python scripts/collect_europe2.py --out <dir> build                # offline: inputs, policies, report

Hand-placed coordinates come only from an official source that was read (operator page or map markers,
an agency station table, or a register value citing one); each such record names it in coordinate_source.
Round-1 files of the same source id are never overwritten: dwd_webcams and arpa_fvg_webcam_directory keep
their raw files under raw/<id>/round2/ and their fragments in policies/<id>.round2.json (sorted after the
round-1 fragment, so the merge and the validator read the round-2 entry last).
"""
from __future__ import annotations

import collections
import datetime as dt
import html
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_europe_central as C  # noqa: E402
from collect_europe_central import F, clean, item, policy, text  # noqa: E402

FAMILY = "europe2"
REVIEWED_AT = "2026-11-14"
REGISTER = "SCRATCH/webcam-research/europe-2.json (register of 2026-11-14, round 2)"
REGISTER_REF = "research register europe-2.json (2026-11-14)"
CC_BY_4 = "https://creativecommons.org/licenses/by/4.0/"
ROUND2_SUFFIX = {"dwd_webcams": "round2", "arpa_fvg_webcam_directory": "round2"}

# ======================================================================================
# Raw files (round-1 folders of the same id are left untouched)
# ======================================================================================


def raw_dir(out, source):
    base = Path(out) / "raw" / source
    return base / ROUND2_SUFFIX[source] if source in ROUND2_SUFFIX else base


def policy_path(out, source):
    suffix = ".round2" if source in ROUND2_SUFFIX else ""
    return Path(out) / "policies" / f"{source}{suffix}.json"


def save(out, source, name, response):
    return F.save_raw(raw_dir(out, source), name, response)


def record_refusal(out, source, url, error):
    folder = raw_dir(out, source)
    folder.mkdir(parents=True, exist_ok=True)
    doc = {"source": source, "url": url, "refused_at": F.now(), "reason": str(error)[:300], "user_agent": F.USER_AGENT}
    (folder / "refused.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


REFRESH = False  # --refresh: request again even when the raw file of this run is already saved


def fetch_one(client, out, source, name, url, accept=None, max_bytes=20 * 1024 * 1024):
    """One list/page request; a refusal is recorded and None returned (the source is then held).
    A file already saved by an earlier pass of this round is reused (no second request) unless --refresh."""
    saved = raw_receipt(out, source, name)
    if saved and not REFRESH and saved.get("url") == url:
        return {"url": url, "final_url": saved.get("final_url"), "status": saved.get("status"), "headers": {},
                "body": read_raw(out, source, name), "observed_at": saved.get("observed_at"), "reused": True}
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


def post_json(client, url, payload):
    """A keyless list request sent as POST (GraphQL), with the client's etiquette: robots.txt first, HTTPS only,
    one request per host per second, the collector User-Agent, refusal on 401/403/429/5xx."""
    if urlsplit(url).scheme != "https":
        raise F.Refused(f"not HTTPS: {url}")
    if not client.allowed(url):
        raise F.Refused(f"robots.txt disallows {url}")
    client._wait(urlsplit(url).hostname)
    redirects = []
    opener = urllib.request.build_opener(F._Redirects(redirects, client.allowed))
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": F.USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
    started = F.now()
    try:
        with opener.open(req, timeout=client.timeout) as r:
            data, status, final, head = r.read(20 * 1024 * 1024 + 1), r.status, r.geturl(), dict(r.headers.items())
    except urllib.error.HTTPError as e:
        data, status, final, head = e.read(4096), e.code, url, dict(e.headers.items()) if e.headers else {}
    client.log.append({"url": url, "method": "POST", "status": status, "bytes": len(data), "started_at": started})
    if status in (401, 403, 407, 429, 451) or status >= 500:
        raise F.Refused(f"HTTP {status} for POST {url}")
    if len(data) > 20 * 1024 * 1024:
        raise F.Refused(f"response over 20 MiB: {url}")
    return {"url": url, "final_url": final, "status": status, "headers": head, "body": data, "truncated": False,
            "redirects": redirects, "started_at": started, "observed_at": F.now(), "request_body": payload}


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
    rel = raw_dir(out, source).relative_to(Path(out)).as_posix()
    rows = []
    for name in names:
        r = raw_receipt(out, source, name)
        if r:
            rows.append({"file": f"{rel}/{name}", "url": r["url"], "observed_at": r["observed_at"], "status": r["status"],
                         "sha256": r["sha256"], "bytes": r["bytes"]})
    return rows


# ======================================================================================
# Endpoints
# ======================================================================================

OOE_LIST = "https://www.land-oberoesterreich.gv.at/webcam/a/json"
OOE_PORTAL = "https://www.land-oberoesterreich.gv.at/webcam.htm"
OOE_WEBMAP = "https://ooe.maps.arcgis.com/sharing/rest/content/items/13c35137e21b4f899b7f165c85d922af/data?f=json"
OOE_IMAGE = "https://www.land-oberoesterreich.gv.at/webcam/a/{station}/KAM{n}"
OOE_STATION_PAGE = "https://www.land-oberoesterreich.gv.at/192995.htm?stationsadresse={station}"
OOE_TERMS = "https://www.land-oberoesterreich.gv.at/nutzungsbedingungen.htm"
OULU_GRAPHQL = "https://api.oulunliikenne.fi/proxy/graphql"
OULU_QUERY = "{ cameras { cameraId name lat lon presets { presetId presentationName imageUrl measuredTime } } }"
OULU_DATASET = "https://avoindata.suomi.fi/data/fi/dataset/oulun-kelikamerakuvat"
OULU_TERMS = "https://wp.oulunliikenne.fi/avoin-data/rajapintojen-kayttooikeusehdot/"
OULU_API_DOC = "https://wp.oulunliikenne.fi/avoin-data/autoliikenne/graphql-rajapinnat/"
OULU_MAP = "https://www.oulunliikenne.fi/"
DWD_DIR = "https://opendata.dwd.de/weather/webcam/"
DWD_STATIONS = ("https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/"
                "KL_Tageswerte_Beschreibung_Stationen.txt")
DWD_LICENCE = "https://www.naturgefahrenportal.de/en/copyright"
DHMZ_PAGE = "https://meteo.hr/podaci.php?section=podaci_vrijeme&param=webkam"
DHMZ_TERMS = "https://meteo.hr/o_nama.php?section=naslovnica&param=uvjeti"
WIEN_PAGES = {"rathausturm": "https://www.wien.gv.at/inhalt/webcam-rathausturm",
              "wasserturm": "https://www.wien.gv.at/inhalt/webcam-wasserturm"}
WIEN_OVERVIEW = "https://www.wien.gv.at/inhalt/webcam"
ARPA_FVG_LIST = "https://www.meteo.fvg.it/ajax/webcamList.php"
ARPA_FVG_MAP = "https://www.meteo.fvg.it/webcam.php"
MK_PAGE_REST = "https://roads.org.mk/wp-json/wp/v2/pages?slug=video-kameri&_fields=id,link,modified,content"
MK_POSTS_REST = "https://roads.org.mk/wp-json/wp/v2/video-kamera?per_page=100&_fields=id,link,slug,title,lang,translations"
MK_MAP = "https://roads.org.mk/patna-mreza/video-kameri/"
RMI_INDEX = "https://www.meteo.be/fr/meteo/observations/webcams"
RMI_LEGAL = "https://www.meteo.be/de/uber-das-kmi/rechtsinformation"
SHMU_PAGE = "https://www.shmu.sk/sk/?page=1&id=webkamery"
MD_LIST = "https://www.border.gov.md/camere-web"
TIROL_LIVE = "https://www.tirol.gv.at/umwelt/luftqualitaet/livebilder"
PLZEN_PAGE = "https://www.plzen.eu/o-meste/multimedia/webkamery"
PKL_LIST = "https://www.pkl.pl/kamery-online.html"
BANSKO_HOME = "https://www.banskoski.com/"
HELSINKI_PORT = "https://www.portofhelsinki.fi/en/about-us/port-of-helsinki/web-camera-south-harbour/"
VISITFINLAND = "https://www.visitfinland.com/en/practical-tips/live-from-finland/"
KIEL_PAGE = "https://www.portofkiel.com/webcam.html"
OMIRL_LIST = "https://omirl.regione.liguria.it/Omirl/rest/stations/webcam"
OMIRL_VIEWER = "https://omirl.regione.liguria.it/"
ORESUND_PAGE = "https://www.oresundsbron.com/sv/pylonkamera"
SMARTBAY_DATASET = "https://data.gov.ie/en_GB/dataset/smartbay-observatory-video-camera-data"
BAFG_PAGE = "https://www.bafg.de/DE/5_Informiert/1_Portale_Dienste/Webcam/webcam_node.html"
TURKU_PAGE = "https://turunseurakunnat.fi/en/turun-tuomiokirkko/explore-turku-cathedral-virtually/tower-camera/"
GEFYRA_PAGE = "https://www.gefyra.gr/en/bridge/Live-Camera/"
BORMIO_PAGE = "https://www.bormioski.eu/webcam-bormio/"
CAMPIGLIO_PAGE = "https://www.campigliodolomiti.it/it/live-info/webcam"
CERVINIA_PAGE = "https://www.cervinia.it/webcam"

# ======================================================================================
# Fetch stage
# ======================================================================================


def fetch_ooe_land_webcams(client, out):
    sid = "ooe_land_webcams"
    if not fetch_one(client, out, sid, "webcam_list.json", OOE_LIST, accept="application/json"):
        return
    webmap = fetch_one(client, out, sid, "webmap.json", OOE_WEBMAP, accept="application/json")
    if not webmap:
        return
    layer = ooe_layer_url(webmap["body"])
    if layer:
        query = layer.rstrip("/") + "/query?" + urlencode({
            "where": "1=1", "outFields": "STATIONSADRESSE,STATIONSNAME,STRASSE,KM", "returnGeometry": "true",
            "outSR": "4326", "f": "json"})
        fetch_one(client, out, sid, "layer0_query.json", query, accept="application/json")
    fetch_one(client, out, sid, "station_page_sample.html", OOE_STATION_PAGE.format(station=32), max_bytes=2 * 1024 * 1024)


def fetch_oulu_kelikamerat(client, out):
    sid = "oulu_kelikamerat"
    try:
        r = post_json(client, OULU_GRAPHQL, {"query": OULU_QUERY})
    except (F.Refused, OSError) as e:
        record_refusal(out, sid, OULU_GRAPHQL, e)
        return
    receipt = save(out, sid, "cameras.json", r)
    receipt.update({"method": "POST", "request_body": r["request_body"]})
    (raw_dir(out, sid) / "cameras.json.receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")


def fetch_dwd_webcams(client, out):
    sid = "dwd_webcams"
    if not fetch_one(client, out, sid, "webcam_dir.html", DWD_DIR):
        return
    fetch_one(client, out, sid, "KL_Tageswerte_Beschreibung_Stationen.txt", DWD_STATIONS, max_bytes=4 * 1024 * 1024)
    # The Hamburg camera site is not named in the register: read the view folder once and its newest
    # description file (.txt), which DWD publishes next to every image.
    listing = fetch_one(client, out, sid, "Hamburg-SO_dir.html", DWD_DIR + "Hamburg-SO/", max_bytes=16 * 1024 * 1024)
    if listing:
        txts = sorted(h for h in dir_links(listing["body"]) if h.endswith(".txt"))
        if txts:
            fetch_one(client, out, sid, "Hamburg-SO_latest.txt", DWD_DIR + "Hamburg-SO/" + txts[-1], max_bytes=1024 * 1024)


def fetch_dhmz_webcams(client, out):
    fetch_one(client, out, "dhmz_webcams", "webkam.html", DHMZ_PAGE)


def fetch_wien_stadt_webcams(client, out):
    for key, url in WIEN_PAGES.items():
        fetch_one(client, out, "wien_stadt_webcams", f"webcam-{key}.html", url)


def fetch_arpa_fvg_webcam_directory(client, out):
    fetch_one(client, out, "arpa_fvg_webcam_directory", "webcamList.json", ARPA_FVG_LIST, accept="application/json")


def fetch_mk_state_roads_video_kameri(client, out):
    sid = "mk_state_roads_video_kameri"
    if fetch_one(client, out, sid, "page_video_kameri.json", MK_PAGE_REST, accept="application/json"):
        fetch_one(client, out, sid, "video_kamera_posts.json", MK_POSTS_REST, accept="application/json")


ISD_HISTORY = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
REFERENCE = "europe2_reference"  # raw folder of the shared official station table


def fetch_station_table(client, out):
    """NOAA NCEI station history (isd-history.csv, U.S. federal agency table of WMO/synoptic stations): the
    station coordinates of the RMI and SHMU camera sites (WMO OSCAR's robots.txt disallows all agents)."""
    fetch_one(client, out, REFERENCE, "isd-history.csv", ISD_HISTORY, max_bytes=8 * 1024 * 1024)


def fetch_tirol_luft_livebilder(client, out):
    sid = "tirol_luft_livebilder"
    page = fetch_one(client, out, sid, "livebilder.html", TIROL_LIVE, max_bytes=8 * 1024 * 1024)
    if page:
        for cam in parse_tirol_livebilder(page["body"]):
            fetch_one(client, out, sid, f"station-{cam['station_slug']}.html", cam["station_page"], max_bytes=8 * 1024 * 1024)


def fetch_page(sid, name, url):
    def fetch(client, out):
        fetch_one(client, out, sid, name, url, max_bytes=8 * 1024 * 1024)
    return fetch


# ======================================================================================
# Pure parsers (the tests feed them trimmed fixtures)
# ======================================================================================


def dir_links(body):
    """Relative links of an nginx/Apache directory index (no parent link, no queries)."""
    return [html.unescape(h) for h in re.findall(r'<a href="([^"?#]+)"', text(body)) if h not in ("../", "/") and "/" not in h.rstrip("/")]


def parse_tirol_livebilder(body):
    """Camera images on luft.tirol.gv.at with the station page each links and the caption (view direction)."""
    page = text(body)
    rows, seen = [], set()
    for m in re.finditer(r'<img[^>]+src="(https://luft\.tirol\.gv\.at/([a-z0-9_]+)\.jpg)"', page):
        image, key = m.group(1), m.group(2)
        if key in seen:
            continue
        rest = page[m.end():m.end() + 1500]
        link = re.search(r'href="(/umwelt/luftqualitaet/([a-z0-9-]+)/)"[^>]*>([^<]*)', rest)
        caption = re.search(r"<p[^>]*>\s*(Blickrichtung[^<]*)</p>", rest)
        if not link or link.group(2) == "livebilder":
            continue
        seen.add(key)
        rows.append({"image": image, "key": key, "station_slug": link.group(2),
                     "station_page": "https://www.tirol.gv.at" + link.group(1), "station_label": clean(link.group(3)),
                     "view": clean(caption.group(1)) if caption else None})
    return rows


def ooe_layer_url(body):
    """URL of the webmap's Land OÖ camera layer (operational layer 0); the ASFINAG layer is never used."""
    doc = json.loads(text(body))
    layers = doc.get("operationalLayers") or []
    for layer in layers:
        url = str(layer.get("url") or "")
        title = str(layer.get("title") or "")
        if "asfinag" in (url + title).lower():
            continue
        if re.search(r"/MapServer/0$|/FeatureServer/0$", url):
            return url
    return None



def ooe_rows(list_body, layer_body):
    """One row per released view (KAMn_Freigabe == 1) of the Land OÖ list, joined on STATIONSADRESSE with the
    point geometry of the webmap's Land OÖ layer (WGS84 by the query's outSR=4326). Unjoined stations are skipped."""
    stations = json.loads(text(list_body).lstrip("﻿"))
    layer = json.loads(text(layer_body))
    wkid = (layer.get("spatialReference") or {}).get("wkid")
    if wkid != 4326:
        raise ValueError(f"Land OÖ layer answered wkid {wkid}, not 4326")
    geo = {}
    for f in layer.get("features", []):
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        if a.get("STATIONSADRESSE") is not None and g.get("x") is not None and g.get("y") is not None:
            geo[int(a["STATIONSADRESSE"])] = (float(g["y"]), float(g["x"]))
    rows, unjoined = [], []
    for s in stations:
        station = int(s["STATIONSADRESSE"])
        if station not in geo:
            unjoined.append(station)
            continue
        for n in range(1, 5):
            if s.get(f"KAM{n}_Freigabe") != 1:
                continue
            rows.append({"station": station, "camera": n, "name": clean(s.get("STATIONSNAME")), "road": clean(s.get("STRASSE")) or None,
                         "km": clean(s.get("KM")) or None, "municipality": clean(s.get("GEM_NAME")) or None,
                         "altitude_m": s.get("SEEHOEHE"), "lat": geo[station][0], "lng": geo[station][1]})
    return rows, unjoined


def parse_time(value):
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def oulu_rows(body, observed_at, max_age_hours=24):
    """City cameras only (cameraId 'CT…'; the 'C1…' ones are Fintraffic Digitraffic cameras already in the catalogue),
    one row per preset whose image was taken within max_age_hours of the list request."""
    doc = json.loads(text(body))
    seen = parse_time(observed_at)
    rows, stale = [], []
    for cam in (doc.get("data") or {}).get("cameras") or []:
        cid = str(cam.get("cameraId") or "")
        if not cid.startswith("CT"):
            continue
        for p in cam.get("presets") or []:
            when = p.get("measuredTime")
            fresh = bool(when) and (seen - parse_time(when)).total_seconds() <= max_age_hours * 3600
            row = {"camera": cid, "preset": str(p.get("presetId") or ""), "camera_name": clean(cam.get("name")),
                   "view": clean(p.get("presentationName")) or None, "image": p.get("imageUrl"), "measured_at": when,
                   "lat": float(cam["lat"]), "lng": float(cam["lon"])}
            (rows if fresh and row["preset"] and row["image"] else stale).append(row)
    return rows, stale


def dwd_views(body):
    return [h.rstrip("/") for h in dir_links(body) if h.endswith("/")]


def dwd_stations(body):
    """CDC station description table (fixed columns, ISO-8859-1): {Stationsname: row}."""
    raw = body.decode("latin-1") if isinstance(body, (bytes, bytearray)) else body
    out = {}
    for line in raw.splitlines():
        m = re.match(r"^(\d{5}) (\d{8}) (\d{8}) +(-?\d+) +(-?\d+\.\d+) +(-?\d+\.\d+) (.+?) {2,}(\S.*?) {2,}(\S+)\s*$", line)
        if m:
            out[m.group(7).strip()] = {"id": m.group(1), "until": m.group(3), "height_m": int(m.group(4)),
                                       "lat": float(m.group(5)), "lng": float(m.group(6)), "name": m.group(7).strip(),
                                       "state": m.group(8).strip()}
    return out


def parse_dhmz(body):
    rows = []
    for m in re.finditer(r'<img[^>]+src="(?:https:)?//vrijeme\.hr/([a-z0-9_]+)\.jpg"[^>]*>', text(body)):
        rows.append({"key": m.group(1), "image": f"https://vrijeme.hr/{m.group(1)}.jpg"})
    page = clean(text(body))
    captions = {"zggric": "Zagreb Maksimir", "split": "PMC Split", "zav": "GMP Zavižan"}
    for r in rows:
        r["caption_found"] = captions.get(r["key"], "~") in page
    return rows


def parse_wien(body):
    """Preset images of one city webcam page and whether its CC BY 4.0 footer is present."""
    page = text(body)
    presets = {}
    for m in re.finditer(r'<img[^>]+src="(https://www\.wien\.gv\.at/webcam-([rw])turm/[rw]turm(\d+)\.jpeg)"[^>]*alt="([^"]*)"', page):
        presets.setdefault(int(m.group(3)), {"n": int(m.group(3)), "image": m.group(1), "caption": clean(m.group(4)) or None})
    licensed = "creativecommons.org/licenses/by/4.0" in page and "CC-BY 4.0" in page
    return [presets[k] for k in sorted(presets)], licensed


def mk_rows(page_body, posts_body):
    """English camera pages joined with the map markers of the official camera map (marker id = a language
    version's post id, linked through the post's translations map)."""
    pages = json.loads(text(page_body))
    content = pages[0]["content"]["rendered"]
    m = re.search(r'data-markers="([^"]+)"', content)
    markers = {int(x["id"]): x["latLang"] for x in json.loads(html.unescape(m.group(1)))} if m else {}
    rows, unplaced = [], []
    for post in json.loads(text(posts_body)):
        if post.get("lang") != "en":
            continue
        trans = post.get("translations") or {}
        hit = next((int(trans[lang]) for lang in ("en", "mk", "sq") if trans.get(lang) and int(trans[lang]) in markers), None)
        title = clean(html.unescape(post["title"]["rendered"]))
        if hit is None:
            unplaced.append(title)
            continue
        kind = "border_crossing" if title.lower().startswith("border") else "toll_plaza"
        rows.append({"post": int(post["id"]), "marker": hit, "title": title, "page": post["link"], "kind": kind,
                     "lat": float(markers[hit]["lat"]), "lng": float(markers[hit]["lng"])})
    return rows, unplaced


def rmi_pages(body):
    rows = []
    for m in re.finditer(r'href="(/fr/meteo/observations/webcams/(webcam|snowcam)-([a-z-]+))"[^>]*>([^<]+)<', text(body)):
        rows.append({"path": m.group(1), "kind": m.group(2), "station": m.group(3), "label": clean(m.group(4))})
    return list({r["path"]: r for r in rows}.values())


def isd_rows(body, wanted):
    """NOAA NCEI isd-history.csv rows for the wanted USAF ids: {usaf: {name, ctry, lat, lng, end}}."""
    import csv
    import io
    out = {}
    for r in csv.DictReader(io.StringIO(text(body))):
        if r.get("USAF") in wanted and r.get("LAT") and r.get("LON"):
            out[r["USAF"]] = {"name": r["STATION NAME"], "ctry": r["CTRY"], "lat": float(r["LAT"]), "lng": float(r["LON"]),
                              "end": r["END"]}
    return out


def shmu_cameras(body):
    rows = []
    for m in re.finditer(r'kamera=(hdcam\d+)" title="[^"]*webovej kamery ([^"]+)"', text(body)):
        rows.append({"camera": m.group(1), "name": clean(m.group(2))})
    return list({r["camera"]: r for r in rows}.values())


def dms(value):
    m = re.match(r"\s*(\d+)°\s*(\d+)'\s*(\d+(?:[.,]\d+)?)", value)
    if not m:
        raise ValueError(f"not a DMS value: {value!r}")
    return int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3).replace(",", ".")) / 3600


def tirol_station(body):
    """Station name and WGS84 position published on a Land Tirol air-quality station page (None when absent)."""
    page = text(body)
    title = re.search(r"<title>([^<|]+)", page)
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S))))
    m = re.search(r"Geographische Länge \(WGS84\):\s*Geographische Breite \(WGS84\):\s*(\d+°\s*\d+'\s*[\d,.]+\")\s*(\d+°\s*\d+'\s*[\d,.]+\")", plain)
    name = clean(title.group(1)) if title else None
    if not m:
        return {"name": name, "lat": None, "lng": None}
    return {"name": name, "lng": dms(m.group(1)), "lat": dms(m.group(2)), "lng_dms": m.group(1), "lat_dms": m.group(2)}


def omirl_rows(body):
    return [{"code": clean(r.get("shortCode")), "name": clean(r.get("name")), "municipality": clean(r.get("municipality")),
             "lat": float(r["lat"]), "lng": float(r["lon"]), "altitude_m": r.get("alt")}
            for r in json.loads(text(body)) if r.get("shortCode") and r.get("lat") is not None]


def smartbay_point(body):
    """The dataset's spatial coverage (a GeoJSON polygon a few metres wide around the observatory): its centre."""
    page = html.unescape(text(body))
    m = re.search(r'\{"type":\s*"Polygon",\s*"coordinates":\s*(\[\[\[.*?\]\]\])\}', page)
    if not m:
        return None
    ring = json.loads(m.group(1))[0]
    lng = sum(p[0] for p in ring) / len(ring)
    lat = sum(p[1] for p in ring) / len(ring)
    return lat, lng


def md_pages(body):
    return sorted(set(re.findall(r'href="/camere-web/([a-z0-9-]+)"', text(body))))


REGISTER_HELD = [  # (id, country, name, url, kind, register admission condition, evidence) from europe-2.json
    ["tr_ibb_uym", "TR", "İBB Ulaşım Yönetim Merkezi / İstanbul'u Seyret — Istanbul traffic and city cameras (re-check)", "https://data.ibb.gov.tr/robots.txt", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; needs a reachable İBB camera list and a KVKK-compatible publication", ["https://data.ibb.gov.tr/robots.txt", "https://uym.ibb.gov.tr/robots.txt", "https://tkm.ibb.gov.tr/robots.txt"]],
    ["tirol_landesstrassen_webcams", "AT", "Land Tirol — Webcams Landesstraßen", "https://www.tirol.gv.at/verkehr/strassenbau-und-strassenerhaltung/webcams/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated. Possible later path: parse the 59 road pages and geocode road+km against GIP.at (CC BY 4.0) — adapter effort L — or ask Land Tirol for the camera list.", ["https://www.tirol.gv.at/impressum/", "https://www.tirol.gv.at/verkehr/strassenbau-und-strassenerhaltung/webcams/", "https://www.tirol.gv.at/verkehr/strassenbau-und-strassenerhaltung/webcams/webcams-bezirk-kufstein/l-211-unterinntalstrasse-1-teil/"]],
    ["vmz_bremen_webcams", "DE", "VMZ Bremen — webcams on the traffic map", "https://vmz.bremen.de/verkehrslage/aktuell", "cannot_be_integrated", "No list endpoint with coordinates: cannot be integrated (the layer source is inside the map bundle). 1 OSM record already uses the ?feature=poi-vmz-hb-17 pattern.", ["https://vmz.bremen.de/verkehrslage/aktuell", "https://vmz.bremen.de/sitemap", "https://vmz.bremen.de/assets/js/app.1741345079.js"]],
    ["vejdirektoratet_webcams", "DK", "Vejdirektoratet — trafikkort webcams", "https://trafikkort.vejdirektoratet.dk/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (beyond the single map link OSM already has).", ["https://trafikkort.vejdirektoratet.dk/", "https://nap.vd.dk/themes/1", "https://raw.githubusercontent.com/Vejdirektoratet/sdk-web/master/README.md"]],
    ["fr_bison_fute_agglomeration_cameras", "FR", "Bison Futé — 'Caméras' layer of the agglomeration traffic maps (DIR Atlantique, Sud-Ouest, Centre-Ouest, Ouest, Nord, Nord-Ouest, Méditerranée)", "https://www.dir.sud-ouest.developpement-durable.gouv.fr/circulation-en-temps-reel-sur-le-peripherique-a10431.html", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (only one link per agglomeration map would be possible; not worth records)", ["https://www.bison-fute.gouv.fr/mentions-legales.html", "https://www.dir.sud-ouest.developpement-durable.gouv.fr/circulation-en-temps-reel-sur-le-peripherique-a10431.html", "https://www.bison-fute.gouv.fr/extensions/bisonfute/_js/bf_jstrafic_web.js"]],
    ["fr_dir_est_webcams", "FR", "DIR Est — webcams (webcam.dir-est.fr)", "https://www.dir.est.developpement-durable.gouv.fr/nos-webcams-r248.html", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (find the 'liens' source, probably per-sector '/iti/{id}', within robots; then page links to https://webcam.dir-est.fr/)", ["https://www.dir.est.developpement-durable.gouv.fr/mentions-legales-a135.html", "https://www.dir.est.developpement-durable.gouv.fr/nos-webcams-r248.html", "https://www.dir.est.developpement-durable.gouv.fr/nos-webcams-a120.html"]],
    ["fr_dir_massif_central_webcams", "FR", "DIR Massif Central — 33 webcams live (RN/A75/A89 network)", "https://www.dir.massif-central.developpement-durable.gouv.fr/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (viewer host on magsys-services.net unreachable; re-check, then look for a camera list with positions)", ["https://www.dir.massif-central.developpement-durable.gouv.fr/mentions-legales-a1510.html", "https://www.dir.massif-central.developpement-durable.gouv.fr/", "https://www.dir.massif-central.developpement-durable.gouv.fr/33-webcams-live-a2584.html"]],
    ["fr_resort_webcam_platforms", "FR", "Ski-resort and town webcam platforms — Skaping (new evidence: player sitemap with per-page coordinates)", "https://www.skaping.com/sitemap.players.xml", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (sitemap has no positions; a per-page crawl would be bulk collection) — ask Skaping for a list or permission", ["https://www.skaping.com/sitemap.players.xml", "https://www.skaping.com/cauterets/pontdespagne"]],
    ["lamma_toscana_webcams", "IT", "Consorzio LaMMA webcam directory and Meteo-I-Mobility road webcams", "https://www.lamma.toscana.it/meteo/osservazioni-e-dati/webcam-lista-localita", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated. For the 6 Meteo-I-Mobility cams: image URLs and positions from LaMMA (e-mail info@lamma.toscana.it) would allow viewable tier B under CC BY-ND 4.0.", ["https://www.lamma.toscana.it/disclaimer", "https://www.lamma.toscana.it/meteo/osservazioni-e-dati/webcam-lista-localita", "https://www.lamma.toscana.it/webcam/volterra-pi"]],
    ["nl_rws_verkeersinfo_cameras", "NL", "Rijkswaterstaat Verkeersinformatie — motorway camera pages", "https://www.rwsverkeersinfo.nl/cameras/8/a4-knooppunt-de-hoek", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (ask RWS/NDW for the camera list used by rwsverkeersinfo.nl)", ["https://www.rijkswaterstaat.nl/copyright", "https://www.rwsverkeersinfo.nl/cameras/8/a4-knooppunt-de-hoek", "https://rwsverkeersinfo.nl/sitemap.xml"]],
    ["at_ski_area_official_pages", "AT", "Austrian ski areas' own webcam pages (Ischgl, Sölden, Kitzbühel, Saalbach, St. Anton, Zillertal, Schladming)", "https://www.stantonamarlberg.com/en/webcams", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (manual curation per resort only)", ["https://www.stantonamarlberg.com/en/webcams", "https://www.zillertal.at/en/?gebiet=livecams", "https://www.schladming-dachstein.at/en/info-and-service/webcams-and-weather/webcams"]],
    ["wien_stadtplan_verkehrskameras", "AT", "Stadt Wien — traffic cameras in the Stadtplan (e.g. Friedrichstraße)", "https://www.wien.gv.at/inhalt/webcam", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (ask Stadt Wien to publish the Stadtplan camera layer as OGD)", ["https://digitales.wien.gv.at/ogd-nutzungsbedingungen/", "https://www.wien.gv.at/inhalt/webcam", "https://data.wien.gv.at/daten/geo?service=WFS&request=GetCapabilities&version=1.1.0"]],
    ["be_wallonia_trafiroutes", "BE", "SPW Mobilité / PEREX — Trafiroutes motorway cameras", "https://trafiroutes.wallonie.be/trafiroutes/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (re-check after the Trafiroutes relaunch)", ["https://trafiroutes.wallonie.be/trafiroutes/", "http://trafiroutes.wallonie.be/trafiroutes/maptempsreel/"]],
    ["ticino_turismo_webcams", "CH", "Ticino Turismo — Webcam 24h", "https://www.ticino.ch/it/webcams.html", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (duplicates feratel)", ["https://www.ticino.ch/it/webcams.html"]],
    ["dic_brno_cameras", "CZ", "DIC Brno (Dopravní informační centrum Brno) — camera layer", "https://www.doprava-brno.cz/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (ask DIC Brno / data.brno.cz for a camera dataset).", ["https://www.doprava-brno.cz/"]],
    ["de_ski_mountain_official_pages", "DE", "German ski and mountain operators' webcam pages (Zugspitze, Garmisch, Nebelhorn, Feldberg, Fichtelberg, Winterberg)", "https://zugspitze.de/en", "cannot_be_integrated", "No list endpoint with coordinates: cannot be integrated beyond the existing provider records.", ["https://zugspitze.de/en", "https://www.liftverbund-feldberg.de/", "https://www.fichtelberg-ski.de/"]],
    ["hessen_mobil_verkehrsservice", "DE", "Hessen Mobil — Verkehrsservice Hessen webcams", "https://verkehrsservice.hessen.de/", "cannot_be_integrated", "No list endpoint with coordinates: cannot be integrated. The 4 OSM links to the home page already cover it.", ["https://verkehrsservice.hessen.de/", "https://verkehrsservice.hessen.de/js/app.67f2dcd9.js"]],
    ["ee_transpordiamet_tarktee", "EE", "Transpordiamet Tark Tee road-weather cameras", "https://tarktee.ee/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; ask Transpordiamet for the Tark Tee data-gateway (ITS NAP) camera feed and its licence.", ["https://tarktee.ee/", "https://tarktee.ee/robots.txt"]],
    ["fr_hautes_alpes_inforoute05", "FR", "Hautes-Alpes — Info Route 05 cameras", "https://inforoute.hautes-alpes.fr/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; read the CGU before adding links", ["https://inforoute.hautes-alpes.fr/doc/cgu.pdf", "https://inforoute.hautes-alpes.fr/"]],
    ["fr_inforoute_link_permitted_departments", "FR", "Haute-Garonne (inforoute31.fr), Drôme (inforoute26.fr) and Alpes-Maritimes (inforoutes06.fr) — road webcams", "https://www.inforoute31.fr/mentions-legales.php", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (the webcam layer request is unknown; ask the departments or find a published list)", ["https://www.inforoute31.fr/mentions-legales.php", "https://www.inforoute26.fr/mentions-legales.php", "https://www.inforoutes06.fr/mentions-legales.php"]],
    ["fr_vendee_departement_webcams", "FR", "Département de la Vendée — 'Les webcams du Conseil départemental'", "https://www.vendee.fr/les-webcams-du-conseil-departemental", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (small set: hand-place after reading the full index and legal notice in a browser)", ["https://www.vendee.fr/mentions-legales", "https://www.vendee.fr/les-webcams-du-conseil-departemental", "https://www.vendee.fr/les-webcams-du-conseil-departemental/port-de-lile-dyeu"]],
    ["budapest_kozut_figyelo", "HU", "Budapest Közút — Közút figyelő camera app", "https://kozutfigyelo.budapestkozut.hu/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (camera service URL inside a bundle over the request cap).", ["https://kozutfigyelo.budapestkozut.hu/", "https://kozutfigyelo.budapestkozut.hu/main.0730bded54724c38.js"]],
    ["is_reykjanes_eruption_webcams", "IS", "Reykjanes eruption webcams — location dataset (Náttúrufræðistofnun) and operator streams", "https://gatt.natt.is/geonetwork/srv/api/records/d8270865-2683-4e55-b07b-87025458f78a/formatters/xml", "cannot_be_integrated", "Ask Náttúrufræðistofnun (natt@natt.is) for the layer and its licence; then page links per operator. Until then no list: cannot be integrated.", ["https://gatt.natt.is/geonetwork/srv/api/records/d8270865-2683-4e55-b07b-87025458f78a/formatters/xml", "https://gis.natt.is/geoserver/wfs"]],
    ["it_ski_sites_unreadable", "IT", "Ski areas whose official sites could not be read (Via Lattea, Roccaraso, Funivia dell'Etna, Monterosa Ski)", "https://www.vialattea.it/robots.txt", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; read the pages in a browser, then hand-place one record per resort.", ["https://www.vialattea.it/robots.txt", "https://www.roccaraso.net/robots.txt", "https://www.funiviaetna.com/robots.txt"]],
    ["marche_rete_mir_webcams", "IT", "Regione Marche Rete MIR (meteo-idro-pluviometric network) station webcams", "https://retemir.regione.marche.it/", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (webcam list not located); find the webcam route in the app (lazy chunk) or ask the Centro Funzionale; read the Regione Marche legal notes for the data licence", ["https://retemir.regione.marche.it/", "https://retemir.regione.marche.it/api/stations", "https://retemir.regione.marche.it/api/sensors"]],
    ["provincia_bz_meteo_webcams", "IT", "Provincia autonoma di Bolzano - Meteo Alto Adige webcams page", "https://meteo.provincia.bz.it/it/webcams", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; find the SPA's data service or ask the office.", ["https://meteo.provincia.bz.it/it/webcams", "https://data.civis.bz.it/dataset?q=webcam"]],
    ["lv_lvc_road_cameras", "LV", "Latvijas Valsts ceļi (LVC) / Latvian NAP road cameras", "https://data.gov.lv/dati/api/3/action/package_search?q=kameras%20OR%20kamera%20OR%20webkamera&rows=20", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; re-check if the NAP adds a camera dataset.", ["https://data.gov.lv/dati/api/3/action/package_search?q=kameras%20OR%20kamera%20OR%20webkamera&rows=20", "https://data.lvceli.lv/opendata/", "https://transportdata.gov.lv/api/v1/fetch/sitemap.xml"]],
    ["pt_spotazores", "PT", "SpotAzores — Azores webcams (all nine islands)", "https://spotazores.com/en/wp-json/wp/v2/webcam?per_page=100&_fields=id,slug,link,title,acf,meta", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated (50 named villages/beaches could be gazetteer-placed; read the site terms first)", ["https://spotazores.com/en/wp-json/wp/v2/webcam?per_page=100&_fields=id,slug,link,title,acf,meta"]],
    ["ru_kamchatka_volcano_cams", "RU", "Kamchatka volcano monitoring (KB GS RAS 'vmon'; IVS FEB RAS / KVERT webcams)", "https://www.emsd.ru/~ssl/monitoring/main.htm", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; confirm camera pages on kscnet.ru/KVERT when reachable (hand-placeable per volcano)", ["https://www.emsd.ru/~ssl/monitoring/main.htm", "https://www.emsd.ru/~ssl/monitoring/inform_n.htm", "https://www.kscnet.ru/robots.txt"]],
    ["tr_customs_border_cams", "TR", "Ticaret Bakanlığı / Trakya customs gate live cameras (Kapıkule, Pazarkule…)", "https://trakyagumruk.gov.tr/robots.txt", "cannot_be_integrated", "no list endpoint with coordinates: cannot be integrated; host must answer over HTTPS and a list of gates be published", ["https://trakyagumruk.gov.tr/robots.txt", "https://ticaret.gov.tr/robots.txt"]],
    ["it_ski_skirama", "IT", "Skirama Dolomiti Adamello Brenta - ski-area webcam sections", "https://www.skirama.it/", "low_confidence", "hand-place six area records (Folgaria, Campiglio, Monte Bondone, Andalo/Paganella, Pejo, Pinzolo).", ["https://www.skirama.it/"]],
    ["zuerich_tourismus_webcams", "CH", "Zürich Tourismus — official livecams (Roundshot)", "https://www.zuerich.com/de/informieren-planen/nuetzliche-infos-und-services/webcams", "low_confidence", "confirm the camera list on the page in a browser, then hand-place 4 views", ["https://www.zuerich.com/de/informieren-planen/nuetzliche-infos-und-services/webcams"]],
    ["rostock_port_livecam", "DE", "Rostock Port — Livecam", "https://www.rostock-port.de/livecam", "low_confidence", "Hand-place 1 record at the Überseehafen; camera position and direction unconfirmed.", ["https://www.rostock-port.de/livecam"]],
    ["it_ski_livigno", "IT", "Livigno APT webcam page", "https://www.livigno.eu/webcam", "low_confidence", "hand-place one record at Livigno.", ["https://www.livigno.eu/", "https://www.livigno.eu/webcam"]],
    ["vt_sk_tmr_webcams", "SK", "Tatry Mountain Resorts — Vysoké Tatry webcams page", "https://www.vt.sk/stredisko/info-o-stredisku/webkamery", "low_confidence", "One hand-placed record (Tatranská Lomnica) linking the resort webcam page.", ["https://www.vt.sk/stredisko/info-o-stredisku/webkamery"]],
    ["me_mup_border_cameras", "ME", "Montenegro Ministry of Interior — border crossing cameras (via AMSCG)", "https://amscg.org/granicni-prelazi", "conditional", "Confirm kamere.mup.gov.me is reachable (ideally over HTTPS) and read its terms; otherwise link the AMSCG HTTPS page per crossing. Hand-place 10 crossings.", ["https://amscg.org/granicni-prelazi", "http://kamere.mup.gov.me/kamere.php?kamere=Sukobin"]],
    ["ru_gazprom_polyana_webcams", "RU", "Gazprom Polyana resort (Laura, Alpika) — official webcam page", "https://polyanaski.ru/webcam/", "sanctions", "hand-place one record at Estosadok/Laura (approx. 43.68 N, 40.26 E, verify); owner sanctions check", ["https://polyanaski.ru/resort/rules/", "https://polyanaski.ru/webcam/"]],
]


# ======================================================================================
# Hand-placement tables (each value cites the official source it comes from)
# ======================================================================================

# DHMZ: the register's positions for the three addresses named in the DHMZ captions (europe-2.json, dhmz_webcams).
DHMZ_PLACES = {
    "zggric": ("Zagreb Maksimir — Kraš administration building roof, Ravnice 48 (view north-west)", "Zagreb", (45.822, 16.034)),
    "split": ("PMC Split — roof, Glagoljaška 11 (view south-west)", "Splitsko-dalmatinska", (43.509, 16.426)),
    "zav": ("GMP Zavižan — mountain hut wall (view east–south–west)", "Ličko-senjska", (44.815, 14.975)),
}
# Stadt Wien: the register's positions for the two towers named on the city's webcam pages (europe-2.json).
WIEN_PLACES = {
    "rathausturm": ("Webcam am Rathausturm", (48.2108, 16.3573)),
    "wasserturm": ("Webcam Wasserturm (Favoriten, Wienerberg)", (48.1717, 16.3488)),
}
# DWD view folder -> station name in the CDC station table (the register's id 05142 is Ueckermünde, so the join is
# by the station named in the folder). Hamburg-SO/SW: the camera site is not published (Fuhlsbüttel or the
# Seewetteramt in St. Pauli), so those two views are left out.
DWD_VIEW_STATIONS = {"Hohenpeissenberg": "Hohenpeißenberg", "Lindenberg": "Lindenberg", "Offenbach": "Offenbach-Wetterpark",
                     "Schmuecke": "Schmücke", "Warnemuende": "Rostock-Warnemünde", "Wasserkuppe": "Wasserkuppe"}
DWD_DIRECTIONS = {"N": "north", "NNE": "north-north-east", "NE": "north-east", "O": "east", "SO": "south-east", "S": "south",
                  "SW": "south-west", "W": "west", "NW": "north-west"}
# RMI/KMI stations -> NOAA NCEI isd-history.csv USAF id (WMO index + 0). Wideumont, Jabbeke and Stabroek are not in
# the table, so their pages are not placed.
RMI_ISD = {"uccle": ("064470", "UCCLE"), "mont-rigi": ("064940", "MONT-RIGI"), "humain": ("064720", "HUMAIN"),
           "saint-hubert": ("064760", "SAINT HUBERT"), "dourbes": ("064550", "DOURBES"), "diepenbeek": ("064770", "DIEPENBEEK"),
           "melle": ("064340", "MELLE"), "zeebruges": ("064180", "ZEEBRUGGE")}
# SHMU cameras -> isd-history.csv USAF id. 118130 is spelled "BRATISLAVA-LOLIBA" in the table (WMO 11813 Bratislava-Koliba).
SHMU_ISD = {"hdcam01": ("118130", "BRATISLAVA"), "hdcam14": ("118130", "BRATISLAVA"), "hdcam13": ("118120", "MALY JAVORNIK"),
            "hdcam12": ("118190", "JASLOVSKE BOHUNICE"), "hdcam03": ("118560", "MOCHOVCE"), "hdcam10": ("119520", "GANOVCE"),
            "hdcam16": ("119580", "KOJSOVSKA HOLA")}
GEFYRA_PLACE = (38.321, 21.773)  # register: the Rio–Antirrio bridge named on the Gefyra camera page
MD_ROMANIA_FACING = ("bumbata", "leova", "cahul", "costesti", "leuseni", "lipcani", "sculeni")

# ======================================================================================
# Builders: one per source, each returns {"status", "policy", "items"?, ...}
# ======================================================================================


def held(source_id, name, url, reason, until, evidence, country=None, **extra):
    entry = {"status": "held", "held_reason": reason, "held_until": until, "evidence": [e for e in evidence if e],
             "source": {"id": source_id, "name": name, "url": url}, "reviewed_at": REVIEWED_AT}
    if country:
        entry["countries"] = [country]
    entry.update(extra)
    return entry


def held_result(source_id, country, name, url, reason, until, evidence, refused_hosts=(), **extra):
    return {"status": "held", "country": country, "policy": held(source_id, name, url, reason, until, evidence, country),
            "refused_hosts": list(refused_hosts), **extra}


def when_of(out, source, name):
    return raw_receipt(out, source, name)["observed_at"]


def not_fetched(source_id, country, name, url, out, evidence):
    r = refused(out, source_id)
    reason = f"list not fetched: {r['reason']}" if r else "list not fetched"
    host = urlsplit(r["url"]).hostname if r else None
    return held_result(source_id, country, name, url, reason, "a fresh list request that the host and its robots.txt allow",
                       evidence, refused_hosts=[{"host": host, "reason": r["reason"]}] if r else [])


def build_ooe_land_webcams(out):
    sid = "ooe_land_webcams"
    body, layer = read_raw(out, sid, "webcam_list.json"), read_raw(out, sid, "layer0_query.json")
    if body is None or layer is None:
        return not_fetched(sid, "AT", "Land Oberösterreich webcams", OOE_PORTAL, out, [OOE_LIST, OOE_WEBMAP])
    when = when_of(out, sid, "webcam_list.json")
    rows, unjoined = ooe_rows(body, layer)
    items = [item(sid, f"{r['station']}-KAM{r['camera']}",
                  f"{r['name']}" + (f" ({r['road']} km {r['km']})" if r["road"] and r["km"] else "") + f" — Kamera {r['camera']}",
                  r["lat"], r["lng"], "AT", "Oberösterreich", format_="snapshot",
                  snapshot_url=OOE_IMAGE.format(station=r["station"], n=r["camera"]),
                  official_page=OOE_STATION_PAGE.format(station=r["station"]), source_page=OOE_PORTAL, source_catalog=OOE_LIST,
                  observed_at=when, coordinate_role="camera_location", coordinate_crs="EPSG:4326",
                  coordinate_source="Land OÖ public webmap 'Webcam-Portal Zentralraum OÖ', layer 0 (Land OÖ cameras; ASFINAG layer "
                                    "excluded), ArcGIS query outSR=4326, joined on STATIONSADRESSE",
                  road=r["road"], road_km=r["km"], municipality=r["municipality"], altitude_m=r["altitude_m"],
                  station_id=r["station"], camera_number=r["camera"])
             for r in rows]
    pol = policy(
        sid, name="Land Oberösterreich — Webcam-Portal OÖ (Landesstraßen)", url=OOE_PORTAL, catalog_url=OOE_LIST,
        terms_url=OOE_TERMS, license_="Land OÖ Informationsweiterverwendung: free re-use with source credit (site-wide clause, "
                                      "no non-commercial limit)", license_url=OOE_TERMS,
        media_rights=("'Sämtliche Informationen, Daten und Dokumente auf den Internetseiten des Landes Oberösterreich stehen "
                      "kostenlos zur Weiterverwendung bereit, sofern nicht bei der konkreten Information anderes festgelegt ist' "
                      "with the credit 'Quelle: Land Oberösterreich'; the webcam portal sets no different terms. Tier B: the "
                      "clause is site-wide and does not name the webcam images (the register recommends a confirming e-mail to "
                      "post@ooe.gv.at before launch: the user's call)."),
        attribution="Quelle: Land Oberösterreich", evidence=[OOE_TERMS, OOE_PORTAL, OOE_WEBMAP],
        formats=["snapshot"], countries=["AT"], media_hosts=["www.land-oberoesterreich.gv.at"],
        page_hosts=["www.land-oberoesterreich.gv.at"], coordinate_role="camera_location", official_map_url=OOE_PORTAL,
        raw=raw_files(out, sid, "webcam_list.json", "webmap.json", "layer0_query.json", "station_page_sample.html"))
    pol["source"].update({"rights_tier": "B", "excluded": "the webmap's ASFINAG layer (layer 1) and views with KAMn_Freigabe=0",
                          "coordinate_source": "Land OÖ public webmap layer 0 (ArcGIS Online proxy), joined on STATIONSADRESSE"})
    return {"status": "integrated", "country": "AT", "items": items, "policy": pol,
            "robots": "www.land-oberoesterreich.gv.at, ooe.maps.arcgis.com, utility.arcgis.com: list, webmap and layer query allowed",
            "changes": [f"{len(items)} released views at {len({r['station'] for r in rows})} stations; image URL form "
                        "/webcam/a/{id}/KAM{n} exactly (no cache-buster), so the 40 OSM rows using these images dedupe",
                        "official_page = the portal's station page 192995.htm?stationsadresse={id}"]
            + ([f"stations without a layer point skipped: {unjoined}"] if unjoined else []),
            "overlap": "40 osm_webcams rows use land-oberoesterreich.gv.at/webcam/a/{id}/KAMn images as their page"}


def build_oulu_kelikamerat(out):
    sid = "oulu_kelikamerat"
    body = read_raw(out, sid, "cameras.json")
    if body is None:
        return not_fetched(sid, "FI", "Oulu road-weather cameras", OULU_DATASET, out, [OULU_GRAPHQL, OULU_DATASET])
    when = when_of(out, sid, "cameras.json")
    rows, stale = oulu_rows(body, when)
    items = [item(sid, f"{r['camera']}-{r['preset']}", f"{r['camera_name']} — {r['view'] or r['preset']}", r["lat"], r["lng"], "FI",
                  "Oulu", format_="snapshot", snapshot_url=r["image"], official_page=OULU_MAP, source_page=OULU_DATASET,
                  source_catalog=OULU_GRAPHQL, observed_at=when, coordinate_role="camera_location", coordinate_crs="EPSG:4326",
                  coordinate_source="Oulu GraphQL camera list (lat/lon per camera)", direction=r["view"],
                  image_observed_at=r["measured_at"], camera_id=r["camera"])
             for r in rows]
    pol = policy(
        sid, name="Oulun kaupunki — kelikamerakuvat (Oulunliikenne.fi)", url=OULU_DATASET, catalog_url=OULU_GRAPHQL,
        terms_url=OULU_TERMS, license_="CC-BY-4.0 (dataset 'Oulun kelikamerakuvat', avoindata.suomi.fi)", license_url=CC_BY_4,
        media_rights=("The CC BY 4.0 dataset is the camera photographs themselves ('Oulun kaupungin liikennekameroiden ... "
                      "tallentamia valokuvia GraphQL-rajapinnan tarjoamana'); the API terms say the data may be used freely. "
                      "Only the city's own 'CT' cameras are listed; the 'C1' cameras are Fintraffic Digitraffic duplicates."),
        attribution="Oulun kaupunki / Oulunliikenne.fi, CC BY 4.0", evidence=[OULU_DATASET, OULU_TERMS, OULU_API_DOC],
        formats=["snapshot"], countries=["FI"], media_hosts=["d2gakb5f3pwfh0.cloudfront.net"], page_hosts=["www.oulunliikenne.fi"],
        minimum_refresh_seconds=600, coordinate_role="camera_location", official_map_url=OULU_MAP,
        raw=raw_files(out, sid, "cameras.json"))
    pol["source"]["rights_tier"] = "A"
    return {"status": "integrated", "country": "FI", "items": items, "policy": pol,
            "robots": "api.oulunliikenne.fi: robots.txt answers 403 (no rules published, list allowed); one keyless GraphQL POST",
            "changes": [f"{len(items)} fresh presets of {len({r['camera'] for r in rows})} city cameras; {len(stale)} presets "
                        "older than 24 h at list time left out (register: 'drop presets older than ~1 day')"],
            "overlap": "the 69 'C1' cameras are Digitraffic weathercams already in the catalogue (not listed here)"}


def build_dwd_webcams(out):
    sid = "dwd_webcams"
    listing, table = read_raw(out, sid, "webcam_dir.html"), read_raw(out, sid, "KL_Tageswerte_Beschreibung_Stationen.txt")
    if listing is None or table is None:
        return not_fetched(sid, "DE", "DWD webcams", DWD_DIR, out, [DWD_DIR, DWD_STATIONS])
    when = when_of(out, sid, "webcam_dir.html")
    stations = dwd_stations(table)
    items, unplaced = [], []
    for view in dwd_views(listing):
        place, _, direction = view.rpartition("-")
        name = DWD_VIEW_STATIONS.get(place)
        st = stations.get(name) if name else None
        if not st:
            unplaced.append(view)
            continue
        items.append(item(sid, view, f"DWD webcam {st['name']} (view {DWD_DIRECTIONS.get(direction, direction)})", st["lat"], st["lng"],
                          "DE", st["state"], format_="snapshot", snapshot_url=f"{DWD_DIR}{view}/{view}_latest_640.jpg",
                          official_page=f"{DWD_DIR}{view}/", source_page=DWD_DIR, source_catalog=DWD_DIR, observed_at=when,
                          coordinate_role="station_location", coordinate_crs="unspecified_geographic",
                          coordinate_source=f"DWD CDC station list KL_Tageswerte_Beschreibung_Stationen.txt, station {st['id']} {st['name']}",
                          coordinate_note="Position of the DWD station the view folder is named after (station table, 4 decimals).",
                          direction=DWD_DIRECTIONS.get(direction, direction), station_id=st["id"], altitude_m=st["height_m"]))
    pol = policy(
        sid, name="Deutscher Wetterdienst webcams (opendata.dwd.de/weather/webcam)", url=DWD_DIR, catalog_url=DWD_DIR,
        terms_url="https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html",
        license_="CC-BY-4.0 (DWD open spatial data: 'any location-related weather and climate information offered for access')",
        license_url=CC_BY_4,
        media_rights=("'All open spatial data and spatial data services of the DWD ... may be re-used under the Creative Commons "
                      "license conditions BY 4.0 (CC BY 4.0) provided that the source is acknowledged. ... Spatial data here includes "
                      "any location-related weather and climate information offered for access.' (DWD licence text, read on the "
                      "DWD-run naturgefahrenportal.de: www.dwd.de disallows generic agents). Tier B: the webcam images are not named."),
        attribution="Quelle: Deutscher Wetterdienst (DWD), CC BY 4.0", evidence=[DWD_LICENCE, "https://opendata.dwd.de/README.txt", DWD_DIR],
        formats=["snapshot"], countries=["DE"], media_hosts=["opendata.dwd.de"], page_hosts=["opendata.dwd.de"],
        minimum_refresh_seconds=600, coordinate_role="station_location",
        raw=raw_files(out, sid, "webcam_dir.html", "KL_Tageswerte_Beschreibung_Stationen.txt", "Hamburg-SO_dir.html",
                      "Hamburg-SO_latest.txt"))
    pol["source"].update({"rights_tier": "B", "supersedes_hold": "round-1 hold (licence clause not readable) resolved by the "
                          "round-2 register: DWD open-data licence text read on naturgefahrenportal.de"})
    return {"status": "integrated", "country": "DE", "items": items, "policy": pol,
            "robots": "opendata.dwd.de: no robots.txt (404); www.dwd.de not requested (robots disallows generic agents)",
            "changes": ["held policy superseded: integrated as viewable (CC BY 4.0, register rank 3)",
                        "station join by the station named in the folder: the register's id 05142 is Ueckermünde; "
                        "Warnemünde is 04271 Rostock-Warnemünde"]
            + ([f"views left out (camera site not published, Hamburg-SO.txt holds only EXIF data): {unplaced}"] if unplaced else []),
            "overlap": "no DWD webcam records in the catalogue"}


def build_dhmz_webcams(out):
    sid = "dhmz_webcams"
    body = read_raw(out, sid, "webkam.html")
    if body is None:
        return not_fetched(sid, "HR", "DHMZ web cameras", DHMZ_PAGE, out, [DHMZ_PAGE])
    when = when_of(out, sid, "webkam.html")
    items = []
    for r in parse_dhmz(body):
        if r["key"] not in DHMZ_PLACES or not r["caption_found"]:
            continue
        name, region, place = DHMZ_PLACES[r["key"]]
        items.append(item(sid, r["key"], f"DHMZ — {name}", place[0], place[1], "HR", region, format_="snapshot",
                          snapshot_url=r["image"], official_page=DHMZ_PAGE, source_page=DHMZ_PAGE, source_catalog=DHMZ_PAGE,
                          observed_at=when, coordinate_role="approximate", coordinate_crs="EPSG:4326",
                          coordinate_source=f"{REGISTER_REF}, dhmz_webcams: position of the address/site named in the DHMZ caption",
                          coordinate_note="Hand-placed at the building or hut named by DHMZ (approximate)."))
    pol = policy(
        sid, name="DHMZ — Državni hidrometeorološki zavod, web kamere", url=DHMZ_PAGE, terms_url=DHMZ_TERMS,
        license_="Free re-use with mandatory source citation (Zakon o meteorološkoj i hidrološkoj djelatnosti, čl. 17)",
        license_url=DHMZ_TERMS,
        media_rights=("'Podaci i informacije objavljeni na mrežnim stranicama DHMZ-a su slobodno dostupni za ponovnu uporabu ... "
                      "mora sadržavati informaciju o izvoru podataka (Izvor: DHMZ)'. Tier B: site-wide clause, webcams not named."),
        attribution="Izvor: DHMZ", evidence=[DHMZ_TERMS, DHMZ_PAGE], formats=["snapshot"], countries=["HR"],
        media_hosts=["vrijeme.hr"], page_hosts=["meteo.hr"], minimum_refresh_seconds=600, coordinate_role="approximate",
        raw=raw_files(out, sid, "webkam.html"))
    pol["source"]["rights_tier"] = "B"
    return {"status": "integrated", "country": "HR", "items": items, "policy": pol,
            "robots": "meteo.hr: no robots.txt (404); vrijeme.hr checked at the image sample",
            "changes": ["3 cameras hand-placed at the register's positions for the captioned sites (approximate)"],
            "overlap": "1 Wikidata record links vrijeme.hr"}


def build_wien_stadt_webcams(out):
    sid = "wien_stadt_webcams"
    items, unlicensed = [], []
    for key, url in WIEN_PAGES.items():
        body = read_raw(out, sid, f"webcam-{key}.html")
        if body is None:
            continue
        presets, licensed = parse_wien(body)
        if not licensed or not presets:
            unlicensed.append(key)
            continue
        name, place = WIEN_PLACES[key]
        first = presets[0]
        items.append(item(sid, key, f"{name} — {first['caption']}" if first["caption"] else name, place[0], place[1], "AT", "Wien",
                          format_="snapshot", snapshot_url=first["image"], official_page=url, source_page=WIEN_OVERVIEW,
                          source_catalog=url, observed_at=when_of(out, sid, f"webcam-{key}.html"), coordinate_role="approximate",
                          coordinate_crs="EPSG:4326",
                          coordinate_source=f"{REGISTER_REF}, wien_stadt_webcams: position of the tower named on the city's webcam page",
                          coordinate_note="Hand-placed at the tower that carries the camera (approximate).",
                          preset_count=len(presets), direction=first["caption"]))
    if not items:
        return not_fetched(sid, "AT", "Stadt Wien webcams", WIEN_OVERVIEW, out, list(WIEN_PAGES.values()))
    pol = policy(
        sid, name="Stadt Wien — Webcams (Rathausturm, Wasserturm)", url=WIEN_OVERVIEW,
        terms_url="https://digitales.wien.gv.at/ogd-nutzungsbedingungen/", license_="CC-BY-4.0", license_url=CC_BY_4,
        media_rights=("Footer of each webcam item: 'Dieser Inhalt wird von der Stadt Wien kostenfrei gemäß Creative Commons "
                      "CC-BY 4.0 zur Verfügung gestellt' (embed code offered). The Burgtheater camera is a feratel player and is "
                      "not listed."),
        attribution="Stadt Wien – wien.gv.at, CC BY 4.0", evidence=list(WIEN_PAGES.values()), formats=["snapshot"],
        countries=["AT"], media_hosts=["www.wien.gv.at"], page_hosts=["www.wien.gv.at"], minimum_refresh_seconds=300,
        coordinate_role="approximate", raw=raw_files(out, sid, *[f"webcam-{k}.html" for k in WIEN_PAGES]))
    pol["source"]["rights_tier"] = "A"
    return {"status": "integrated", "country": "AT", "items": items, "policy": pol,
            "robots": "www.wien.gv.at: /inhalt/ and /webcam-rturm/, /webcam-wturm/ allowed",
            "changes": ["one record per camera with its first preset view as the snapshot; the other presets stay on the page"]
            + ([f"pages without the CC BY 4.0 footer skipped: {unlicensed}"] if unlicensed else [])}


def build_arpa_fvg_webcam_directory(out):
    sid = "arpa_fvg_webcam_directory"
    r = refused(out, sid)
    return held_result(
        sid, "IT", "ARPA FVG - OSMER webcam directory (ajax/webcamList.php)", ARPA_FVG_MAP,
        "robots.txt not readable over HTTPS: https://www.meteo.fvg.it/robots.txt redirects to the http:// home page, which "
        "the client treats as unreachable (= disallow); the round-2 list ajax/webcamList.php was therefore not requested"
        + (f" ({r['reason']})" if r else ""),
        "the project owner's decision on the HTTP robots redirect, or ARPA FVG serving robots.txt over HTTPS; then the "
        "~204-row list with filtering (no raw IPs, device paths, HTTP-only or rows other sources supply)",
        [ARPA_FVG_LIST, "https://www.meteo.fvg.it/note-legali.php?ln="],
        refused_hosts=[{"host": "www.meteo.fvg.it", "reason": "robots.txt redirects to plain HTTP (treated as disallow)"}],
        robots="www.meteo.fvg.it: robots.txt -> 302 http:// (unreachable under the client's rule)")


def page_policy(sid, *, name, url, terms_url, license_, media_rights, attribution, evidence, countries, page_hosts, role,
                raw, official_map_url=None, catalog_url=None, license_url=None):
    return policy(sid, name=name, url=url, catalog_url=catalog_url, terms_url=terms_url, license_=license_, license_url=license_url,
                  media_rights=media_rights, attribution=attribution, evidence=evidence, formats=["official_page"],
                  countries=countries, page_hosts=page_hosts, coordinate_role=role, official_map_url=official_map_url, raw=raw)


def build_mk_state_roads_video_kameri(out):
    sid = "mk_state_roads_video_kameri"
    page, posts = read_raw(out, sid, "page_video_kameri.json"), read_raw(out, sid, "video_kamera_posts.json")
    if page is None or posts is None:
        return not_fetched(sid, "MK", "Public Enterprise for State Roads — video cameras", MK_MAP, out, [MK_PAGE_REST, MK_POSTS_REST])
    when = when_of(out, sid, "video_kamera_posts.json")
    rows, unplaced = mk_rows(page, posts)
    items = [item(sid, str(r["post"]), f"{r['title']} — State Roads video camera", r["lat"], r["lng"], "MK", "North Macedonia",
                  format_="official_page", official_page=r["page"], source_page=MK_MAP, source_catalog=MK_POSTS_REST,
                  observed_at=when, coordinate_role="associated_feature", coordinate_crs="EPSG:4326",
                  coordinate_source=f"map marker {r['marker']} of the official camera map (roads.org.mk video-kameri page)",
                  coordinate_note="Marker of the toll plaza or border crossing on the operator's camera map.", site_type=r["kind"])
             for r in rows]
    pol = page_policy(
        sid, name="Јавно претпријатие за државни патишта / Public Enterprise for State Roads — video cameras", url=MK_MAP,
        catalog_url=MK_POSTS_REST, terms_url=MK_MAP, license_="None found (all rights reserved)",
        media_rights="No reuse licence and no media exposed in the REST content; links to the official camera pages only.",
        attribution="Public Enterprise for State Roads (roads.org.mk)", evidence=[MK_MAP, MK_POSTS_REST], countries=["MK"],
        page_hosts=["roads.org.mk"], role="associated_feature", official_map_url=MK_MAP,
        raw=raw_files(out, sid, "page_video_kameri.json", "video_kamera_posts.json"))
    return {"status": "integrated", "country": "MK", "items": items, "policy": pol,
            "robots": "roads.org.mk: only /wp-admin/ disallowed (REST allowed)",
            "changes": ["one record per English camera page, positioned by the official map marker of any language version"]
            + ([f"pages without a map marker skipped: {unplaced}"] if unplaced else [])}


def isd_place(table, usaf, expect):
    row = table.get(usaf)
    if not row or expect.split()[0] not in row["name"]:
        return None
    return row


def build_be_rmi_kmi_webcams(out):
    sid = "be_rmi_kmi_webcams"
    body, table = read_raw(out, sid, "webcams.html"), read_raw(out, REFERENCE, "isd-history.csv")
    if body is None or table is None:
        return not_fetched(sid, "BE", "RMI/KMI webcams", RMI_INDEX, out, [RMI_INDEX, ISD_HISTORY])
    when = when_of(out, sid, "webcams.html")
    isd = isd_rows(table, {v[0] for v in RMI_ISD.values()})
    items, unplaced = [], []
    for p in rmi_pages(body):
        spec = RMI_ISD.get(p["station"])
        row = isd_place(isd, *spec) if spec else None
        if not row:
            unplaced.append(p["path"].rsplit("/", 1)[1])
            continue
        items.append(item(sid, f"{p['kind']}-{p['station']}", f"IRM/KMI {p['kind']} {p['label']}", row["lat"], row["lng"], "BE",
                          "Belgium", format_="official_page", official_page="https://www.meteo.be" + p["path"], source_page=RMI_INDEX,
                          source_catalog=RMI_INDEX, observed_at=when, coordinate_role="station_location", coordinate_crs="EPSG:4326",
                          coordinate_source=f"NOAA NCEI isd-history.csv, station {spec[0]} {row['name']} (WMO {spec[0][:5]})",
                          coordinate_note="Synoptic station position from the agency table (about 1 arc-minute precision)."))
    pol = page_policy(
        sid, name="IRM/KMI — webcams and snowcams (meteo.be)", url=RMI_INDEX, terms_url=RMI_LEGAL,
        license_="None (all rights KMI; reproduction and commercial use forbidden)",
        media_rights=("'Die Vervielfältigung oder Publikation ... ist ... strikt verboten'; links to the station pages only. Station "
                      "positions come from an agency station table, not from meteo.be."),
        attribution="IRM/KMI — meteo.be", evidence=[RMI_LEGAL, RMI_INDEX, ISD_HISTORY], countries=["BE"], page_hosts=["www.meteo.be"],
        role="station_location", raw=raw_files(out, sid, "webcams.html") + raw_files(out, REFERENCE, "isd-history.csv"))
    return {"status": "integrated", "country": "BE", "items": items, "policy": pol,
            "robots": "www.meteo.be: 'Allow: /'; www.ncei.noaa.gov: /pub/data/noaa/ allowed (WMO OSCAR disallows all agents)",
            "changes": [f"{len(items)} of {len(items) + len(unplaced)} pages placed at their RMI station"]
            + ([f"stations not in the agency table, pages not placed: {unplaced}"] if unplaced else []),
            "overlap": "2 OSM rows (Mont Rigi) use getWebcamImage.php as page; the build moves them to references"}


def build_shmu_webcams(out):
    sid = "shmu_webcams"
    body, table = read_raw(out, sid, "webkamery.html"), read_raw(out, REFERENCE, "isd-history.csv")
    if body is None or table is None:
        return not_fetched(sid, "SK", "SHMÚ webcams", SHMU_PAGE, out, [SHMU_PAGE, ISD_HISTORY])
    when = when_of(out, sid, "webkamery.html")
    isd = isd_rows(table, {v[0] for v in SHMU_ISD.values()})
    items, unplaced = [], []
    for c in shmu_cameras(body):
        spec = SHMU_ISD.get(c["camera"])
        row = isd_place(isd, *spec) if spec else None
        if not row:
            unplaced.append(c["name"])
            continue
        items.append(item(sid, c["camera"], f"SHMÚ webkamera {c['name']}", row["lat"], row["lng"], "SK", "Slovensko",
                          format_="official_page", official_page=f"{SHMU_PAGE}&kamera={c['camera']}", source_page=SHMU_PAGE,
                          source_catalog=SHMU_PAGE, observed_at=when, coordinate_role="station_location", coordinate_crs="EPSG:4326",
                          coordinate_source=f"NOAA NCEI isd-history.csv, station {spec[0]} {row['name']} (WMO {spec[0][:5]})",
                          coordinate_note="Synoptic station position from the agency table (about 1 arc-minute precision)."))
    pol = page_policy(
        sid, name="SHMÚ — webkamery (Slovenský hydrometeorologický ústav)", url=SHMU_PAGE, terms_url="https://opendata.shmu.sk/README.txt",
        license_="CC BY 4.0 covers opendata.shmu.sk only; the webcams on www.shmu.sk carry no licence",
        media_rights=("The images sit under /data/datawebcam/, which robots.txt disallows, and outside the CC BY 4.0 open-data "
                      "server: links to the camera pages only."),
        attribution="SHMÚ, www.shmu.sk", evidence=[SHMU_PAGE, "https://opendata.shmu.sk/README.txt", ISD_HISTORY], countries=["SK"],
        page_hosts=["www.shmu.sk"], role="station_location",
        raw=raw_files(out, sid, "webkamery.html") + raw_files(out, REFERENCE, "isd-history.csv"))
    pol["source"]["robots_note"] = "www.shmu.sk disallows /data/ (the image folder): no image is fetched or embedded"
    return {"status": "integrated", "country": "SK", "items": items, "policy": pol,
            "robots": "www.shmu.sk: camera pages allowed, /data/ (images) disallowed and not requested",
            "changes": [f"{len(items)} of {len(items) + len(unplaced)} cameras placed at their SHMÚ station"]
            + ([f"stations not in the agency table, not placed: {unplaced}"] if unplaced else [])}


def build_tirol_luft_livebilder(out):
    sid = "tirol_luft_livebilder"
    body = read_raw(out, sid, "livebilder.html")
    if body is None:
        return not_fetched(sid, "AT", "Land Tirol Luftgüte Livebilder", TIROL_LIVE, out, [TIROL_LIVE])
    items, unplaced, pages = [], [], []
    for cam in parse_tirol_livebilder(body):
        name = f"station-{cam['station_slug']}.html"
        st_body = read_raw(out, sid, name)
        st = tirol_station(st_body) if st_body else None
        if not st or st["lat"] is None:
            unplaced.append(cam["station_slug"])
            continue
        pages.append(name)
        items.append(item(sid, cam["key"], f"{st['name']} — Land Tirol Luftgüte webcam" + (f" ({cam['view']})" if cam["view"] else ""),
                          st["lat"], st["lng"], "AT", "Tirol", format_="official_page", official_page=cam["station_page"],
                          source_page=TIROL_LIVE, source_catalog=TIROL_LIVE, observed_at=when_of(out, sid, name),
                          coordinate_role="station_location", coordinate_crs="EPSG:4326",
                          coordinate_source=f"Land Tirol station page {cam['station_page']} (WGS84 {st['lat_dms']} N, {st['lng_dms']} E)",
                          direction=cam["view"]))
    pol = page_policy(
        sid, name="Land Tirol — Luftgüte Livebilder", url=TIROL_LIVE, terms_url="https://www.tirol.gv.at/impressum/",
        license_="All rights reserved (© Land Tirol); linking free",
        media_rights="'Das bloße Verlinken auf Inhalte dieser Webseite steht grundsätzlich jedermann frei'; re-use needs an "
                     "application. Links to the station pages only.",
        attribution="© Land Tirol", evidence=["https://www.tirol.gv.at/impressum/", TIROL_LIVE], countries=["AT"],
        page_hosts=["www.tirol.gv.at"], role="station_location", official_map_url=TIROL_LIVE,
        raw=raw_files(out, sid, "livebilder.html", *pages))
    return {"status": "integrated", "country": "AT", "items": items, "policy": pol,
            "robots": "www.tirol.gv.at: /umwelt/luftqualitaet/ allowed",
            "changes": ["each record links its station page (with the camera) instead of the shared Livebilder page"]
            + ([f"station pages without a published position, not placed: {unplaced}"] if unplaced else [])}


def build_omirl_arpal_webcams(out):
    sid = "omirl_arpal_webcams"
    body = read_raw(out, sid, "stations_webcam.json")
    if body is None:
        return not_fetched(sid, "IT", "OMIRL webcams", OMIRL_VIEWER, out, [OMIRL_LIST])
    when = when_of(out, sid, "stations_webcam.json")
    items = [item(sid, r["code"], f"OMIRL webcam {r['name']} ({r['municipality']})", r["lat"], r["lng"], "IT", "Liguria",
                  format_="official_page", official_page=OMIRL_VIEWER, source_page=OMIRL_VIEWER, source_catalog=OMIRL_LIST,
                  observed_at=when, coordinate_role="station_location", coordinate_crs="EPSG:4326",
                  coordinate_source="OMIRL station list (rest/stations/webcam lat/lon)", altitude_m=r["altitude_m"])
             for r in omirl_rows(body)]
    pol = page_policy(
        sid, name="ARPAL — OMIRL webcams (Regione Liguria)", url=OMIRL_VIEWER, catalog_url=OMIRL_LIST,
        terms_url="https://www.arpal.liguria.it/note-legali.html",
        license_="Creative Commons 2.5 Share Alike, non-commercial (ARPAL legal notes)",
        media_rights="Non-commercial share-alike and a time-stamped image path: viewer links only, no image.",
        attribution="ARPAL - OMIRL, Regione Liguria", evidence=["https://www.arpal.liguria.it/note-legali.html", OMIRL_LIST],
        countries=["IT"], page_hosts=["omirl.regione.liguria.it"], role="station_location", official_map_url=OMIRL_VIEWER,
        raw=raw_files(out, sid, "stations_webcam.json"))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "omirl.regione.liguria.it: no robots.txt (404)"}


def build_ie_marine_institute_smartbay(out):
    sid = "ie_marine_institute_smartbay"
    body = read_raw(out, sid, "dataset.html")
    point = smartbay_point(body) if body else None
    if point is None:
        return not_fetched(sid, "IE", "SmartBay Observatory video camera", SMARTBAY_DATASET, out, [SMARTBAY_DATASET])
    items = [item(sid, "smartbay-observatory-video", "SmartBay Observatory underwater video camera (Galway Bay)", point[0], point[1],
                  "IE", "Galway", format_="official_page", official_page=SMARTBAY_DATASET, source_page=SMARTBAY_DATASET,
                  source_catalog=SMARTBAY_DATASET, observed_at=when_of(out, sid, "dataset.html"), coordinate_role="camera_location",
                  coordinate_crs="EPSG:4326", coordinate_source="data.gov.ie dataset record, spatial coverage polygon (centre)",
                  identity_basis="official_dataset")]
    pol = page_policy(
        sid, name="Marine Institute — SmartBay Observatory video camera", url=SMARTBAY_DATASET, terms_url=SMARTBAY_DATASET,
        license_="CC BY 4.0 (dataset 'SmartBay Observatory Video Camera Data')", license_url=CC_BY_4,
        media_rights=("The CC BY 4.0 record covers the archived footage; the live stream's URL and licence are not published "
                      "(smartbay.marine.ie disallows all agents): a link to the dataset record only."),
        attribution="Marine Institute, SmartBay Observatory (CC BY 4.0)", evidence=[SMARTBAY_DATASET], countries=["IE"],
        page_hosts=["data.gov.ie"], role="camera_location", raw=raw_files(out, sid, "dataset.html"))
    return {"status": "integrated", "country": "IE", "items": items, "policy": pol,
            "robots": "data.gov.ie: dataset page allowed (/api/ disallowed, not requested); smartbay.marine.ie not requested",
            "changes": ["the page link is the data.gov.ie record (the live stream page is not published)"]}


def build_gefyra_rio_antirrio_cam(out):
    sid = "gefyra_rio_antirrio_cam"
    body = read_raw(out, sid, "live-camera.html")
    if body is None or "meteocam.gr/iframe.php" not in text(body):
        return not_fetched(sid, "GR", "Gefyra live camera", GEFYRA_PAGE, out, [GEFYRA_PAGE])
    items = [item(sid, "rio-antirrio-live-camera", "Rio–Antirrio bridge live camera (Gefyra S.A.)", GEFYRA_PLACE[0], GEFYRA_PLACE[1],
                  "GR", "Western Greece", format_="official_page", official_page=GEFYRA_PAGE, source_page=GEFYRA_PAGE,
                  source_catalog=GEFYRA_PAGE, observed_at=when_of(out, sid, "live-camera.html"),
                  coordinate_role="associated_feature", coordinate_crs="EPSG:4326",
                  coordinate_source=f"{REGISTER_REF}, gefyra_rio_antirrio_cam: the bridge named on the Gefyra camera page",
                  coordinate_note="Placed at the bridge the camera shows; the camera's own position is not published.")]
    pol = page_policy(
        sid, name="Γέφυρα Α.Ε. / Gefyra S.A. — Rio–Antirrio bridge live camera", url=GEFYRA_PAGE, terms_url="https://www.gefyra.gr/en/Terms/",
        license_="None ('©2026 All Rights Reserved')",
        media_rights="The camera is a third-party meteocam.gr embed; no reuse licence. Link only.",
        attribution="Γέφυρα Α.Ε. / Gefyra S.A. — live camera (meteocam.gr)", evidence=["https://www.gefyra.gr/en/Terms/", GEFYRA_PAGE],
        countries=["GR"], page_hosts=["www.gefyra.gr"], role="associated_feature", raw=raw_files(out, sid, "live-camera.html"))
    return {"status": "integrated", "country": "GR", "items": items, "policy": pol, "robots": "www.gefyra.gr: 'Allow: /'"}


def build_md_border_police_webcams(out):
    sid = "md_border_police_webcams"
    body = read_raw(out, sid, "camere-web.html")
    slugs = md_pages(body) if body else []
    ro = [s for s in slugs if s.startswith(MD_ROMANIA_FACING)]
    result = held_result(
        sid, "MD", "Poliția de Frontieră a Republicii Moldova — camere web (Romania-facing crossings)", MD_LIST,
        f"no official coordinates: the {len(ro)} pages at Moldova–Romania crossings ({', '.join(ro)}) name the crossing only; "
        "the Border Police site publishes no positions and the register gives none (round-2 hand-placement rule)",
        "an official position per crossing (operator map or an agency table), or the coordinator's approval to hand-place "
        "at the named crossings",
        [MD_LIST, "https://www.border.gov.md/camere-web/leuseni-iesire"], robots="www.border.gov.md: /camere-web allowed")
    result["policy"]["pages"] = ro
    return result


def build_md_border_police_webcams_ukraine_facing(out):
    body = read_raw(out, "md_border_police_webcams", "camere-web.html")
    slugs = md_pages(body) if body else []
    ua = [s for s in slugs if not s.startswith(MD_ROMANIA_FACING)]
    result = held_result(
        "md_border_police_webcams_ukraine_facing", "MD", "Poliția de Frontieră — camere web at Ukraine-facing or dual crossings",
        MD_LIST,
        f"Ukraine exclusion, decided conservatively: {len(ua)} pages at Moldova–Ukraine or dual crossings ({', '.join(ua)}) show "
        "Ukraine-bound traffic; the round holds them rather than decide how the martial-law exclusion applies",
        "the user's decision on Moldovan-side cameras facing Ukraine-bound traffic (and official positions)",
        [MD_LIST])
    result["policy"]["pages"] = ua
    return result


def no_official_position(sid, country, name, url, page_file, evidence, what):
    def build(out):
        fetched = read_raw(out, sid, page_file) is not None
        r = refused(out, sid)
        reason = (f"no official coordinates: {what}; the operator page publishes no position and no agency table or register "
                  "value covers it (round-2 hand-placement rule)") if fetched else f"page not fetched ({r['reason'] if r else 'no response'})"
        return held_result(sid, country, name, url, reason,
                           "an official position (operator map/coordinates or an agency table), or the coordinator's approval "
                           "to hand-place at the named place", evidence,
                           refused_hosts=[{"host": urlsplit(url).hostname, "reason": r["reason"]}] if r and not fetched else [],
                           robots="page allowed by robots.txt and read" if fetched else None)
    return build


def build_bafg_deutsches_eck_webcam(out):
    sid = "bafg_deutsches_eck_webcam"
    r = refused(out, sid)
    return held_result(
        sid, "DE", "BfG — Webcam Deutsches Eck", BAFG_PAGE,
        f"host refused: {r['reason'] if r else 'no response'} (robots.txt also answered 403); the camera page could not be "
        "confirmed this round", "the BfG page answering the collector (no bypass), then one hand-placed record",
        [BAFG_PAGE, "https://pegelonline.wsv.de/gast/start"],
        refused_hosts=[{"host": "www.bafg.de", "reason": r["reason"] if r else "HTTP 403"}])


def register_held(row):
    sid, country, name, url, kind, condition, evidence = row
    reasons = {
        "cannot_be_integrated": "the register marks it 'cannot be integrated': no list endpoint with coordinates",
        "low_confidence": "low confidence in the register (skipped this round)",
        "conditional": "conditional in the register: the camera host was unreachable and HTTP-only, low confidence",
        "sanctions": "held: the operator's sanctions exposure (Gazprom group) has not been assessed",
    }

    def build(out):
        return held_result(sid, country, name, url or "", reasons[kind], condition or "re-check", evidence or [url])
    return build


# Already held in scripts/webcam_source_policies.json with the same reasons: no fragment is written.
REPO_HELD = {
    "trafikverket_cameras": "the user's free API key (CC0 1.0 API licence confirmed by the register)",
    "arpae_camera_coastal": "no published image route",
    "hamburg_verkehrskameras": "no published image or stream host",
    "arpav_webcams": "no list endpoint (register: page_only at most)",
}


def no_position_sources():
    def spec(sid, country, name, url, page_file, what, *evidence):
        return sid, {"fetch": FETCH_PAGES[sid], "build": no_official_position(sid, country, name, url, page_file, [url, *evidence], what)}
    return dict([
        spec("plzen_city_webcams", "CZ", "Statutární město Plzeň — webkamery", PLZEN_PAGE, "webkamery.html",
             "7 city cameras at named squares and junctions"),
        spec("pkl_webcams", "PL", "Polskie Koleje Linowe — kamery online", PKL_LIST, "kamery-online.html",
             "7 cable-car venue pages (upper stations)"),
        spec("bansko_ski_webcams", "BG", "Bansko ski area — webcams", BANSKO_HOME, "home.html", "6 named ski-area webcam pages"),
        spec("port_of_helsinki_webcams", "FI", "Port of Helsinki — web cameras", HELSINKI_PORT, "web-camera-south-harbour.html",
             "6 harbour camera pages"),
        spec("visitfinland_live_streams", "FI", "Visit Finland — live streams (YouTube channels)", VISITFINLAND,
             "live-from-finland.html", "6 streams at named places"),
        spec("port_of_kiel_webcams", "DE", "Port of Kiel — webcams Schwedenkai / Hafenhaus", KIEL_PAGE, "webcam.html",
             "2 port cameras"),
        spec("oresundsbron_pylon_cams", "SE", "Øresundsbron — pylon cameras", ORESUND_PAGE, "pylonkamera.html",
             "2 pylon cameras (and the DK/SE side of each pylon)"),
        spec("turku_cathedral_tower_cams", "FI", "Turku Cathedral — tower camera", TURKU_PAGE, "tower-camera.html",
             "the cathedral tower camera"),
        spec("it_ski_bormio", "IT", "Bormio Ski — webcam page", BORMIO_PAGE, "webcam-bormio.html", "the resort webcam page"),
        spec("it_ski_campiglio_apt", "IT", "APT Madonna di Campiglio — webcam page", CAMPIGLIO_PAGE, "webcam.html",
             "the resort webcam page"),
        spec("it_ski_cervinia", "IT", "Cervino S.p.A. — webcam page", CERVINIA_PAGE, "webcam.html", "the resort webcam page"),
    ])


FETCH_PAGES = {
    "be_rmi_kmi_webcams": fetch_page("be_rmi_kmi_webcams", "webcams.html", RMI_INDEX),
    "shmu_webcams": fetch_page("shmu_webcams", "webkamery.html", SHMU_PAGE),
    "md_border_police_webcams": fetch_page("md_border_police_webcams", "camere-web.html", MD_LIST),
    "plzen_city_webcams": fetch_page("plzen_city_webcams", "webkamery.html", PLZEN_PAGE),
    "pkl_webcams": fetch_page("pkl_webcams", "kamery-online.html", PKL_LIST),
    "bansko_ski_webcams": fetch_page("bansko_ski_webcams", "home.html", BANSKO_HOME),
    "port_of_helsinki_webcams": fetch_page("port_of_helsinki_webcams", "web-camera-south-harbour.html", HELSINKI_PORT),
    "visitfinland_live_streams": fetch_page("visitfinland_live_streams", "live-from-finland.html", VISITFINLAND),
    "port_of_kiel_webcams": fetch_page("port_of_kiel_webcams", "webcam.html", KIEL_PAGE),
    "omirl_arpal_webcams": fetch_page("omirl_arpal_webcams", "stations_webcam.json", OMIRL_LIST),
    "oresundsbron_pylon_cams": fetch_page("oresundsbron_pylon_cams", "pylonkamera.html", ORESUND_PAGE),
    "ie_marine_institute_smartbay": fetch_page("ie_marine_institute_smartbay", "dataset.html", SMARTBAY_DATASET),
    "bafg_deutsches_eck_webcam": fetch_page("bafg_deutsches_eck_webcam", "webcam_node.html", BAFG_PAGE),
    "turku_cathedral_tower_cams": fetch_page("turku_cathedral_tower_cams", "tower-camera.html", TURKU_PAGE),
    "gefyra_rio_antirrio_cam": fetch_page("gefyra_rio_antirrio_cam", "live-camera.html", GEFYRA_PAGE),
    "it_ski_bormio": fetch_page("it_ski_bormio", "webcam-bormio.html", BORMIO_PAGE),
    "it_ski_campiglio_apt": fetch_page("it_ski_campiglio_apt", "webcam.html", CAMPIGLIO_PAGE),
    "it_ski_cervinia": fetch_page("it_ski_cervinia", "webcam.html", CERVINIA_PAGE),
}

SOURCES = {
    "ooe_land_webcams": {"fetch": fetch_ooe_land_webcams, "build": build_ooe_land_webcams},
    "oulu_kelikamerat": {"fetch": fetch_oulu_kelikamerat, "build": build_oulu_kelikamerat},
    "dwd_webcams": {"fetch": fetch_dwd_webcams, "build": build_dwd_webcams},
    "dhmz_webcams": {"fetch": fetch_dhmz_webcams, "build": build_dhmz_webcams},
    "wien_stadt_webcams": {"fetch": fetch_wien_stadt_webcams, "build": build_wien_stadt_webcams},
    REFERENCE: {"fetch": fetch_station_table},
    "arpa_fvg_webcam_directory": {"fetch": fetch_arpa_fvg_webcam_directory, "build": build_arpa_fvg_webcam_directory},
    "mk_state_roads_video_kameri": {"fetch": fetch_mk_state_roads_video_kameri, "build": build_mk_state_roads_video_kameri},
    "be_rmi_kmi_webcams": {"fetch": FETCH_PAGES["be_rmi_kmi_webcams"], "build": build_be_rmi_kmi_webcams},
    "shmu_webcams": {"fetch": FETCH_PAGES["shmu_webcams"], "build": build_shmu_webcams},
    "md_border_police_webcams": {"fetch": FETCH_PAGES["md_border_police_webcams"], "build": build_md_border_police_webcams},
    "md_border_police_webcams_ukraine_facing": {"build": build_md_border_police_webcams_ukraine_facing},
    "tirol_luft_livebilder": {"fetch": fetch_tirol_luft_livebilder, "build": build_tirol_luft_livebilder},
    "omirl_arpal_webcams": {"fetch": FETCH_PAGES["omirl_arpal_webcams"], "build": build_omirl_arpal_webcams},
    "ie_marine_institute_smartbay": {"fetch": FETCH_PAGES["ie_marine_institute_smartbay"], "build": build_ie_marine_institute_smartbay},
    "gefyra_rio_antirrio_cam": {"fetch": FETCH_PAGES["gefyra_rio_antirrio_cam"], "build": build_gefyra_rio_antirrio_cam},
    "bafg_deutsches_eck_webcam": {"fetch": FETCH_PAGES["bafg_deutsches_eck_webcam"], "build": build_bafg_deutsches_eck_webcam},
    **no_position_sources(),
    **{row[0]: {"build": register_held(row)} for row in REGISTER_HELD},
}

VIEWABLE = ("ooe_land_webcams", "oulu_kelikamerat", "dwd_webcams", "dhmz_webcams", "wien_stadt_webcams")

ETIQUETTE = [
    "Every request went through webcam_fetch.PoliteClient (robots.txt first, 1 s per host, HTTPS only); the Oulu list is one "
    "keyless GraphQL POST sent by post_json with the same rules (robots.txt answered 403 = no rules).",
    "Before choosing a station table, one probe read only robots.txt of oscar.wmo.int (Disallow: / for all, so WMO OSCAR was "
    "not used), www.ncei.noaa.gov, service.unece.org and unece.org (both 403, not used): four requests outside the collector.",
    "The DWD station table (1.39 MB) and the NOAA isd-history.csv (about 3 MB) were read whole: they are the official "
    "coordinate sources of the hand-placed stations.",
    "The DWD Hamburg-SO folder index (about 400 KB) and its newest .txt were read once to find the camera site; the .txt holds "
    "only EXIF data.",
    "Seven Land Tirol station pages were read for their published WGS84 positions (four publish one).",
]


# ======================================================================================
# Stage runner
# ======================================================================================


def check_one(client, out, sid, items, media_hosts):
    first = next((x for x in items if x["format"] == "snapshot"), None)
    if first is None:
        return None
    event = client.check_image(first["snapshot_url"], first["provider"], first["id"], media_hosts)
    C.write_json(Path(out) / "checks" / f"{sid}.snapshot.json", [event])
    return event


def check_summary(out, sid):
    events = C.read_json(Path(out) / "checks" / f"{sid}.snapshot.json")
    if not events:
        return None
    e = events[0]
    return {"kind": "image", "url": e.get("url"), "status": e.get("status"), "http": e.get("http_status"),
            "signature": e.get("signature"), "content_type": e.get("content_type"), "bytes_read": e.get("bytes_read"),
            "checked_at": e.get("checked_at"), "reason": e.get("inconclusive_reason")}


def build_stage(out, only=None):
    out = Path(out)
    report = {"family": FAMILY, "generated_at": F.now(), "register": REGISTER, "sources": [], "held": [], "hosts_refused": [],
              "already_held_in_repo": REPO_HELD, "etiquette": ETIQUETTE}
    for sid, spec in SOURCES.items():
        if "build" not in spec or (only and sid not in only):
            continue
        result = spec["build"](out)
        C.write_json(policy_path(out, sid), {sid: result["policy"]})
        row = {"id": sid, "country": result.get("country"), "status": result["status"],
               "policy_file": policy_path(out, sid).relative_to(out).as_posix()}
        if result["status"] == "integrated":
            items = result["items"]
            F.write_catalog(out / f"{sid}.json", sources=[sid], items=items, supersedes=result.get("supersedes", ()))
            formats = collections.Counter(x["format"] for x in items)
            row.update({"records": len(items), "viewable": formats["snapshot"] + formats["hls"], "page_only": formats["official_page"],
                        "input_file": f"{sid}.json", "check": check_summary(out, sid)})
        else:
            report["held"].append({"id": sid, "country": result.get("country"), "reason": result["policy"]["held_reason"]})
        for host in result.get("refused_hosts", ()):
            report["hosts_refused"].append({"source": sid, "host": host["host"], "reason": host["reason"]})
        row.update({k: result[k] for k in ("robots", "overlap", "changes", "notes") if result.get(k)})
        report["sources"].append(row)
    report["totals"] = {
        "integrated_sources": sum(r["status"] == "integrated" for r in report["sources"]),
        "viewable": sum(r.get("viewable", 0) for r in report["sources"]),
        "page_only": sum(r.get("page_only", 0) for r in report["sources"]),
        "held_fragments": len(report["held"])}
    C.write_json(out / "reports" / f"{FAMILY}.json", report)
    print(json.dumps(report["totals"]))
    print(json.dumps([(r["id"], r["status"], r.get("viewable"), r.get("page_only")) for r in report["sources"]
                      if r["status"] == "integrated"], ensure_ascii=False))
    return report


def check_stage(out, only=None):
    client = F.PoliteClient()
    for sid in VIEWABLE:
        if only and sid not in only:
            continue
        result = SOURCES[sid]["build"](out)
        if result["status"] != "integrated":
            print(f"{sid}: not integrated, no check")
            continue
        event = check_one(client, out, sid, result["items"], result["policy"]["media_hosts"])
        print(sid, json.dumps({k: (event or {}).get(k) for k in ("status", "http_status", "signature", "content_type",
                                                                   "inconclusive_reason")}))


def fetch_stage(out, only=None):
    client = F.PoliteClient()
    for sid, spec in SOURCES.items():
        fn = spec.get("fetch")
        if not fn or (only and sid not in only):
            continue
        n0 = len(client.log)
        fn(client, out)
        if len(client.log) > n0:
            log_path = raw_dir(out, sid) / "request_log.json"
            C.write_json(log_path, (C.read_json(log_path) or []) + client.log[n0:])
        print(sid, [(e["url"][:90], e["status"]) for e in client.log[n0:]], "refused" if refused(out, sid) else "")


def main(argv=None):
    global REFRESH
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output folder (webcam-inputs-2026-11)")
    ap.add_argument("stage", choices=("fetch", "check", "build"))
    ap.add_argument("--only", help="comma-separated source ids")
    ap.add_argument("--refresh", action="store_true", help="fetch: request again even when this round's raw file exists")
    args = ap.parse_args(argv)
    REFRESH = args.refresh
    only = set(args.only.split(",")) if args.only else None
    {"fetch": fetch_stage, "check": check_stage, "build": build_stage}[args.stage](args.out, only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
