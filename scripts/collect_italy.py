#!/usr/bin/env python3
"""Collect the Italian webcam sources of the 2026-11-14 round (stdlib only).

Same stages and outputs as collect_europe_central.py, whose helpers this module reuses:
fetch (camera lists through PoliteClient, saved with receipts under OUT/raw/<source>/),
check (at most one image or HLS sample per new viewable provider) and build (offline:
OUT/<source>.json, OUT/policies/<source>.json, OUT/checks/..., OUT/reports/italy.json).

  python scripts/collect_italy.py --out <dir> fetch [--only a,b]
  python scripts/collect_italy.py --out <dir> check [--only a,b]
  python scripts/collect_italy.py --out <dir> build
"""
from __future__ import annotations

import collections
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_europe_central as C  # noqa: E402
from collect_europe_central import F, clean, fetch_one, item, policy, text  # noqa: E402

FAMILY = "italy"

# ======================================================================================
# Camera lists
# ======================================================================================

GARR_CHANNEL = "https://garr.tv/api/v1/video-channels/ingv_catania/videos?isLive=true"
GARR_VIDEO = "https://garr.tv/api/v1/videos/{uuid}"
VENEZIA_PAGE = "https://www.comune.venezia.it/it/content/webcam-0"
ARPAE_CAMERAS = "https://simc.arpae.it/stream_camera/api/cameras"
ASTM_PAGES = {  # road -> (operator, official page listing that road's cameras)
    "A4": ("SATAP", "https://www.satapweb.it/webcam-a4/"),
    "A21": ("Autovia Padana", "https://www.autoviapadana.it/webcam/"),
    "A6": ("Autostrada dei Fiori", "https://www.autostradadeifiori.it/webcam/"),
    "A10": ("Concessioni del Tirreno", "https://www.concessionideltirreno.it/webcam-a10/"),
    "A12": ("Concessioni del Tirreno", "https://www.concessionideltirreno.it/webcam-a12/"),
    "A33": ("Asti-Cuneo", "https://www.asticuneo.it/webcam/"),
    "A15": ("SALT - Autocisa", "https://www.salt.it/autocisa/webcam/"),
    "A32": ("SITAF", "https://www.sitaf.it/webcam-a32/"),
    "T4": ("SITAF", "https://www.sitaf.it/webcam-t4/"),
}
RAS_PAGE = "https://www.ras.bz.it/it/webcams/"
INFOVIAGGIANDO_PAGE = "https://www.infoviaggiando.it/webcam"
FVG_360_PAGE = "https://www.meteo.fvg.it/webcam_360.php"
GENOVA_PAGE = "https://smart.comune.genova.it/node/30486"
METEOTRENTINO_PAGE = "https://www.meteotrentino.it/dati/meteo/webcam/"
A22_PAGE = "https://www.autobrennero.it/it/in-viaggio/webcam/"


def fetch_ingv_oe_tv_channels(client, out):
    r = fetch_one(client, out, "ingv_oe_tv_channels", "channel_live_videos.json", GARR_CHANNEL, accept="application/json")
    if not r:
        return
    for video in json.loads(r["body"]).get("data", [])[:4]:
        uuid = video.get("uuid", "")
        if re.fullmatch(r"[0-9a-f-]{36}", uuid):
            fetch_one(client, out, "ingv_oe_tv_channels", f"video_{uuid}.json", GARR_VIDEO.format(uuid=uuid),
                      accept="application/json")


def fetch_venezia_cpsm_webcams(client, out):
    # www.comune.venezia.it asks for Crawl-delay: 10: a dedicated client keeps 10 s between requests.
    slow = F.PoliteClient(delay=10)
    fetch_one(slow, out, "venezia_cpsm_webcams", "webcam-0.html", VENEZIA_PAGE)
    client.log.extend(slow.log)


def fetch_arpae_camera_coastal(client, out):
    """The list carries a private config block (device addresses): it is dropped before the raw file is kept."""
    try:
        r = client.get(ARPAE_CAMERAS, accept="application/json")
    except (F.Refused, OSError) as e:
        C.record_refusal(out, "arpae_camera_coastal", ARPAE_CAMERAS, e)
        return
    data = json.loads(r["body"].decode("utf-8-sig"))
    redacted = [{k: v for k, v in cam.items() if k != "config"} | {"config_keys": sorted((cam.get("config") or {}).keys())}
                if isinstance(cam, dict) else cam for cam in (data if isinstance(data, list) else [])]
    body = json.dumps(redacted, ensure_ascii=False, indent=1).encode("utf-8")
    import hashlib
    note = {"redacted": "config objects removed before saving (private device addresses)",
            "original_bytes": len(r["body"]), "original_sha256": hashlib.sha256(r["body"]).hexdigest()}
    C.save(out, "arpae_camera_coastal", "cameras.json", dict(r, body=body))
    (C.raw_dir(out, "arpae_camera_coastal") / "cameras.json.redaction.json").write_text(json.dumps(note, indent=1), encoding="utf-8")


def fetch_astm_group_webcams(client, out):
    for road, (_, url) in ASTM_PAGES.items():
        fetch_one(client, out, "astm_group_webcams", f"webcam-{road.lower()}.html", url)


def fetch_ras_suedtirol_webcams(client, out):
    fetch_one(client, out, "ras_suedtirol_webcams", "webcams.html", RAS_PAGE)


def fetch_infoviaggiando_webcams(client, out):
    fetch_one(client, out, "infoviaggiando_webcams", "webcam.html", INFOVIAGGIANDO_PAGE)


def fetch_arpa_fvg_webcam_directory(client, out):
    fetch_one(client, out, "arpa_fvg_webcam_directory", "webcam_360.html", FVG_360_PAGE)


def fetch_genova_comune_webcams(client, out):
    fetch_one(client, out, "genova_comune_webcams", "node-30486.html", GENOVA_PAGE)


def fetch_meteotrentino_webcams(client, out):
    fetch_one(client, out, "meteotrentino_webcams", "webcam-index.html", METEOTRENTINO_PAGE)


def fetch_a22_autobrennero(client, out):
    fetch_one(client, out, "a22_autobrennero", "webcam.html", A22_PAGE)


# ======================================================================================
# Pure parsers (tests feed them the saved fixtures)
# ======================================================================================


def parse_garr_channel(body):
    return [{"uuid": v["uuid"], "name": v.get("name"), "is_live": v.get("isLive")} for v in json.loads(text(body)).get("data", [])]


def parse_garr_video(body):
    v = json.loads(text(body))
    playlists = [p.get("playlistUrl") for p in v.get("streamingPlaylists", []) if p.get("playlistUrl")]
    return {"uuid": v["uuid"], "name": v.get("name"), "licence": (v.get("licence") or {}).get("label"),
            "privacy": (v.get("privacy") or {}).get("label"), "is_live": v.get("isLive"),
            "state": (v.get("state") or {}).get("label"), "watch_url": v.get("url"),
            "playlist": playlists[0] if playlists else None, "description": v.get("description") or ""}


VENEZIA_LINK = re.compile(r'href="(https://www\.comune\.venezia\.it/sites/default/files/publicCPSM2/webcam/([a-z]+web\d)\.jpg)"'
                          r'[^>]*?title="([^"]+)"')


def parse_venezia(body):
    """Each still image is a link whose title names the view, e.g. "S.Marco Torre dell'Orologio (vista1)"."""
    rows = {}
    for m in VENEZIA_LINK.finditer(text(body)):
        rows.setdefault(m.group(2), {"code": m.group(2), "image": m.group(1), "label": clean(m.group(3))})
    return list(rows.values())


RAS_MARKER = re.compile(r"\{position: \{lat: ([-0-9.]+), lng: ([-0-9.]+)\}, detailPage:'(https://www\.ras\.bz\.it/it/webcam/detail/"
                        r"[a-z0-9-]+/)',html: '.*?<div class=\"title\">(.*?)</div>", re.S)


def parse_ras(body):
    rows = []
    for m in RAS_MARKER.finditer(text(body)):
        rows.append({"slug": m.group(3).rstrip("/").rsplit("/", 1)[1], "lat": float(m.group(1)), "lng": float(m.group(2)),
                     "page": m.group(3), "name": clean(m.group(4))})
    return rows


def parse_infoviaggiando(body):
    rows = []
    for raw in re.findall(r'\{"GeoLatY":[^{}]*\}', html.unescape(text(body))):
        r = json.loads(raw)
        if r.get("Category") != "webcam":
            continue
        title = clean(r.get("TitleH1"))
        road = re.match(r"(?:Bivio )?([AR]\d+)", title)
        rows.append({"camera": str(r["id"]), "title": title, "road": road.group(1) if road else None,
                     "lat": float(r["GeoLatY"]), "lng": float(r["GeoLonX"]), "direction": r.get("direzione")})
    return rows


def parse_genova(body):
    pattern = (r'data-href="https://strumenti\.comune\.genova\.it/webcams/turistiche/([a-z0-9_]+)/current\.jpg".*?'
               r"<h4[^>]*>(.*?)</h4>")
    return [{"code": m.group(1), "name": clean(m.group(2))} for m in re.finditer(pattern, text(body), re.S)]


def parse_meteotrentino(body):
    pattern = (r'<a href="(https://www\.meteotrentino\.it/dati/meteo/webcam/webcam-([a-z0-9-]+)/)"[^>]*>.*?'
               r'photocard-title">(.*?)</h3>')
    return [{"slug": m.group(2), "page": m.group(1), "name": clean(m.group(3))} for m in re.finditer(pattern, text(body), re.S)]


def parse_a22(body):
    t = text(body)
    title = re.search(r"<title>(.*?)</title>", t, re.S)
    return {"images": sorted(set(re.findall(r"WebCamImg/(km\d+)\.jpg", t)), key=lambda k: int(k[2:])),
            "title": clean(title.group(1)) if title else None}


# ======================================================================================
# Hand-placed positions (approximate; the operators publish names, not coordinates)
# ======================================================================================

INGV_PLACES = {  # channel name -> (record name, official page, place, region, DOI)
    "Etna": ("Etna — INGV live TV channel (EtnaTVChn)", "https://www.ct.ingv.it/sezioniesterne/StreamingEtna.php",
             (37.751, 14.993), "Sicilia", "https://doi.org/10.13127/etna/tvchn"),
    "Eolie": ("Isole Eolie — INGV live TV channel (AeolianTVChn)", "https://www.ct.ingv.it/sezioniesterne/StreamingEolie.php",
              (38.789, 15.213), "Sicilia", "https://doi.org/10.13127/aeolian/tvchn"),
}

VENEZIA_PLACES = {  # image code prefix -> building where the cameras are installed
    "smarco": (45.4344, 12.3387), "rialto": (45.4368, 12.3344), "murano": (45.4555, 12.359), "salute": (45.4307, 12.3363),
}

GENOVA_PLACES = {
    "calata": (44.4085, 8.9245), "corsoitalia": (44.3955, 8.956), "f_begato": (44.43, 8.915), "tursi": (44.4045, 8.905),
    "nervi": (44.38, 9.034), "deferrari": (44.4072, 8.9339), "portoantico2": (44.41, 8.9265), "portoantico": (44.4093, 8.927),
    "puntavagno": (44.3972, 8.9465), "raccoltefrugone": (44.3815, 9.0405), "matitone": (44.414, 8.913),
    "gropallo": (44.3803, 9.0335),
}

METEOTRENTINO_PLACES = {
    "grigno-barricata": (45.964, 11.625), "lago-di-calaita": (46.201, 11.803), "malga-bissina": (46.06, 10.513),
    "malga-zugna-rovereto": (45.83, 11.056), "paganella": (46.143, 11.03), "passo-costalunga": (46.404, 11.611),
    "passo-manghen": (46.173, 11.44), "peio": (46.364, 10.675), "ronchi-di-ala": (45.752, 11.058),
    "san-martino-di-castrozza": (46.262, 11.802), "trento-laste": (46.072, 11.136),
}

A22_HQ = (46.0945, 11.1105)  # Autostrada del Brennero S.p.A., Via Berlino 10, Trento (publisher of the shared page)


# ======================================================================================
# Builders
# ======================================================================================

held_result = C.held_result


def build_ingv_oe_tv_channels(out):
    channel = C.read_raw(out, "ingv_oe_tv_channels", "channel_live_videos.json")
    if channel is None:
        return held_result("ingv_oe_tv_channels", "IT", "INGV live TV channels", GARR_CHANNEL, "list not fetched",
                           "a fresh list", [GARR_CHANNEL])
    items, notes, names = [], [], ["channel_live_videos.json"]
    for v in parse_garr_channel(channel):
        name = f"video_{v['uuid']}.json"
        body = C.read_raw(out, "ingv_oe_tv_channels", name)
        if body is None:
            continue
        names.append(name)
        video = parse_garr_video(body)
        when = C.raw_receipt(out, "ingv_oe_tv_channels", name)["observed_at"]
        if video["licence"] != "CC BY 4.0" or video["privacy"] != "Public" or not video["playlist"] \
                or video["name"] not in INGV_PLACES:
            notes.append(f"{video['name']}: licence {video['licence']}, privacy {video['privacy']} — skipped")
            continue
        label, page, place, region, doi = INGV_PLACES[video["name"]]
        items.append(item("ingv_oe_tv_channels", video["uuid"], label, place[0], place[1], "IT", region, format_="hls",
                          stream_url=video["playlist"], official_page=page, source_page=video["watch_url"],
                          source_catalog=GARR_CHANNEL, observed_at=when, coordinate_role="approximate",
                          coordinate_crs="EPSG:4326", coordinate_transform_applied=False,
                          coordinate_note="Volcano reference point (summit/island); the channel shows INGV cameras around it.",
                          reference_url=doi, licence_on_video=video["licence"]))
    pol = policy(
        "ingv_oe_tv_channels", name="INGV Osservatorio Etneo — live TV channels (Etna, Isole Eolie)",
        url="https://www.ct.ingv.it/sezioniesterne/StreamingEtna.php", catalog_url=GARR_CHANNEL,
        terms_url="https://www.ct.ingv.it/sezioniesterne/StreamingEtna.php", license_="CC-BY-4.0", license_url=C.CC_BY_4,
        media_rights=("Live video explicitly licensed CC BY 4.0: licence field 'CC BY 4.0' on each garr.tv video and the CC BY "
                      "4.0 notice on the INGV streaming pages ('I dati e i risultati pubblicati su queste pagine sono distribuiti "
                      "sotto licenza Creative Commons Attribution 4.0 International License'). Commercial use allowed."),
        attribution=("INGV - Osservatorio Etneo, Etna's TV channel (EtnaTVChn), https://doi.org/10.13127/etna/tvchn, CC BY 4.0 "
                     "(Aeolian: https://doi.org/10.13127/aeolian/tvchn)"),
        provider_notice="The channel may switch between INGV cameras; the marker is the volcano, not one camera.",
        evidence=["https://www.ct.ingv.it/sezioniesterne/StreamingEtna.php", "https://www.ct.ingv.it/sezioniesterne/StreamingEolie.php",
                  GARR_CHANNEL], formats=["hls"], countries=["IT"], media_hosts=["garr.tv"], page_hosts=["www.ct.ingv.it"],
        coordinate_role="approximate", raw=C.raw_files(out, "ingv_oe_tv_channels", *names))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "garr.tv: 'Disallow:' empty (all allowed)", "notes": "; ".join(notes) or None,
            "overlap": "none (no garr.tv or ct.ingv.it records in the catalogue)"}


def build_venezia_cpsm_webcams(out):
    body = C.read_raw(out, "venezia_cpsm_webcams", "webcam-0.html")
    if body is None:
        return held_result("venezia_cpsm_webcams", "IT", "Comune di Venezia CPSM webcams", VENEZIA_PAGE, "page not fetched",
                           "a fresh page", [VENEZIA_PAGE])
    when = C.raw_receipt(out, "venezia_cpsm_webcams", "webcam-0.html")["observed_at"]
    items = []
    for r in parse_venezia(body):
        place = VENEZIA_PLACES[r["code"].split("web")[0]]
        items.append(item("venezia_cpsm_webcams", r["code"], f"{r['label']} — Centro Maree Venezia", place[0], place[1], "IT",
                          "Veneto (Venezia)", format_="snapshot", snapshot_url=r["image"], official_page=VENEZIA_PAGE,
                          source_page=VENEZIA_PAGE, source_catalog=VENEZIA_PAGE, observed_at=when, coordinate_role="approximate",
                          coordinate_crs="EPSG:4326", coordinate_transform_applied=False,
                          coordinate_note="Hand-placed at the building where the camera is installed (named on the page)."))
    pol = policy(
        "venezia_cpsm_webcams", name="Comune di Venezia — Centro Previsioni e Segnalazioni Maree, webcam", url=VENEZIA_PAGE,
        terms_url="https://www.comune.venezia.it/content/note-legali",
        license_="CC-BY-3.0-IT (site-wide, 'salvo dove è diversamente specificato'; nothing else stated on the webcam page)",
        license_url="https://creativecommons.org/licenses/by/3.0/it/",
        media_rights=("The webcam images are content of www.comune.venezia.it published by the Comune; the site-wide CC BY 3.0 IT "
                      "applies unless otherwise stated and the page states nothing else: reuse allowed citing the source and the "
                      "original page address. Tier B: not separately confirmed with the Comune."),
        attribution=("Comune di Venezia - Centro Previsioni e Segnalazioni Maree, webcam "
                     "(https://www.comune.venezia.it/it/content/webcam-0), CC BY 3.0 IT"),
        provider_notice="Images are updated in sequence about every 20 minutes (Comune di Venezia).",
        evidence=["https://www.comune.venezia.it/content/note-legali", VENEZIA_PAGE], formats=["snapshot"], countries=["IT"],
        media_hosts=["www.comune.venezia.it"], page_hosts=["www.comune.venezia.it"], minimum_refresh_seconds=1200,
        coordinate_role="approximate", raw=C.raw_files(out, "venezia_cpsm_webcams", "webcam-0.html"))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "www.comune.venezia.it: Crawl-delay 10 honoured (10 s client); /sites/ not disallowed",
            "changes": ["4 buildings hand-placed (approximate); the Lido-diga camera is described but not shown, so not listed"],
            "overlap": "none (no comune.venezia.it records)"}


def build_arpae_camera_coastal(out):
    body = C.read_raw(out, "arpae_camera_coastal", "cameras.json")
    cams = json.loads(text(body)) if body else []
    without = [c for c in cams if not c.get("url")]
    return held_result(
        "arpae_camera_coastal", "IT", "Arpae Emilia-Romagna camERa coastal webcams", "https://simc.arpae.it/stream_camera/gis/map",
        f"snapshot route not confirmed: the official list ({len(cams)} cameras) has url null on {len(without)} rows and "
        "names no image route, so the single check had nothing to sample (no route guessed)",
        "the snapshot/TIMEX image route published by Arpae (or confirmed by e-mail), then one image check",
        [ARPAE_CAMERAS, "https://www.arpae.it/it/note-legali-e-copyright"],
        robots="simc.arpae.it: no robots.txt (404); list read, config block (private device addresses) dropped before saving")


def build_astm_group_webcams(out):
    refusals = []
    for road, (_, url) in ASTM_PAGES.items():
        r = C.raw_receipt(out, "astm_group_webcams", f"webcam-{road.lower()}.html")
        if not r or r["status"] != 200:
            refusals.append((urlsplit(url).hostname, r["status"] if r else "not fetched"))
    hosts = sorted({h for h, _ in refusals})
    return held_result(
        "astm_group_webcams", "IT", "ASTM group motorway webcams", "https://www.satapweb.it/webcam-a4/",
        f"{len(refusals)} of {len(ASTM_PAGES)} webcam pages answered HTTP 410 Gone (nginx, robots.txt included) to the "
        f"collector on {len(hosts)} hosts; not retried with another agent; no coordinates (km markers only) in any case",
        "pages reachable for a declared crawler, and positions for the km markers",
        [url for _, url in ASTM_PAGES.values()],
        refused_hosts=[{"host": h, "reason": f"HTTP {s}"} for h, s in sorted(set(refusals))],
        robots="robots.txt itself answered 410 on every host")


def build_ras_suedtirol_webcams(out):
    body = C.read_raw(out, "ras_suedtirol_webcams", "webcams.html")
    if body is None:
        return held_result("ras_suedtirol_webcams", "IT", "RAS webcams", RAS_PAGE, "page not fetched", "a fresh page", [RAS_PAGE])
    when = C.raw_receipt(out, "ras_suedtirol_webcams", "webcams.html")["observed_at"]
    items = [item("ras_suedtirol_webcams", r["slug"], f"{r['name']} — RAS webcam", r["lat"], r["lng"], "IT",
                  "Alto Adige / Südtirol", format_="official_page", official_page=r["page"], source_page=RAS_PAGE,
                  source_catalog=RAS_PAGE, observed_at=when, coordinate_role="station_location", coordinate_crs="EPSG:4326",
                  coordinate_note="Position of the RAS site on the operator's own webcam map.")
             for r in parse_ras(body)]
    pol = policy(
        "ras_suedtirol_webcams", name="RAS — Radiotelevisione Azienda Speciale, webcam (Alto Adige / Südtirol)", url=RAS_PAGE,
        terms_url="https://www.ras.bz.it/it/note-legali/", license_="None stated (© RAS)",
        media_rights="No licence for third-party display of the images; links to the official camera pages only.",
        attribution="RAS - Radiotelevisione Azienda Speciale (www.ras.bz.it)",
        evidence=["https://www.ras.bz.it/it/note-legali/", "https://home.provincia.bz.it/it/note-legali"],
        formats=["official_page"], countries=["IT"], page_hosts=["www.ras.bz.it"], coordinate_role="station_location",
        official_map_url=RAS_PAGE, raw=C.raw_files(out, "ras_suedtirol_webcams", "webcams.html"))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "www.ras.bz.it: typo3 folders, ?id= and cHash disallowed; /it/webcam pages allowed",
            "changes": ["coordinates from the RAS map markers (register expected geocoding)",
                        f"{text(body).count('detailPage:') - len(items)} marker(s) skipped: malformed detail link "
                        "(Fleres: /it/webcam/detail/webcam/detail/fleres/, not in the page list)"],
            "overlap": "47 OSM records link ras.bz.it webcam pages (German paths); kept as separate community links"}


def medoid(rows):
    return min(rows, key=lambda a: sum(math.hypot(a["lat"] - b["lat"], (a["lng"] - b["lng"]) * 0.7) for b in rows))


def build_infoviaggiando_webcams(out):
    body = C.read_raw(out, "infoviaggiando_webcams", "webcam.html")
    if body is None:
        return held_result("infoviaggiando_webcams", "IT", "Infoviaggiando", INFOVIAGGIANDO_PAGE, "page not fetched",
                           "a fresh page", [INFOVIAGGIANDO_PAGE])
    when = C.raw_receipt(out, "infoviaggiando_webcams", "webcam.html")["observed_at"]
    rows = parse_infoviaggiando(body)
    groups = collections.OrderedDict()
    for r in rows:
        if r["road"]:
            groups.setdefault(r["road"], []).append(r)
    items = []
    for road, cams in groups.items():
        anchor = medoid(cams)
        items.append(item("infoviaggiando_webcams", road, f"{road} webcams — Infoviaggiando ({len(cams)} camera{'s' if len(cams) != 1 else ''})",
                          anchor["lat"], anchor["lng"], "IT", "Lombardia / Veneto / Friuli Venezia Giulia",
                          format_="official_page", official_page=INFOVIAGGIANDO_PAGE, source_page=INFOVIAGGIANDO_PAGE,
                          source_catalog=INFOVIAGGIANDO_PAGE, observed_at=when, coordinate_role="associated_feature",
                          coordinate_crs="EPSG:4326", road=road, camera_count=len(cams),
                          coordinate_note="One camera position on this road from the operator's map; the shared page lists every camera."))
    pol = policy(
        "infoviaggiando_webcams", name="Infoviaggiando — north-east motorway webcams (Autostrade Alto Adriatico, CAV, A4 Holding)",
        url=INFOVIAGGIANDO_PAGE, terms_url="https://www.infoviaggiando.it/it/disclaimer",
        license_="None — exclusive rights; reproduction (even partial), mirroring and framing prohibited without written authorization",
        media_rights=("The disclaimer forbids reproducing the site's content, photos and video; linking to the public page is "
                      "not forbidden. Conservative reading: one shared-page record per road, no camera list copied."),
        attribution="Infoviaggiando - Autostrade Alto Adriatico, CAV, Autostrada BS-PD (https://www.infoviaggiando.it/webcam)",
        evidence=["https://www.infoviaggiando.it/it/disclaimer"], formats=["official_page"], countries=["IT"],
        page_hosts=["www.infoviaggiando.it"], coordinate_role="associated_feature", official_map_url=INFOVIAGGIANDO_PAGE,
        raw=C.raw_files(out, "infoviaggiando_webcams", "webcam.html"))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "www.infoviaggiando.it: Python-urllib/curl/wget disallowed by name; 'User-agent: *' allows /webcam (collector UA)",
            "changes": [f"{len(rows)} cameras on the page; one record per road ({len(items)}) under the conservative reading of the "
                        "disclaimer (register: 'one shared-page record per road')"],
            "overlap": "2 OSM records link CAV image URLs (assets.cavspa.it)"}


def build_genova_comune_webcams(out):
    body = C.read_raw(out, "genova_comune_webcams", "node-30486.html")
    if body is None:
        return held_result("genova_comune_webcams", "IT", "Comune di Genova webcam", GENOVA_PAGE, "page not fetched",
                           "a fresh page", [GENOVA_PAGE])
    when = C.raw_receipt(out, "genova_comune_webcams", "node-30486.html")["observed_at"]
    items = [C.hand_placed("genova_comune_webcams", r["code"], f"{r['name']} — webcam Comune di Genova", GENOVA_PLACES[r["code"]],
                           "IT", "Liguria (Genova)", page=GENOVA_PAGE, source_page=GENOVA_PAGE, source_catalog=GENOVA_PAGE,
                           observed_at=when, role="associated_feature",
                           note="Hand-placed at the landmark named by the city page (view subject or camera site).")
             for r in parse_genova(body) if r["code"] in GENOVA_PLACES]
    pol = policy(
        "genova_comune_webcams", name="Comune di Genova — webcam turistiche", url=GENOVA_PAGE,
        terms_url="https://www.comune.genova.it/note-legali",
        license_="CC-BY-4.0 for www.comune.genova.it content; scope over smart/strumenti subdomains not stated",
        media_rights=("Licence scope over the webcam host is unconfirmed and the image host refuses direct requests; page links "
                      "only (upgrade candidate if the Comune confirms)."),
        attribution="Comune di Genova - Webcam turistiche (https://smart.comune.genova.it/node/30486)",
        evidence=["https://www.comune.genova.it/note-legali", GENOVA_PAGE], formats=["official_page"], countries=["IT"],
        page_hosts=["smart.comune.genova.it"], coordinate_role="associated_feature", official_map_url=GENOVA_PAGE,
        raw=C.raw_files(out, "genova_comune_webcams", "node-30486.html"))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "smart.comune.genova.it: no rule on /node", "changes": ["12 landmarks hand-placed (associated_feature)"],
            "overlap": "1 OSM record links an old comune.genova.it De Ferrari page"}


def build_meteotrentino_webcams(out):
    body = C.read_raw(out, "meteotrentino_webcams", "webcam-index.html")
    if body is None:
        return held_result("meteotrentino_webcams", "IT", "Meteotrentino webcams", METEOTRENTINO_PAGE, "page not fetched",
                           "a fresh page", [METEOTRENTINO_PAGE])
    when = C.raw_receipt(out, "meteotrentino_webcams", "webcam-index.html")["observed_at"]
    items = [C.hand_placed("meteotrentino_webcams", r["slug"], f"{r['name']} — Meteotrentino webcam",
                           METEOTRENTINO_PLACES[r["slug"]], "IT", "Trentino", page=r["page"], source_page=METEOTRENTINO_PAGE,
                           source_catalog=METEOTRENTINO_PAGE, observed_at=when)
             for r in parse_meteotrentino(body) if r["slug"] in METEOTRENTINO_PLACES]
    pol = policy(
        "meteotrentino_webcams", name="Meteotrentino — webcam (Provincia autonoma di Trento)", url=METEOTRENTINO_PAGE,
        terms_url="https://www.provincia.tn.it/Informative/Note-legali-e-crediti",
        license_="CC-BY-4.0 per the provincial legal notes (site content incl. images)", license_url=C.CC_BY_4,
        media_rights=("The image host contenuti.meteotrentino.it disallows all robots and the image route is unconfirmed: "
                      "per-camera page links only (upgrade candidate once Meteotrentino confirms)."),
        attribution="Meteotrentino - Provincia autonoma di Trento, CC BY 4.0",
        evidence=["https://www.provincia.tn.it/Informative/Note-legali-e-crediti", METEOTRENTINO_PAGE],
        formats=["official_page"], countries=["IT"], page_hosts=["www.meteotrentino.it"], coordinate_role="approximate",
        raw=C.raw_files(out, "meteotrentino_webcams", "webcam-index.html"))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "www.meteotrentino.it: 'Disallow:' empty; contenuti.meteotrentino.it (images, not fetched): Disallow /",
            "changes": ["11 camera sites hand-placed (approximate)"]}


def build_a22_autobrennero(out):
    body = C.read_raw(out, "a22_autobrennero", "webcam.html")
    if body is None:
        return held_result("a22_autobrennero", "IT", "Autostrada del Brennero A22 webcams", A22_PAGE, "page not fetched",
                           "a fresh page", [A22_PAGE])
    when = C.raw_receipt(out, "a22_autobrennero", "webcam.html")["observed_at"]
    page = parse_a22(body)
    items = [C.hand_placed("a22_autobrennero", "webcam-page",
                           f"Autostrada del Brennero A22 — webcam page ({len(page['images'])} locations)",
                           A22_HQ, "IT", "Trentino-Alto Adige / Veneto / Lombardia / Emilia-Romagna", page=A22_PAGE,
                           source_page=A22_PAGE, source_catalog=A22_PAGE, observed_at=when, role="associated_feature",
                           note=("Placed at the operator's seat in Trento, away from the 13 A22 camera positions already in the "
                                 "catalogue (opendatahub); the shared page shows every A22 webcam."), road="A22")]
    pol = policy(
        "a22_autobrennero", name="Autostrada del Brennero (A22) — webcam page", url=A22_PAGE,
        terms_url="https://www.autobrennero.it/it/la-societa/trasparenza/bilanci/",
        license_="None — all rights reserved",
        media_rights="Images are the company's exclusive property; link to the shared page only.",
        attribution="Autostrada del Brennero S.p.A. (https://www.autobrennero.it/it/in-viaggio/webcam/)",
        evidence=["https://www.autobrennero.it/it/la-societa/trasparenza/bilanci/", A22_PAGE], formats=["official_page"],
        countries=["IT"], page_hosts=["www.autobrennero.it"], coordinate_role="associated_feature", official_map_url=A22_PAGE,
        raw=C.raw_files(out, "a22_autobrennero", "webcam.html"))
    return {"status": "integrated", "country": "IT", "items": items, "policy": pol,
            "robots": "www.autobrennero.it: robots.txt 404 (empty), page allowed",
            "changes": ["one record for the shared page, not per camera (13 opendatahub + 4 OSM records already sit at the km positions)"],
            "overlap": "13 opendatahub + 4 OSM records use km{N}.jpg images as page; the build moves them to references"}


def build_arpa_fvg_webcam_directory(out):
    r = C.refused(out, "arpa_fvg_webcam_directory")
    return held_result(
        "arpa_fvg_webcam_directory", "IT", "ARPA FVG OSMER webcam directory (Panomax)", FVG_360_PAGE,
        "robots.txt not readable over HTTPS: https://www.meteo.fvg.it/robots.txt redirects to the http:// home page, which the "
        "client treats as unreachable (no crawling); the directory was not read" + (f" ({r['reason']})" if r else ""),
        "an HTTPS robots.txt allowing the page (or ARPA FVG's permission); Panomax page coordinates",
        [FVG_360_PAGE, "https://www.panomax.com/en/terms-of-use"],
        refused_hosts=[{"host": "www.meteo.fvg.it", "reason": "robots.txt redirects away from HTTPS"}])


def build_arpav_webcams(out):
    return held_result("arpav_webcams", "IT", "ARPAV Veneto webcam map",
                       "https://www.arpa.veneto.it/dati-ambientali/dati-in-diretta/radar/webcam",
                       "no camera list endpoint (JS-rendered map; register)", "an official list with image URLs and coordinates",
                       ["https://www.arpa.veneto.it/note-legali"])


def low(source_id, name, url, evidence):
    return C.low_confidence(source_id, "IT", name, url, evidence)


def check_venezia(client, out, result):
    # www.comune.venezia.it asks for Crawl-delay: 10; the image sits on the same host.
    return C.check_snapshot(F.PoliteClient(delay=10), out, result)


SOURCES = {
    "ingv_oe_tv_channels": {"fetch": fetch_ingv_oe_tv_channels, "build": build_ingv_oe_tv_channels},
    "venezia_cpsm_webcams": {"fetch": fetch_venezia_cpsm_webcams, "build": build_venezia_cpsm_webcams},
    "arpae_camera_coastal": {"fetch": fetch_arpae_camera_coastal, "build": build_arpae_camera_coastal},
    "astm_group_webcams": {"fetch": fetch_astm_group_webcams, "build": build_astm_group_webcams},
    "ras_suedtirol_webcams": {"fetch": fetch_ras_suedtirol_webcams, "build": build_ras_suedtirol_webcams},
    "infoviaggiando_webcams": {"fetch": fetch_infoviaggiando_webcams, "build": build_infoviaggiando_webcams},
    "arpa_fvg_webcam_directory": {"fetch": fetch_arpa_fvg_webcam_directory, "build": build_arpa_fvg_webcam_directory},
    "genova_comune_webcams": {"fetch": fetch_genova_comune_webcams, "build": build_genova_comune_webcams},
    "meteotrentino_webcams": {"fetch": fetch_meteotrentino_webcams, "build": build_meteotrentino_webcams},
    "a22_autobrennero": {"fetch": fetch_a22_autobrennero, "build": build_a22_autobrennero},
    "arpav_webcams": {"build": build_arpav_webcams},
    "aspi_webcams": {"build": low("aspi_webcams", "Autostrade per l'Italia — webcam map", "https://www.autostrade.it/it/webcam",
                                  ["https://www.autostrade.it/it/webcam"])},
    "visittrentino_webcams": {"build": low("visittrentino_webcams", "Visit Trentino webcam directory",
                                           "https://www.visittrentino.info/it/webcams",
                                           ["https://www.visittrentino.info/it/note-legali"])},
    "milano_serravalle_videowall": {"build": low("milano_serravalle_videowall", "Milano Serravalle — Milano Tangenziali videowall",
                                                 "https://www.serravalle.it/index.php/pagine/videowall/1",
                                                 ["https://www.e015.regione.lombardia.it/site/download-policy?id=226"])},
}

CHECKS = {"ingv_oe_tv_channels": C.check_hls, "venezia_cpsm_webcams": check_venezia}


ETIQUETTE = [
    "Robots re-check with the fixed webcam_fetch.Robots: every URL fetched for this family is allowed by its host's "
    "robots.txt (see reports/europe_central.json for the joint re-check); meteo.fvg.it was never requested.",
    "www.comune.venezia.it asks Crawl-delay 10: the page and the image sample used a 10-second client.",
    "arpae_camera_coastal: the list's config block (private 10.x device addresses) was dropped before the raw file was "
    "saved; the original size and SHA-256 are in raw/arpae_camera_coastal/cameras.json.redaction.json.",
    "astm_group_webcams: 9 page requests and 7 robots.txt requests all answered 410 Gone to the collector; no retry.",
]


def main(argv=None):
    return C.run(FAMILY, SOURCES, C.main_args(argv), CHECKS, ETIQUETTE)


if __name__ == "__main__":
    sys.exit(main())
