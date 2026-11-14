#!/usr/bin/env python3
"""Collect the Iberian webcam sources of the 2026-11-14 round (stdlib only).

Network (scripts/webcam_fetch.py PoliteClient, with RFC 9309 wildcards added): one
camera-list request per source, saved with its receipt under OUT/raw/<source>/, the
dataset page of the two Madrid sources, and ONE image sample per new or upgraded
viewable provider. Build (offline): parse the saved lists with the pure functions
below and write OUT/<source>.json, OUT/policies/<source>.json,
OUT/checks/<source>.snapshot.json and OUT/reports/iberia.json.

  python scripts/collect_iberia.py --out DIR                        # lists, pages, samples, build
  python scripts/collect_iberia.py --out DIR --from-raw             # saved lists; pages and samples again
  python scripts/collect_iberia.py --out DIR --from-raw --offline   # saved lists, pages and samples: no network

Upgrades (madrid_traffic, euskadi_traffic, bizkaia) keep the provider_id scheme of the
records already in the catalogue and supersede the provider with its full current list;
an upgrade whose image sample fails is not written (the existing records stay as they are).
"""
from __future__ import annotations

import argparse
import collections
import copy
import csv
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as F  # noqa: E402

FAMILY = "iberia"
REVIEWED_AT = "2026-11-14"
POLICY_REGISTRY = Path(__file__).resolve().with_name("webcam_source_policies.json")

# ---------- camera lists ----------
MADRID_KML = "https://datos.madrid.es/egob/catalogo/202088-0-trafico-camaras.kml"
MADRID_DATASET_PAGE = "https://datos.madrid.es/en/dataset/202088-0-trafico-camaras"
MADRID_TERMS = "https://datos.madrid.es/pages/condiciones-generales-ayuntamiento-de-madrid"
CALLE30_XML = "https://datos.madrid.es/egob/catalogo/212166-7899870-trafico-calle30-camaras.xml"
CALLE30_DATASET_PAGE = "https://datos.madrid.es/en/dataset/212166-7899870-trafico-calle30-camaras"
CALLE30_NAP_PAGE = "https://nap.dgt.es/en/dataset/trafico-calle-30-camaras"
MALAGA_CSV = "https://datosabiertos.malaga.eu/recursos/transporte/trafico/da_camarasTrafico-4326.csv"
MALAGA_DATASET_PAGE = "https://datosabiertos.malaga.eu/dataset/camaras-de-trafico"
EUSKADI_API = "https://api.euskadi.eus/traffic/v1.0/cameras?_page={page}"
EUSKADI_GV_JSON = "https://opendata.euskadi.eus/contenidos/ds_localizaciones/camaras_trafico/opendata/camaras-trafico.json"
EUSKADI_TERMS = "https://opendata.euskadi.eus/general/-/informacion-legal-opendata/"
BIZKAIA_JSON = "https://www.opendatabizkaia.eus/es/dump/a0222f71-1b4a-4285-924d-b62f888eabe1/camaras-trafico?format=json"
BIZKAIA_DATASET_PAGE = "https://www.opendatabizkaia.eus/es/catalogo/trafico/recurso/camaras-trafico"
BIZKAIA_TERMS = "https://www.opendatabizkaia.eus/es/info/aviso-legal"
VALENCIA_QUERY = ("https://geoportal.valencia.es/server/rest/services/OPENDATA/Trafico/MapServer/190/query"
                  "?where=1%3D1&outFields=*&outSR=4326&f=json")
ANDORRA_PAGE = "https://www.mobilitat.ad/totes-les-cameres"
FGC_LIST_URLS = (  # every machine-readable route to the 30 records (Opendatasoft API and exports)
    "https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets/webcams-actives-tim/exports/json",
    "https://dadesobertes.fgc.cat/explore/dataset/webcams-actives-tim/download/?format=json",
)
EUSKADI_MAX_PAGES = 60
CC_BY_40 = "https://creativecommons.org/licenses/by/4.0/"

# Plausibility boxes (lat_min, lat_max, lng_min, lng_max): a sanity check, not a boundary.
BOX = {"madrid": (40.25, 40.65, -3.90, -3.50), "malaga": (36.60, 36.85, -4.65, -4.30),
       "euskadi": (42.40, 43.50, -3.50, -1.70), "bizkaia": (43.00, 43.50, -3.50, -2.40)}


def in_box(lat, lng, box):
    return lat is not None and lng is not None and box[0] <= lat <= box[1] and box[2] <= lng <= box[3]


# ---------- robots.txt: RFC 9309 wildcards on top of PoliteClient ----------
def robots_rules(text, user_agent=F.USER_AGENT):
    """(allow, pattern) rules of the group that applies to user_agent (RFC 9309 grouping)."""
    groups, agents, rules, last_agent = [], [], [], False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_agent and agents:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            last_agent = True
            continue
        last_agent = False
        if key in ("allow", "disallow") and agents and value:
            rules.append((key == "allow", value))
    if agents:
        groups.append((agents, rules))
    token = user_agent.split("/")[0].split()[0].lower()  # product token: "q-globe"
    own = [(a, rs) for a, rs in groups if any(x != "*" and x in token for x in a)]
    chosen = own or [(a, rs) for a, rs in groups if "*" in a]
    return [r for _, rs in chosen for r in rs]


def _robots_pattern(rule):
    anchored = rule.endswith("$")
    body = re.escape(rule[:-1] if anchored else rule).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def robots_allows(text, url, user_agent=F.USER_AGENT):
    """Longest matching rule wins, allow on a tie; '*' and '$' are honoured."""
    parts = urlsplit(url)
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    best = None
    for allow, rule in robots_rules(text, user_agent):
        if _robots_pattern(rule).match(path):
            key = (len(rule), allow)
            if best is None or key > best:
                best = key
    return best is None or best[1]


class StrictClient(F.PoliteClient):
    """PoliteClient whose robots check also applies RFC 9309 wildcards: urllib.robotparser
    reads 'Disallow: /explore/dataset/*/download' literally and would allow that path."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.robots_text, self.robots_error = {}, {}

    def _open(self, url, max_bytes, headers=None):
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        try:
            r = super()._open(url, max_bytes, headers)
        except Exception as exc:
            if parts.path == "/robots.txt":
                self.robots_error[base] = f"{type(exc).__name__}: {exc}"[:200]
            raise
        if parts.path == "/robots.txt":
            if 200 <= r["status"] < 300:
                self.robots_text[base] = r["body"].decode("utf-8", "replace")
            elif r["status"] >= 500:
                self.robots_error[base] = f"HTTP {r['status']}"
        return r

    def allowed(self, url):
        if not super().allowed(url):
            return False
        text = self.robots_text.get("{0.scheme}://{0.netloc}".format(urlsplit(url)))
        return text is None or robots_allows(text, url)

    def robots_note(self, url):
        base = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if base in self.robots_error:
            return f"robots.txt unreachable ({self.robots_error[base]}): treated as disallow (RFC 9309)"
        if base in self.robots_text:
            return "robots.txt read; " + ("allows" if self.allowed(url) else "disallows") + " this path (RFC 9309 wildcards)"
        return "no robots.txt (4xx): all allowed"


# ---------- fetch ----------
def _save(raw_dir, source, name, response):
    return F.save_raw(Path(raw_dir) / source, name, response)


def fetch_madrid_traffic(client, raw_dir):
    return [_save(raw_dir, "madrid_traffic", "trafico-camaras.kml", client.get(MADRID_KML))]


def fetch_madrid_calle30_cameras(client, raw_dir):
    return [_save(raw_dir, "madrid_calle30_cameras", "camaras.xml", client.get(CALLE30_XML))]


def fetch_malaga_traffic(client, raw_dir):
    return [_save(raw_dir, "malaga_traffic", "da_camarasTrafico-4326.csv", client.get(MALAGA_CSV))]


def fetch_bizkaia(client, raw_dir):
    return [_save(raw_dir, "bizkaia", "camaras-trafico.json", client.get(BIZKAIA_JSON, accept="application/json"))]


def fetch_euskadi_traffic(client, raw_dir):
    receipts = [_save(raw_dir, "euskadi_traffic", "camaras-trafico.json", client.get(EUSKADI_GV_JSON))]
    page, total = 1, 1
    while page <= total and page <= EUSKADI_MAX_PAGES:
        data, r = client.get_json(EUSKADI_API.format(page=page))
        receipts.append(_save(raw_dir, "euskadi_traffic", f"cameras_page_{page:03d}.json", r))
        total = int(data.get("totalPages") or 1)
        page += 1
    return receipts


def fetch_valencia_traffic(client, raw_dir):
    return [_save(raw_dir, "valencia_traffic", "layer190.json", client.get(VALENCIA_QUERY, accept="application/json"))]


def fetch_andorra_mobilitat(client, raw_dir):
    return [_save(raw_dir, "andorra_mobilitat", "totes-les-cameres.html", client.get(ANDORRA_PAGE))]


def fetch_fgc_tourism_webcams(client, raw_dir):
    """robots.txt first: the record list is only published on Opendatasoft API/export paths."""
    allowed = {url: client.allowed(url) for url in FGC_LIST_URLS}
    folder = Path(raw_dir) / "fgc_tourism_webcams"
    folder.mkdir(parents=True, exist_ok=True)
    note = {"checked_at": F.now(), "robots_allowed_rfc9309": allowed, "user_agent": F.USER_AGENT,
            "note": "No list request is made where robots.txt disallows it."}
    (folder / "robots_check.json").write_text(json.dumps(note, indent=1), encoding="utf-8")
    if not any(allowed.values()):
        raise F.Refused("robots.txt disallows every list route (/api/, /explore/dataset/*/download)")
    url = next(u for u, ok in allowed.items() if ok)
    return [_save(raw_dir, "fgc_tourism_webcams", "webcams-actives-tim.json", client.get(url))]


FETCHERS = {
    "madrid_traffic": fetch_madrid_traffic,
    "madrid_calle30_cameras": fetch_madrid_calle30_cameras,
    "malaga_traffic": fetch_malaga_traffic,
    "bizkaia": fetch_bizkaia,
    "euskadi_traffic": fetch_euskadi_traffic,
    "valencia_traffic": fetch_valencia_traffic,
    "andorra_mobilitat": fetch_andorra_mobilitat,
    "fgc_tourism_webcams": fetch_fgc_tourism_webcams,
}


def fetch_lists(client, out, only=None):
    """Fetch every list; a refusal is recorded (never worked around) and the source skipped."""
    status = {}
    for source, fetch in FETCHERS.items():
        if only and source not in only:
            continue
        try:
            status[source] = {"ok": True, "receipts": fetch(client, Path(out) / "raw")}
        except F.Refused as exc:
            status[source] = {"ok": False, "refused": str(exc)}
        except (OSError, ValueError) as exc:
            status[source] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        print(source, "ok" if status[source]["ok"] else status[source], flush=True)
    path = Path(out) / "raw" / "iberia_fetch_status.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    previous.update(status)
    path.write_text(json.dumps(previous, indent=1, ensure_ascii=False), encoding="utf-8")
    return status


# ---------- pure parsers (tests feed them saved fixtures) ----------
KML_NS = {"k": "http://earth.google.com/kml/2.2"}
IMG_SRC = re.compile(r"""src\s*=\s*["']?([^\s"'>]+)""", re.I)
POINT = re.compile(r"POINT\s*\(\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s*\)")


def _text(body):
    return body.decode("utf-8-sig") if isinstance(body, bytes) else body


def https_url(value, hosts):
    """value if it is an HTTPS URL on one of hosts, without credentials, spaces or fragment; else None."""
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        return None
    try:
        u = urlsplit(value)
        port = u.port
    except ValueError:
        return None
    if (u.scheme != "https" or (u.hostname or "") not in hosts or port not in (None, 443)
            or u.username is not None or u.password is not None or u.fragment):
        return None
    return value


def parse_madrid_kml(body):
    """Informo CCTV.kml: Numero (official 5-digit id), Nombre, WGS84 point, image in the description."""
    rows = []
    for pm in ET.fromstring(_text(body)).iter("{%s}Placemark" % KML_NS["k"]):
        data = {d.get("name"): (d.findtext("k:Value", default="", namespaces=KML_NS) or "").strip()
                for d in pm.iter("{%s}Data" % KML_NS["k"])}
        coords = (pm.findtext(".//k:Point/k:coordinates", default="", namespaces=KML_NS) or "").split(",")
        image = IMG_SRC.search(pm.findtext("k:description", default="", namespaces=KML_NS) or "")
        rows.append({"provider_id": data.get("Numero"), "name": data.get("Nombre"),
                     "lng": float(coords[0]) if len(coords) >= 2 else None,
                     "lat": float(coords[1]) if len(coords) >= 2 else None,
                     "image": image.group(1) if image else None})
    return rows


def calle30_image(url_field, fichero):
    """The XML's scheme-less 'www.mc30.es/xml-data/imagenes_camaras/X.jpg' as the HTTPS URL the www
    host redirects to (https://mc30.es/...), the host that serves the list itself; else None."""
    value = (url_field or "").strip()
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?mc30\.es(/xml-data/imagenes_camaras/[A-Za-z0-9_.+()-]+\.jpg)", value)
    if not m or m.group(1).rsplit("/", 1)[1] != (fichero or "").strip():
        return None
    return "https://mc30.es" + m.group(1)


def calle30_id(nombre):
    """Stable provider_id from the camera name ('M30-PK10+900C(M.ALVARO)' -> 'M30-PK10_900C_M.ALVARO')."""
    value = (nombre or "").strip().replace("+", "_").replace("(", "_").replace(")", "")
    return re.sub(r"[^A-Za-z0-9:_.-]", "_", value)


def parse_calle30_xml(body):
    rows = []
    for cam in ET.fromstring(_text(body)).iter("Camara"):
        lat, lng = cam.findtext("Posicion/Latitud"), cam.findtext("Posicion/Longitud")
        nombre = (cam.findtext("Nombre") or "").strip()
        rows.append({"provider_id": calle30_id(nombre), "official_name": nombre,
                     "lat": float(lat) if lat else None, "lng": float(lng) if lng else None,
                     "image": calle30_image(cam.findtext("URL"), cam.findtext("Fichero")),
                     "ip_published": bool((cam.findtext("IP") or "").strip())})
    return rows


def parse_malaga_csv(body):
    rows = []
    for r in csv.DictReader(io.StringIO(_text(body))):
        m = POINT.fullmatch((r.get("SDOGEOMETRIA") or "").strip())
        rows.append({"provider_id": (r.get("ID") or "").strip(), "name": (r.get("NOMBRE") or "").strip(),
                     "description": (r.get("DESCRIPCION") or "").strip(), "address": (r.get("DIRECCION") or "").strip(),
                     "lng": float(m.group(1)) if m else None, "lat": float(m.group(2)) if m else None,
                     "page": (r.get("URL") or "").strip(), "image": (r.get("URLIMAGEN") or "").strip()})
    return rows


def parse_jsonp(body):
    text = _text(body).strip()
    if not text.startswith(("[", "{")):
        text = text[text.index("(") + 1:text.rindex(")")]
    return json.loads(text)


def parse_euskadi_pages(pages):
    """[(page_url, body)] of api.euskadi.eus/traffic/v1.0/cameras -> cameras, checking the declared total."""
    cameras, total = [], None
    for url, body in pages:
        page = json.loads(_text(body))
        total = page.get("totalItems") if total is None else total
        cameras.extend({**c, "_page_url": url} for c in page["cameras"])
    if total is not None and len(cameras) != total:
        raise ValueError(f"euskadi API: {len(cameras)} cameras read, {total} declared")
    return cameras


def parse_bizkaia_dump(body):
    doc = json.loads(_text(body))
    names = [f["id"] for f in doc["fields"]]
    return [dict(zip(names, rec)) for rec in doc["records"]]


def parse_andorra_page(body):
    """Cameras with coordinates published in the page's HTML (data-lat/data-lng pairs); [] when none."""
    text = _text(body)
    pairs = re.findall(r'data-lat(?:itude)?="(-?[0-9.]+)"[^>]*data-(?:lng|lon|longitude)="(-?[0-9.]+)"', text)
    images = re.findall(r'(?:src|data-src)="(https://imgs\.mobilitat\.ad/[^"]+)"', text)
    return {"coordinates": [(float(a), float(b)) for a, b in pairs], "images": images}


def _num(value):
    if value in (None, "", "NULL"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _null(value):
    return None if value in (None, "", "NULL") else str(value).strip()


def check_ok(event):
    """An image sample counts only with a 2xx answer and a JPEG/PNG signature."""
    return bool(event) and event.get("status") == "image_signature_confirmed" and 200 <= (event.get("http_status") or 0) < 300


def page_ok(receipt):
    return bool(receipt) and receipt.get("status") == 200 and str(receipt.get("content_type") or "").startswith("text/html")


# ---------- items ----------
def _base(provider, provider_id, name, lat, lng, region, observed_at, **extra):
    item = {"provider": provider, "provider_id": provider_id, "id": f"{provider}:{provider_id}", "name": name,
            "lat": lat, "lng": lng, "country": "ES", "region": region, "stream_url": None, "snapshot_url": None,
            "observed_at": observed_at, "health": {"status": "unverified"}}
    item.update(extra)
    return item


def _snapshot(item, url, official_page):
    item.update({"format": "snapshot", "snapshot_url": url, "official_page": official_page,
                 "rights_status": "official_public_feed"})
    return item


def _page(item, official_page, reference=None):
    item.update({"format": "official_page", "official_page": official_page, "rights_status": "official_page_only"})
    if reference:
        item["reference_url"] = reference
    return item


def madrid_items(rows, observed_at, upgrade, official_page, source_page):
    items, skipped = [], []
    for r in rows:
        pid = r["provider_id"] or ""
        if not re.fullmatch(r"[0-9]{5}", pid) or not in_box(r["lat"], r["lng"], BOX["madrid"]):
            skipped.append({"provider_id": pid, "reason": "no official 5-digit id or implausible coordinates"})
            continue
        item = _base("madrid_traffic", pid, r["name"] or pid, r["lat"], r["lng"], "Madrid", observed_at,
                     coordinate_role="camera_location", coordinate_crs="EPSG:4326", source_page=source_page,
                     source_catalog=MADRID_KML, minimum_refresh_seconds=300)
        image = https_url(r["image"], {"informo.madrid.es"})
        if upgrade and image:
            items.append(_snapshot(item, image, official_page))
        else:
            items.append(_page(item, official_page, r["image"]))
    return items, skipped


def calle30_items(rows, observed_at, official_page, source_page):
    items, skipped, seen = [], [], set()
    for r in rows:
        pid = r["provider_id"]
        if r["ip_published"]:
            skipped.append({"provider_id": pid, "reason": "device address published"})
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,80}", pid or "") or not r["image"] \
                or not in_box(r["lat"], r["lng"], BOX["madrid"]):
            skipped.append({"provider_id": pid, "reason": "no id, image or plausible coordinates"})
            continue
        if pid in seen:
            skipped.append({"provider_id": pid, "reason": "listed twice (same camera, same image file)"})
            continue
        seen.add(pid)
        item = _base("madrid_calle30_cameras", pid, f"Calle 30 (M-30) · {r['official_name']}", r["lat"], r["lng"],
                     "Madrid", observed_at, official_name=r["official_name"], coordinate_role="camera_location",
                     coordinate_crs="unspecified_geographic",
                     coordinate_note="Publisher latitude/longitude in decimal degrees; datum not declared.",
                     road="M-30", source_page=source_page, source_catalog=CALLE30_XML, minimum_refresh_seconds=300)
        items.append(_snapshot(item, r["image"], official_page))
    return items, skipped


def malaga_items(rows, observed_at):
    items, skipped = [], []
    for r in rows:
        pid, image = r["provider_id"], https_url(r["image"], {"ctraficomovilidad.malaga.eu"})
        page = https_url(r["page"], {"movilidad.malaga.eu"})
        if not re.fullmatch(r"[0-9]{1,12}", pid or "") or not image or not in_box(r["lat"], r["lng"], BOX["malaga"]):
            skipped.append({"provider_id": pid, "reason": "no id, HTTPS image or plausible coordinates"})
            continue
        item = _base("malaga_traffic", pid, r["name"] or pid, r["lat"], r["lng"], "Málaga", observed_at,
                     coordinate_role="camera_location", coordinate_crs="EPSG:4326",
                     address=r["address"] or None, description=r["description"] or None,
                     source_page=MALAGA_DATASET_PAGE, source_catalog=MALAGA_CSV)
        items.append(_snapshot(item, image, page))
    return items, skipped


EUSKADI_KEPT = {"1": "Gobierno Vasco (Dirección de Tráfico)", "5": "Ayuntamiento de Bilbao",
                "7": "Ayuntamiento de Donostia-San Sebastián"}
EUSKADI_ELSEWHERE = {"2": "bizkaia provider (opendatabizkaia.eus)", "6": "vitoria provider (vitoria-gasteiz.org)"}
EUSKADI_PAGES = {"1": "https://www.trafikoa.eus/", "5": "https://www.bilbao.eus/opendata/es/catalogo/dato-camaras-trafico",
                 "7": "https://www.trafikoa.eus/"}
EUSKADI_NOTE = ("Publisher geographic coordinates are preserved; exact datum is not declared in the collected contract. "
                "Not suitable for precision matching.")


def euskadi_items(cameras, licensed_urls, observed_at, upgrade):
    """Every camera of the current euskadi_traffic list: Gobierno Vasco cameras whose image URL is a field of
    the CC BY 4.0 dataset become snapshots (when upgrade), Bilbao and Donostia stay page links."""
    items, skipped = [], []
    for c in cameras:
        src, cam = str(c.get("sourceId")), str(c.get("cameraId"))
        pid, image = f"{src}.{cam}", c.get("urlImage")
        lat, lng = _num(c.get("latitude")), _num(c.get("longitude"))
        if src not in EUSKADI_KEPT:
            skipped.append({"provider_id": pid, "reason": "listed under " + EUSKADI_ELSEWHERE.get(src, f"API source {src}")})
            continue
        if not image or any(ch.isspace() for ch in image) or urlsplit(image).scheme not in ("http", "https"):
            skipped.append({"provider_id": pid, "reason": "no usable image URL published" + (f" ({image!r})" if image else "")})
            continue
        if not in_box(lat, lng, BOX["euskadi"]):
            skipped.append({"provider_id": pid, "reason": f"implausible coordinates {lat},{lng}"})
            continue
        item = _base("euskadi_traffic", pid, str(c.get("cameraName") or pid).strip(), lat, lng, "Euskadi", observed_at,
                     identity_basis="official_record_id", coordinate_role="approximate",
                     coordinate_crs="unspecified_geographic", coordinate_note=EUSKADI_NOTE,
                     source_page="https://opendata.euskadi.eus/api-traffic/?api=traffic", source_catalog=c["_page_url"],
                     road=_null(c.get("road")), kilometer=_null(c.get("kilometer")), upstream_source_id=src,
                     upstream_operator=EUSKADI_KEPT[src], page_link_scope="provider_camera_directory")
        gv_image = https_url(image, {"www.trafikoa.eus"}) if src == "1" and image in licensed_urls else None
        if upgrade and gv_image:
            item.update(upstream_metadata_license="CC-BY-4.0", licensed_dataset=EUSKADI_GV_JSON, minimum_refresh_seconds=180)
            items.append(_snapshot(item, gv_image, EUSKADI_PAGES[src]))
        else:
            item["upstream_metadata_license"] = "CC-BY-3.0-ES" if src == "5" else "Open Data Euskadi terms"
            items.append(_page(item, EUSKADI_PAGES[src], image))
    return items, skipped


BIZKAIA_NOTE = ("Explicit COORD_GEOGRAFICAS_* columns; exact datum unspecified. Misleading metric latitude/longitude "
                "columns are not used. No precision matching.")


def bizkaia_image(url, https_rewrite_verified):
    """(snapshot URL or None, note). The 48 http URLs become https on the same host only when verified."""
    if https_url(url, {"www.bizkaimove.eus"}):
        return url, None
    m = re.fullmatch(r"http://www\.bizkaimove\.eus(/camaras/cam[0-9]+\.jpg)", url or "")
    if m and https_rewrite_verified:
        return "https://www.bizkaimove.eus" + m.group(1), "published as http; served over https by the same host (sample verified)"
    return None, None


def bizkaia_items(rows, observed_at, upgrade, https_rewrite_verified):
    items, skipped = [], []
    for r in rows:
        url = _null(r.get("URL"))
        if not url:
            continue  # the provider only lists cameras that publish an image link (unchanged rule)
        pid = str(r.get("_id"))
        lat = _num(r.get("KOORD_GEOGRAFIKOAK_LATITUDEA/COORD_GEOGRAFICAS_LATITUD"))
        lng = _num(r.get("KOORD_GEOGRAFIKOAK_LONGITUDEA/COORD_GEOGRAFICAS_LONGITUD"))
        if not in_box(lat, lng, BOX["bizkaia"]):
            skipped.append({"provider_id": pid, "reason": f"implausible coordinates {lat},{lng}"})
            continue
        item = _base("bizkaia", pid, _null(r.get("IZENA/NOMBRE")) or pid, lat, lng, "Bizkaia", observed_at,
                     identity_basis="official_record_id", coordinate_role="approximate",
                     coordinate_crs="unspecified_geographic", coordinate_note=BIZKAIA_NOTE,
                     source_page=BIZKAIA_DATASET_PAGE, source_catalog=BIZKAIA_JSON,
                     road=_null(r.get("ERREPIDEA/CARRETERA")), direction=_null(r.get("NORANZKOA/SENTIDO")),
                     kilometer=_null(r.get("PK")), page_link_scope="provider_camera_directory")
        image, note = bizkaia_image(url, https_rewrite_verified)
        if upgrade and image:
            if note:
                item["snapshot_url_note"] = note
            items.append(_snapshot(item, image, BIZKAIA_DATASET_PAGE))
        else:
            items.append(_page(item, BIZKAIA_DATASET_PAGE, url))
    return items, skipped


# ---------- policies ----------
def existing_policy(pid, registry=POLICY_REGISTRY):
    return copy.deepcopy(json.loads(Path(registry).read_text(encoding="utf-8"))[pid])


def _hosts(items, field):
    return sorted({urlsplit(i[field]).hostname for i in items if i.get(field)})


def _formats(items):
    return sorted({i["format"] for i in items})


def _review(source, viewable, evidence, catalog_url):
    source.update({"catalog_url": catalog_url, "reviewed_at": REVIEWED_AT, "evidence": evidence,
                   "review_status": "reviewed_for_snapshot_and_reference_use" if viewable
                   else "reviewed_for_external_references_only",
                   "review_note": "Approved scope is limited to the formats and origins in this registry; "
                                  "no upstream liveness claim is accepted."})
    return source


def madrid_policy(items, source_url_page):
    p = existing_policy("madrid_traffic")
    s = p["source"]
    media = ("The CC BY 4.0 dataset 'Tráfico. Cámaras' embeds each camera image (informo.madrid.es/cameras/CamaraNNNNN.jpg) "
             "and states that an image capture is included every five minutes; the city's general conditions allow "
             "commercial and non-commercial reuse of information in any medium, citing the source. Images shown "
             "unmodified, never stored.")
    s.update({"name": "Ayuntamiento de Madrid — Tráfico. Cámaras", "url": source_url_page, "terms_url": MADRID_TERMS,
              "metadata_license": "CC-BY-4.0", "license": "CC-BY-4.0", "license_url": CC_BY_40,
              "media_rights": media, "rights_note": media,
              "attribution": "Origen de los datos: Ayuntamiento de Madrid – Tráfico. Cámaras (datos.madrid.es), CC BY 4.0",
              "rights_status": "official_public_feed", "allowed_hosts": ["informo.madrid.es"],
              "official_page_hosts": _hosts(items, "official_page"), "minimum_refresh_seconds": 300})
    _review(s, True, [MADRID_TERMS, MADRID_DATASET_PAGE, MADRID_KML], MADRID_KML)
    p.update({"media_hosts": ["informo.madrid.es"], "page_hosts": _hosts(items, "official_page"),
              "formats": _formats(items), "countries": ["ES"], "coordinate_role": "camera_location"})
    return p


def calle30_policy(items, source_url_page):
    media = ("The CC BY dataset 'Tráfico. Calle 30. Cámaras' is described as 'data and images from traffic control "
             "cameras in M-30' and lists each image file; Madrid's general conditions allow commercial and "
             "non-commercial reuse, citing the source. Images shown unmodified, never stored.")
    s = {"id": "madrid_calle30_cameras", "name": "Madrid Calle 30 (M-30) — traffic cameras", "url": source_url_page,
         "terms_url": MADRID_TERMS, "metadata_license": "CC-BY", "license": "CC-BY (Creative Commons Attribution; "
         "Ayuntamiento de Madrid general reuse conditions)", "license_url": MADRID_TERMS,
         "media_rights": media, "rights_note": media,
         "attribution": "Origen de los datos: Ayuntamiento de Madrid / Madrid Calle 30 – Tráfico. Calle 30. Cámaras, CC BY",
         "rights_status": "official_public_feed", "allowed_hosts": ["mc30.es"],
         "official_page_hosts": _hosts(items, "official_page"), "minimum_refresh_seconds": 300}
    _review(s, True, [CALLE30_NAP_PAGE, MADRID_TERMS, CALLE30_XML], CALLE30_XML)
    return {"source": s, "media_hosts": ["mc30.es"], "page_hosts": _hosts(items, "official_page"),
            "formats": _formats(items), "countries": ["ES"], "operator_hints": ["calle 30", "mc30"],
            "coordinate_role": "camera_location"}


def malaga_policy(items):
    media = ("Dataset field URLIMAGEN publishes each camera's image URL as part of the openly licensed dataset "
             "(licence title CC BY 4.0, licence link CC BY-SA 4.0: both allow commercial use). Condition: images "
             "displayed unmodified, with attribution; never stored or edited.")
    s = {"id": "malaga_traffic", "name": "Ayuntamiento de Málaga — cámaras de tráfico", "url": MALAGA_DATASET_PAGE,
         "terms_url": MALAGA_DATASET_PAGE, "metadata_license": "CC-BY-4.0 (title) / CC-BY-SA-4.0 (link)",
         "license": "CC-BY-4.0 per licence title; the link points to CC-BY-SA-4.0 (apply the stricter)",
         "license_url": "https://creativecommons.org/licenses/by-sa/4.0/", "media_rights": media, "rights_note": media,
         "attribution": "Ayuntamiento de Málaga – Cámaras de tráfico (datosabiertos.malaga.eu), CC BY 4.0 / CC BY-SA 4.0",
         "display_condition": "display unmodified with attribution",
         "rights_status": "official_public_feed", "allowed_hosts": ["ctraficomovilidad.malaga.eu"],
         "official_page_hosts": _hosts(items, "official_page")}
    _review(s, True, [MALAGA_DATASET_PAGE, MALAGA_CSV], MALAGA_CSV)
    return {"source": s, "media_hosts": ["ctraficomovilidad.malaga.eu"], "page_hosts": _hosts(items, "official_page"),
            "formats": _formats(items), "countries": ["ES"], "operator_hints": [], "coordinate_role": "camera_location"}


def euskadi_policy(items):
    p = existing_policy("euskadi_traffic")
    s = p["source"]
    media = ("Gobierno Vasco cameras (API source 1): the CC BY 4.0 dataset 'Cámaras de tráfico de Euskadi' lists each "
             "camera's image URL (URLCAM, refreshed every 3 minutes) and the Open Data Euskadi legal notice puts Basque "
             "Government content under the licence shown: displayed unmodified as snapshots. Ayuntamiento de Bilbao "
             "(source 5) and Donostia-San Sebastián (source 7) cameras: image rights not established; page links only.")
    s.update({"name": "Open Data Euskadi — traffic cameras (Gobierno Vasco snapshots; Bilbao and Donostia links)",
              "metadata_license": "CC-BY-4.0 (Gobierno Vasco dataset); upstream Bilbao catalogue CC-BY-3.0-ES",
              "license": "CC-BY-4.0 (Gobierno Vasco cameras); Bilbao and Donostia records are links only",
              "license_url": CC_BY_40, "media_rights": media, "rights_note": media,
              "attribution": "Fuente: Open Data Euskadi – Gobierno Vasco, Cámaras de tráfico de Euskadi, CC BY 4.0; "
                             "page links: Ayuntamiento de Bilbao, Ayuntamiento de Donostia-San Sebastián",
              "rights_status": "official_public_feed", "allowed_hosts": ["www.trafikoa.eus"],
              "official_page_hosts": _hosts(items, "official_page"), "minimum_refresh_seconds": 180})
    _review(s, True, [EUSKADI_TERMS, "https://opendata.euskadi.eus/catalogo/-/camaras-de-trafico-de-euskadi/", EUSKADI_GV_JSON],
            EUSKADI_API.format(page=1))
    p.update({"media_hosts": ["www.trafikoa.eus"], "page_hosts": _hosts(items, "official_page"),
              "formats": _formats(items), "countries": ["ES"]})
    return p


def bizkaia_policy(items):
    p = existing_policy("bizkaia")
    s = p["source"]
    media = ("The CC BY 4.0 dataset 'Cámaras de tráfico' includes 'el enlace directo a la imagen de la cámara' as a "
             "declared field; the open-data legal notice allows commercial or non-commercial use citing the source. "
             "Published http image links are served over https by the same host (one sample verified). Images "
             "displayed unmodified, never stored.")
    s.update({"name": "Diputación Foral de Bizkaia — cámaras de tráfico", "terms_url": BIZKAIA_TERMS,
              "metadata_license": "CC-BY-4.0", "license": "CC-BY-4.0", "license_url": CC_BY_40,
              "media_rights": media, "rights_note": media,
              "attribution": "Fuente de los datos: www.opendatabizkaia.eus – Diputación Foral de Bizkaia, CC BY 4.0",
              "rights_status": "official_public_feed", "allowed_hosts": ["www.bizkaimove.eus"],
              "official_page_hosts": _hosts(items, "official_page")})
    _review(s, True, [BIZKAIA_DATASET_PAGE, BIZKAIA_TERMS, BIZKAIA_JSON], BIZKAIA_JSON)
    p.update({"media_hosts": ["www.bizkaimove.eus"], "page_hosts": _hosts(items, "official_page"),
              "formats": _formats(items), "countries": ["ES"]})
    return p


def held_policy(pid, name, url, reason, until, evidence):
    return {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
            "source": {"id": pid, "name": name, "url": url}}


DGT_HELD = held_policy(
    "dgt_nap_cameras", "DGT traffic cameras (DATEX II v3.7 DevicePublication)", "https://nap.dgt.es/en/dataset/camaras-dgt-datex2-v3-7",
    "Publisher confirmation pending: the dataset is CC BY on the national access point, but the linked aviso legal "
    "is generic; an e-mail to nap@dgt.es must confirm that the CC BY dataset licence covers the camera images "
    "(etraffic.dgt.es) before they are shown.",
    "written confirmation from nap@dgt.es that the CC BY licence covers the images",
    ["https://nap.dgt.es/en/dataset/camaras-dgt-datex2-v3-7", "https://www.dgt.es/contenido/aviso-legal/"])


# ---------- network stage: robots audit, dataset pages, one image sample per provider ----------
def sample_targets(parsed):
    """(provider, record_id, url, hosts) per viewable candidate; deterministic: lowest provider_id."""
    targets = {}
    if "madrid_traffic" in parsed:
        r = min((r for r in parsed["madrid_traffic"]["rows"] if https_url(r["image"], {"informo.madrid.es"})
                 and re.fullmatch(r"[0-9]{5}", r["provider_id"] or "")),
                key=lambda r: r["provider_id"], default=None)
        if r:
            targets["madrid_traffic"] = (f"madrid_traffic:{r['provider_id']}", r["image"], ["informo.madrid.es"])
    if "madrid_calle30_cameras" in parsed:
        # The register sampled a plain file name (09NC39TV01.jpg); this one takes a name with '+' and '()'.
        rows = [r for r in parsed["madrid_calle30_cameras"]["rows"] if r["image"]]
        special = [r for r in rows if re.search(r"[^A-Za-z0-9_-]", r["official_name"])]
        r = min(special or rows, key=lambda r: r["provider_id"], default=None)
        if r:
            targets["madrid_calle30_cameras"] = (f"madrid_calle30_cameras:{r['provider_id']}", r["image"], ["mc30.es"])
    if "malaga_traffic" in parsed:
        r = min((r for r in parsed["malaga_traffic"]["rows"] if https_url(r["image"], {"ctraficomovilidad.malaga.eu"})
                 and r["provider_id"].isdigit()),
                key=lambda r: int(r["provider_id"]), default=None)
        if r:
            targets["malaga_traffic"] = (f"malaga_traffic:{r['provider_id']}", r["image"], ["ctraficomovilidad.malaga.eu"])
    if "euskadi_traffic" in parsed:
        gv = [c for c in parsed["euskadi_traffic"]["cameras"] if str(c.get("sourceId")) == "1"
              and c.get("urlImage") in parsed["euskadi_traffic"]["licensed_urls"] and https_url(c["urlImage"], {"www.trafikoa.eus"})
              and str(c.get("cameraId")).isdigit()]
        c = min(gv, key=lambda c: int(c["cameraId"]), default=None)
        if c:
            targets["euskadi_traffic"] = (f"euskadi_traffic:1.{c['cameraId']}", c["urlImage"], ["www.trafikoa.eus"])
    if "bizkaia" in parsed:
        # The one sample tests the http->https rewrite, so it is taken from an http row.
        rows = [r for r in parsed["bizkaia"]["rows"] if bizkaia_image(_null(r.get("URL")), True)[1]]
        r = min(rows, key=lambda r: int(r["_id"]), default=None)
        if r:
            targets["bizkaia"] = (f"bizkaia:{r['_id']}", bizkaia_image(_null(r["URL"]), True)[0], ["www.bizkaimove.eus"])
    return targets


def network_stage(client, out, parsed):
    raw = Path(out) / "raw"
    audit = {}
    for source, info in parsed.items():
        for url in info.get("list_urls", []):
            audit[url] = {"source": source, "allowed": client.allowed(url), "note": client.robots_note(url)}
    for url in FGC_LIST_URLS:
        audit[url] = {"source": "fgc_tourism_webcams", "allowed": client.allowed(url), "note": client.robots_note(url)}
    (raw / "iberia_robots_audit.json").write_text(json.dumps({"checked_at": F.now(), "user_agent": F.USER_AGENT,
                                                               "urls": audit}, indent=1), encoding="utf-8")
    for source, page in (("madrid_traffic", MADRID_DATASET_PAGE), ("madrid_calle30_cameras", CALLE30_DATASET_PAGE)):
        if source not in parsed:
            continue
        try:
            _save(raw, source, "dataset_page.html", client.get(page, max_bytes=2 * 1024 * 1024))
        except (F.Refused, OSError) as exc:
            (raw / source / "dataset_page.error.json").write_text(json.dumps({"url": page, "error": str(exc)[:300]}),
                                                                  encoding="utf-8")
    for provider, (record_id, url, hosts) in sample_targets(parsed).items():
        event = client.check_image(url, provider, record_id, hosts)
        event["robots_note"] = client.robots_note(url)
        if event.get("http_status") is None and "unreachable" in event["robots_note"]:
            # PoliteClient reports any robots denial the same way; say what happened: no image request.
            event["inconclusive_reason"] = "timeout: " + event["robots_note"] + "; the image was not requested"
        path = Path(out) / "checks" / f"{provider}.snapshot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([event], indent=1, ensure_ascii=False), encoding="utf-8")
        print("check", provider, event["status"], event.get("http_status"), event.get("signature"), flush=True)


# ---------- build ----------
def _read(path):
    return Path(path).read_bytes() if Path(path).exists() else None


def _receipt(path):
    p = Path(str(path) + ".receipt.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def parse_raw(raw):
    """Saved lists -> parsed rows per source (sources without a saved list are absent)."""
    raw, parsed = Path(raw), {}
    specs = {"madrid_traffic": ("trafico-camaras.kml", parse_madrid_kml),
             "madrid_calle30_cameras": ("camaras.xml", parse_calle30_xml),
             "malaga_traffic": ("da_camarasTrafico-4326.csv", parse_malaga_csv),
             "bizkaia": ("camaras-trafico.json", parse_bizkaia_dump)}
    for source, (name, parse) in specs.items():
        body = _read(raw / source / name)
        if body is not None:
            rec = _receipt(raw / source / name)
            parsed[source] = {"rows": parse(body), "receipt": rec, "list_urls": [rec["url"], rec["final_url"]]}
    pages = sorted((raw / "euskadi_traffic").glob("cameras_page_[0-9][0-9][0-9].json"))
    gv = _read(raw / "euskadi_traffic" / "camaras-trafico.json")
    if pages and gv is not None:
        receipts = [_receipt(p) for p in pages]
        cameras = parse_euskadi_pages([(r["url"], p.read_bytes()) for r, p in zip(receipts, pages)])
        gv_rec = _receipt(raw / "euskadi_traffic" / "camaras-trafico.json")
        parsed["euskadi_traffic"] = {"cameras": cameras, "licensed_urls": {g["URLCAM"] for g in parse_jsonp(gv)},
                                     "licensed_count": len(parse_jsonp(gv)), "receipt": receipts[0],
                                     "list_urls": [gv_rec["url"], receipts[0]["url"]]}
    body = _read(raw / "andorra_mobilitat" / "totes-les-cameres.html")
    if body is not None:
        rec = _receipt(raw / "andorra_mobilitat" / "totes-les-cameres.html")
        parsed["andorra_mobilitat"] = {"page": parse_andorra_page(body), "receipt": rec, "list_urls": [rec["url"]]}
    return parsed


def _checks(out, provider):
    p = Path(out) / "checks" / f"{provider}.snapshot.json"
    events = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    return events[0] if events else None


def _json(path, default=None):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default


def build(out, parsed):
    """Write inputs and policy fragments; return the per-source report entries."""
    out, raw = Path(out), Path(out) / "raw"
    fetch_status = _json(raw / "iberia_fetch_status.json", {})
    audit = _json(raw / "iberia_robots_audit.json", {}).get("urls", {})
    report, policies, held = {}, {}, {}

    def emit(source, items, policy, supersedes=(), skipped=(), event=None, notes=()):
        path = out / f"{source}.json"
        F.write_catalog(path, [source], items, supersedes=supersedes)
        policies[source] = policy
        report[source] = {"id": source, "country": "ES", "input_file": path.name,
                          "viewable": sum(i["format"] != "official_page" for i in items),
                          "page_only": sum(i["format"] == "official_page" for i in items),
                          "supersedes": list(supersedes), "skipped_count": len(skipped),
                          "skipped_by_reason": dict(collections.Counter(s["reason"].split(" (")[0] for s in skipped)),
                          "skipped_records": [s for s in skipped if not s["reason"].startswith("listed under")][:20],
                          "sample_check": _check_summary(event), "notes": list(notes)}

    def hold(source, name, url, reason, until, evidence, event=None, notes=()):
        held[source] = held_policy(source, name, url, reason, until, evidence)
        report[source] = {"id": source, "status": "held", "held_reason": reason, "held_until": until,
                          "sample_check": _check_summary(event), "notes": list(notes)}

    # madrid_traffic: upgrade only with a confirmed sample
    if "madrid_traffic" in parsed:
        info, event = parsed["madrid_traffic"], _checks(out, "madrid_traffic")
        page = MADRID_DATASET_PAGE if page_ok(_receipt(raw / "madrid_traffic" / "dataset_page.html")) else existing_policy("madrid_traffic")["source"]["url"]
        if check_ok(event):
            items, skipped = madrid_items(info["rows"], info["receipt"]["observed_at"], True, page,
                                          existing_policy("madrid_traffic")["source"]["url"])
            emit("madrid_traffic", items, madrid_policy(items, page), ["madrid_traffic"], skipped, event,
                 [f"list {info['receipt']['url']} -> {info['receipt']['final_url']}", f"official_page {page}",
                  "snapshot_url kept as published, with its ?v= cache-buster (no credential key)"])
        else:
            report["madrid_traffic"] = {"id": "madrid_traffic", "status": "unchanged",
                                        "reason": "image sample not confirmed: upgrade not written",
                                        "sample_check": _check_summary(event)}

    if "madrid_calle30_cameras" in parsed:
        info, event = parsed["madrid_calle30_cameras"], _checks(out, "madrid_calle30_cameras")
        page_verified = page_ok(_receipt(raw / "madrid_calle30_cameras" / "dataset_page.html"))
        page = CALLE30_DATASET_PAGE if page_verified else None
        if check_ok(event):
            items, skipped = calle30_items(info["rows"], info["receipt"]["observed_at"], page, page or CALLE30_NAP_PAGE)
            emit("madrid_calle30_cameras", items, calle30_policy(items, page or CALLE30_NAP_PAGE), (), skipped, event,
                 [f"list {info['receipt']['url']} -> {info['receipt']['final_url']}",
                  "image URL built as https://mc30.es + the published scheme-less www.mc30.es path (the www host "
                  "redirects there; the list is served from https://mc30.es)",
                  f"official_page {page or 'none (dataset page not verified)'}"])
        else:
            hold("madrid_calle30_cameras", "Madrid Calle 30 (M-30) — traffic cameras", CALLE30_NAP_PAGE,
                 "image sample not confirmed (" + str((event or {}).get("inconclusive_reason") or (event or {}).get("http_status")) + ")",
                 "a confirmed HTTPS JPEG sample on mc30.es", [CALLE30_NAP_PAGE, CALLE30_XML], event)

    if "malaga_traffic" in parsed:
        info, event = parsed["malaga_traffic"], _checks(out, "malaga_traffic")
        if check_ok(event):
            items, skipped = malaga_items(info["rows"], info["receipt"]["observed_at"])
            emit("malaga_traffic", items, malaga_policy(items), (), skipped, event,
                 ["licence title CC BY 4.0 / link CC BY-SA 4.0: recorded condition 'display unmodified with attribution'"])
        else:
            hold("malaga_traffic", "Ayuntamiento de Málaga — cámaras de tráfico", MALAGA_DATASET_PAGE,
                 "image sample not confirmed", "a confirmed HTTPS JPEG sample on ctraficomovilidad.malaga.eu",
                 [MALAGA_DATASET_PAGE], event)

    if "euskadi_traffic" in parsed:
        info, event = parsed["euskadi_traffic"], _checks(out, "euskadi_traffic")
        if check_ok(event):
            items, skipped = euskadi_items(info["cameras"], info["licensed_urls"], info["receipt"]["observed_at"], True)
            emit("euskadi_traffic", items, euskadi_policy(items), ["euskadi_traffic"], skipped, event,
                 [f"kept under euskadi_traffic with per-record format so every existing id stays: Gobierno Vasco "
                  f"snapshots, Bilbao/Donostia page links; licensed GV dataset lists {info['licensed_count']} cameras",
                  f"API lists {len(info['cameras'])} cameras over all sources; sources 2 and 6 belong to the bizkaia "
                  f"and vitoria providers"])
        else:
            report["euskadi_traffic"] = {"id": "euskadi_traffic", "status": "unchanged",
                                         "reason": "www.trafikoa.eus image sample not confirmed: all records stay page_only "
                                                   "(no upgrade written)", "sample_check": _check_summary(event)}

    if "bizkaia" in parsed:
        info, event = parsed["bizkaia"], _checks(out, "bizkaia")
        verified = check_ok(event)
        # A sample that reached the host but found no image for that one camera (404/410) leaves the https
        # rows as published (the register sampled one); no answer at all leaves the provider unchanged.
        upgrade = verified or bool(event and event.get("http_status") in (404, 410))
        items, skipped = bizkaia_items(info["rows"], info["receipt"]["observed_at"], upgrade, verified)
        if not upgrade:
            report["bizkaia"] = {"id": "bizkaia", "status": "unchanged", "sample_check": _check_summary(event),
                                 "reason": "image sample not confirmed: upgrade not written"}
        elif any(i["format"] == "snapshot" for i in items):
            emit("bizkaia", items, bizkaia_policy(items), ["bizkaia"], skipped, event,
                 ["sample taken on an http row rewritten to https on www.bizkaimove.eus: "
                  + ("confirmed, all rows viewable" if verified else "not confirmed, http rows stay page_only")])

    # Held: list or coordinates not available within the etiquette
    fgc_audit = [audit.get(u) for u in FGC_LIST_URLS]
    discarded = (raw / "fgc_tourism_webcams" / "disallowed_request_discarded.receipt.json").exists()
    if not (raw / "fgc_tourism_webcams" / "webcams-actives-tim.json").exists():
        hold("fgc_tourism_webcams", "FGC — Webcams dels equipaments turístics",
             "https://dadesobertes.fgc.cat/explore/dataset/webcams-actives-tim/",
             "robots.txt of dadesobertes.fgc.cat disallows /api/ and /explore/dataset/*/download for all agents: the "
             "30 records can only be read from those paths (the explore page loads them through /api/).",
             "FGC publishes the list on a path robots.txt allows, or confirms automated reading of the export",
             ["https://dadesobertes.fgc.cat/robots.txt", "https://dadesobertes.fgc.cat/explore/dataset/webcams-actives-tim/"],
             notes=[f"robots.txt (RFC 9309) {'allows' if a and a['allowed'] else 'disallows'} {u}"
                    for u, a in zip(FGC_LIST_URLS, fgc_audit)] + (
                 ["one request was made in error to /explore/dataset/webcams-actives-tim/download/?format=json: "
                  "urllib.robotparser (PoliteClient) ignores the '*' wildcard; the response was discarded unread, "
                  "its receipt is kept in raw/fgc_tourism_webcams/"] if discarded else []))

    if "valencia_traffic" not in parsed:
        why = fetch_status.get("valencia_traffic", {})
        hold("valencia_traffic", "Ajuntament de València — Càmeres de trànsit", "https://datos.gob.es/catalogo/l01462508-camaras-trafico",
             "geoportal.valencia.es robots.txt unreachable (connection reset, twice): treated as disallow (RFC 9309), "
             "so the ArcGIS layer was not queried. " + str(why.get("refused") or why.get("error") or ""),
             "geoportal.valencia.es serves a robots.txt that allows the layer query",
             ["https://datos.gob.es/catalogo/l01462508-camaras-trafico"],
             notes=["robots.txt attempts: 2026-11-14T07:31Z in the list run and one retry, both reset by the host"])

    if "andorra_mobilitat" in parsed and not parsed["andorra_mobilitat"]["page"]["coordinates"]:
        hold("andorra_mobilitat", "Govern d'Andorra — Mobilitat webcams", ANDORRA_PAGE,
             "The official webcam page lists no cameras or coordinates in its HTML (they are loaded by script from an "
             "unlisted source); no camera list endpoint is published. Images: all rights reserved, no framing.",
             "a published camera list with coordinates (page links only)", [ANDORRA_PAGE, "https://www.govern.ad/ca/avis-legal"])

    held["dgt_nap_cameras"] = DGT_HELD
    report["dgt_nap_cameras"] = {"id": "dgt_nap_cameras", "status": "held", "held_reason": DGT_HELD["held_reason"],
                                 "held_until": DGT_HELD["held_until"]}

    pol_dir = out / "policies"
    pol_dir.mkdir(parents=True, exist_ok=True)
    for pid, policy in {**policies, **held}.items():
        (pol_dir / f"{pid}.json").write_text(json.dumps({pid: policy}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _check_summary(event):
    if not event:
        return None
    return {k: event.get(k) for k in ("record_id", "url", "status", "http_status", "signature", "content_type",
                                      "bytes_read", "checked_at", "inconclusive_reason", "robots_note")}


def baseline_counts(catalogue, inputs, providers):
    """Records per provider in the built catalogue and in the package inputs (read-only)."""
    counts = {p: {"catalogue": 0, "package_inputs": 0, "catalogue_formats": {}} for p in providers}
    if catalogue and Path(catalogue).exists():
        fmt = collections.defaultdict(collections.Counter)
        for i in json.loads(Path(catalogue).read_text(encoding="utf-8"))["items"]:
            if i.get("provider") in counts:
                counts[i["provider"]]["catalogue"] += 1
                fmt[i["provider"]][i.get("format")] += 1
        for p, c in fmt.items():
            counts[p]["catalogue_formats"] = dict(c)
    for path in inputs or ():
        if Path(path).exists():
            for i in json.loads(Path(path).read_text(encoding="utf-8")).get("items", []):
                if i.get("provider") in counts:
                    counts[i["provider"]]["package_inputs"] += 1
    return counts


CHANGES_FROM_REGISTER = [
    "madrid_calle30_cameras: 36 records, not 37 (camera 15RR64TV01 is listed twice); ids are the camera names with "
    "'+' and '()' mapped to '_' (M30-PK10+900C(M.ALVARO) -> M30-PK10_900C_M.ALVARO); no official_page (the "
    "datos.madrid.es dataset page for 212166 answered 404), source page = the NAP dataset record.",
    "madrid_traffic: official_page is the datos.madrid.es dataset page (verified, CC BY 4.0 shown); image URLs kept "
    "as published with their per-camera ?v= value.",
    "euskadi_traffic: no upgrade (www.trafikoa.eus unreachable, as in the register); kept under the same id when it "
    "is retried: GV snapshots + Bilbao/Donostia page links in one provider so every existing id stays.",
    "bizkaia: the one sample was taken on an http row rewritten to https (cam86.jpg): confirmed, so all 91 viewable.",
    "fgc_tourism_webcams: held (register: viewable) - every route to the records is robots-disallowed.",
    "valencia_traffic, andorra_mobilitat: held (robots.txt unreachable; no list/coordinates).",
]
FOR_THE_COORDINATOR = [
    "webcam_fetch.PoliteClient uses urllib.robotparser, which ignores '*' and '$' in robots rules: 'Disallow: "
    "/explore/dataset/*/download' was read as allowing that path and one list request was made to "
    "dadesobertes.fgc.cat/explore/dataset/webcams-actives-tim/download/?format=json (body discarded unread, receipt "
    "kept). Other collectors may be affected; collect_iberia.StrictClient adds RFC 9309 wildcard matching.",
    "checks/euskadi_traffic.snapshot.json is evidence of the failed sample only; there is no euskadi_traffic input "
    "to pair it with.",
    "madrid_calle30_cameras sample (M30-PK00+000C(MANOTERAS).jpg) was a complete 1,750-byte JPEG: possibly a "
    "placeholder frame; the register's sample of a plain-named camera (09NC39TV01.jpg) was a normal image.",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--from-raw", action="store_true", help="use the saved camera lists (no list request)")
    ap.add_argument("--offline", action="store_true", help="no network at all: saved lists, pages and samples")
    ap.add_argument("--baseline-catalogue", type=Path, help="current data/webcams.json, for before/after counts")
    ap.add_argument("--baseline-inputs", type=Path, nargs="*", default=[], help="package input files already merged")
    args = ap.parse_args(argv)
    client = None if args.offline else StrictClient()
    if not args.from_raw and not args.offline:
        fetch_lists(client, args.out)
    parsed = parse_raw(args.out / "raw")
    if client:
        network_stage(client, args.out, parsed)
        log = args.out / "raw" / "iberia_request_log.json"
        old = _json(log, [])
        log.write_text(json.dumps(old + client.log, indent=1), encoding="utf-8")
    report = build(args.out, parsed)
    providers = ["madrid_traffic", "euskadi_traffic", "bizkaia", "malaga_traffic", "madrid_calle30_cameras",
                 "fgc_tourism_webcams", "valencia_traffic", "andorra_mobilitat", "dgt_nap_cameras"]
    before = baseline_counts(args.baseline_catalogue, args.baseline_inputs, providers)
    for pid in providers:
        entry = report.setdefault(pid, {"id": pid})
        entry["before"] = before[pid]
        entry["after"] = (entry.get("viewable", 0) + entry.get("page_only", 0)) if "input_file" in entry else before[pid]["catalogue"]
    unreachable = sorted({urlsplit(e["sample_check"]["url"]).hostname for e in report.values()
                          if "unreachable" in str((e.get("sample_check") or {}).get("robots_note"))})
    if "valencia_traffic" not in parsed:
        unreachable.append("geoportal.valencia.es")
    doc = {"family": FAMILY, "generated_at": F.now(), "collector": "scripts/collect_iberia.py", "sources": report,
           "unchanged_by_brief": ["catalonia_sct", "vigo_traffic"],
           "hosts_unreachable_or_refused": unreachable,
           "requests_logged": len(_json(args.out / "raw" / "iberia_request_log.json", [])),
           "changes_from_register": CHANGES_FROM_REGISTER,
           "for_the_coordinator": FOR_THE_COORDINATOR}
    path = args.out / "reports" / f"{FAMILY}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    for pid, e in report.items():
        print(pid, e.get("status", "written"), e.get("viewable"), e.get("page_only"), (e.get("sample_check") or {}).get("status"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
