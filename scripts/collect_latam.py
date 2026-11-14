#!/usr/bin/env python3
"""Collect Latin American and Caribbean webcam sources for the Q-Globe catalogue (stdlib only).

Integrated when ready (2026-11 Americas register ids):
  eso_chile_webcams           ESO Paranal / ELT Armazones webcam images (CC BY 4.0, "feel free to embed")
  brazil_praia_grande_aovivo  Praia Grande city camera map (keyless JSON with coordinates): links to the map
Everything else in this family is written as a held policy with its reason (no records):
  El Salvador MARN (YouTube embed, no image, no coordinates), volcano observatories without a camera list
  with coordinates, hosts that refused, sources whose terms need an agreement.

Network only through webcam_fetch.PoliteClient; one image sample for the viewable provider. Parsing is in
pure functions (tests/test_collect_latam.py runs them on saved fixtures, offline).

  python scripts/collect_latam.py --out <dir>
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as W  # noqa: E402

FAMILY = "latam"
REVIEWED_AT = "2026-11-14"

ESO_PAGE = "https://www.eso.org/public/outreach/webcams/"
ESO_TERMS = "https://www.eso.org/public/outreach/copyright/"
ESO_TRAVEL_PARANAL = "https://www.eso.org/public/about-eso/travel/paranal/"
ESO_TRAVEL_ELT = "https://www.eso.org/public/about-eso/travel/elt/"
ESO_HOST = "www.eso.org"

SNET_PAGE = "https://www.snet.gob.sv/"

PG_MAP = "https://cameras.praiagrande.sp.gov.br/aovivo/"
PG_API = "https://cameras.praiagrande.sp.gov.br/aovivo/api"
PG_HOST = "cameras.praiagrande.sp.gov.br"
# Cameras at children's venues: published on the city map, but not listed one by one here.
PG_SKIP = re.compile(r"espa[cç]o\s+kids", re.I)


def coords(lat, lng):
    lat, lng = float(lat), float(lng)
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError("no usable coordinates")
    return round(lat, 6), round(lng, 6)


def text_of(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


# ================================================================= ESO
ESO_SECTION = re.compile(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2[^>]*>|\Z)", re.S)
ESO_IMAGE = re.compile(r'<a href="(/public/[^"]+\.jpg)">\s*<img src="(/public/[^"]+\.jpg)"[^>]*>\s*</a>(.*?)'
                       r'(?=<a href="/public/[^"]+\.jpg">|\Z)', re.S)
ESO_CAPTION = re.compile(r'<div align="center">(.*?)</div>', re.S)


def eso_site(heading):
    """('paranal'|'armazones'|None) for an ESO webcam section heading."""
    h = heading.lower()
    if "vlt" in h:
        return "paranal"
    if "elt" in h:
        return "armazones"
    return None  # ALMA (frozen since 2020, operated with partners), APEX, La Silla third-party cams, Headquarters


def parse_eso_page(text):
    """-> (views [{'site', 'section', 'href', 'thumb', 'caption'}], skipped [(section, reason)])."""
    start = text.find("Feel free to embed")
    body = text[start:] if start >= 0 else text
    views, skipped = [], []
    for m in ESO_SECTION.finditer(body):
        heading, content = text_of(m.group(1)), m.group(2)
        site = eso_site(heading)
        if not site:
            if ".jpg" in content:
                skipped.append((heading, "not an ESO Chile view kept by this adapter (ALMA frozen since 2020, partner or third-party host, or outside Chile)"))
            continue
        lead = text_of(content.split("<h3", 1)[0])
        if "not operational" in lead.lower():
            skipped.append((heading, "camera marked not operational on the page"))
            continue
        for im in ESO_IMAGE.finditer(content):
            href, thumb, tail = im.group(1), im.group(2), im.group(3)
            caption = ESO_CAPTION.search(tail)
            views.append({"site": site, "section": heading, "href": href, "thumb": thumb,
                          "caption": text_of(caption.group(1)) if caption else ""})
    return views, skipped


def eso_map_point(text, marker):
    """The ll= point of the Google map that ESO's own travel page embeds next to `marker`."""
    for m in re.finditer(r'maps\.google\.[a-z.]+/maps\?([^"]+)"', text):
        query = html.unescape(m.group(1))
        if marker.lower() in query.lower():
            ll = re.search(r"(?:^|&)ll=(-?\d+\.\d+),(-?\d+\.\d+)", query)
            if ll:
                return coords(ll.group(1), ll.group(2))
    return None


def eso_view_id(href):
    path = href.removeprefix("/public/").removesuffix(".jpg")
    return re.sub(r"[^A-Za-z0-9_.-]+", ".", path).strip(".")


def eso_name(view):
    site = "Paranal (VLT)" if view["site"] == "paranal" else "Cerro Armazones (ELT)"
    href = view["href"]
    if "preset_100" in href or "pano_PV" in href:
        label = view["section"].replace("Views from the ", "").replace("ELT ", "").strip("() ")
        what = "360° panorama" if view["site"] == "paranal" else f"{label}, 360° panorama"
        return f"ESO {site} — {what}"
    caption = re.split(r"(?<=[.!?])\s", view["caption"])[0].rstrip(".") if view["caption"] else ""
    caption = re.sub(r"\s+LIVE$", "", caption)
    number = re.search(r"preset_(\d+)", href)
    if not caption or len(caption) > 60:
        caption = "view " + (number.group(1) if number else "")
    return f"ESO {site} — {caption}"[:160]


def parse_eso(page_text, paranal_point, armazones_point, observed_at):
    views, skipped = parse_eso_page(page_text)
    items, seen = [], set()
    for v in views:
        point = paranal_point if v["site"] == "paranal" else armazones_point
        if not point:
            skipped.append((v["section"], "no ESO-published position for the site"))
            continue
        # Panoramas: the 960-px image ESO shows on the page; points of interest: the full image it links.
        image = v["thumb"] if "preset_100" in v["href"] else v["href"]
        pid = eso_view_id(image)
        if pid in seen:
            continue
        seen.add(pid)
        items.append({
            "provider": "eso_chile_webcams", "provider_id": pid, "id": f"eso_chile_webcams:{pid}", "name": eso_name(v),
            "lat": point[0], "lng": point[1], "country": "CL", "region": "Antofagasta",
            "coordinate_role": "associated_feature" if v["site"] == "paranal" else "approximate",
            "coordinate_note": ("VLT platform as pinned on ESO's Paranal travel page" if v["site"] == "paranal" else
                                "Centre of the 'Cerro Armazones' map on ESO's ELT travel page; the summit platform is a few km south"),
            "format": "snapshot", "stream_url": None, "snapshot_url": urljoin(ESO_PAGE, image),
            "official_page": ESO_PAGE + ("#armazones" if v["site"] == "armazones" else ""),
            "source_page": ESO_PAGE, "source_catalog": ESO_PAGE, "rights_status": "official_public_feed",
            "observed_at": observed_at, "health": {"status": "unverified"}, "requires_catalog_refresh": False,
            "image_timestamp_source": "http_last_modified",
            "freshness_note": "ESO refreshes these images irregularly (9-10 days old when checked on 2026-11-14): "
                              "show the image's Last-Modified time, never present it as live.",
            "caption": v["caption"][:300] or None, "provider_in_service": True})
    return items, skipped


# ================================================================= Praia Grande
def parse_praia_grande(rows, observed_at):
    items, excluded, seen = [], {}, set()
    for r in rows:
        desc = re.sub(r"\s+", " ", str(r.get("Description") or r.get("Name") or "")).strip()
        if PG_SKIP.search(desc) or PG_SKIP.search(str(r.get("Name") or "")):
            excluded["childrens_venue"] = excluded.get("childrens_venue", 0) + 1
            continue
        pid = str(r.get("Id") or "")
        try:
            lat, lng = coords(r.get("Latitude"), r.get("Longitude"))
        except (TypeError, ValueError):
            excluded["no_coordinates"] = excluded.get("no_coordinates", 0) + 1
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", pid) or pid in seen:
            excluded["bad_or_duplicate_id"] = excluded.get("bad_or_duplicate_id", 0) + 1
            continue
        seen.add(pid)
        name = re.sub(r"\s*\((?:Internet|internet|Briefcam)\)", "", desc).strip() or pid
        items.append({
            "provider": "brazil_praia_grande_aovivo", "provider_id": pid, "id": f"brazil_praia_grande_aovivo:{pid}",
            "name": name, "lat": lat, "lng": lng, "country": "BR", "region": "SP", "coordinate_role": "camera_location",
            "format": "official_page", "stream_url": None, "snapshot_url": None, "official_page": PG_MAP,
            "source_page": PG_MAP, "source_catalog": PG_API, "rights_status": "official_page_only",
            "link_scope": "provider_map", "observed_at": observed_at, "health": {"status": "unverified"},
            "provider_camera_name": str(r.get("Name") or "")[:120]})
    return items, excluded


# ================================================================= policies
def policies():
    return {
        "eso_chile_webcams": {
            "source": {
                "id": "eso_chile_webcams", "name": "ESO observatory webcams in Chile (Paranal VLT, ELT Cerro Armazones)",
                "url": ESO_PAGE, "catalog_url": ESO_PAGE, "terms_url": ESO_TERMS,
                "metadata_license": "CC-BY-4.0", "license": "CC-BY-4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "media_rights": "'Feel free to embed these webcam images on other web pages: just use the URL of the "
                                "product.' (ESO webcam page) and ESO images are CC BY 4.0 with a clear, visible credit "
                                "(ESO copyright page, re-read 2026-11-14). No implied ESO endorsement; images showing an "
                                "identifiable person may not be used commercially; ESO logo not licensed.",
                "rights_note": "Landscape/telescope views only; the ELT West camera (not operational), ALMA (frozen since "
                               "2020), APEX, REM/La Silla (third-party hosts) and the Garching headquarters cameras are "
                               "not included. Updates are irregular: show the image time.",
                "attribution": "Credit: ESO (webcam images, CC BY 4.0) – link to https://www.eso.org/public/outreach/webcams/",
                "rights_status": "official_public_feed", "allowed_hosts": [ESO_HOST],
                "review_status": "reviewed_for_snapshot_and_reference_use", "reviewed_at": REVIEWED_AT,
                "evidence": [ESO_PAGE, ESO_TERMS, ESO_TRAVEL_PARANAL, ESO_TRAVEL_ELT]},
            "media_hosts": [ESO_HOST], "page_hosts": [ESO_HOST], "formats": ["snapshot"], "countries": ["CL"],
            "operator_hints": [], "coordinate_role": "associated_feature"},
        "brazil_praia_grande_aovivo": {
            "source": {
                "id": "brazil_praia_grande_aovivo", "name": "Praia Grande – Câmeras ao Vivo (Monitoramento)",
                "url": PG_MAP, "catalog_url": PG_API, "terms_url": PG_MAP,
                "metadata_license": "No licence stated; factual camera list (name, position) from the city's public "
                                    "camera map, links only",
                "license": "No licence stated; links only",
                "media_rights": "No reuse licence for the images (Brazilian municipal works are not public domain): "
                                "the record links to the city's public camera map, no image is fetched or embedded.",
                "rights_note": "Two cameras at children's venues ('Espaço Kids') are left out.",
                "attribution": "Prefeitura de Praia Grande – Monitoramento",
                "rights_status": "official_page_only", "allowed_hosts": [],
                "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT,
                "evidence": [PG_MAP, PG_API]},
            "media_hosts": [], "page_hosts": [PG_HOST], "formats": ["official_page"], "countries": ["BR"],
            "operator_hints": [], "coordinate_role": "camera_location", "official_map_url": PG_MAP},
    }


def held(sid, name, url, reason, until, evidence):
    return {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
            "source": {"id": sid, "name": name, "url": url}}


HELD = {
    "colombia_sgc_volcano_cameras": held(
        "colombia_sgc_volcano_cameras", "Servicio Geológico Colombiano volcano webcams",
        "https://www2.sgc.gov.co/sgc/volcanes/VolcanGaleras/Paginas/imagenes-en-linea.aspx",
        "No camera list with coordinates: only a per-volcano image page (6 Galeras cameras confirmed, 37 nationally "
        "by SGC's own count); terms forbid copying or compiling content without written consent.",
        "an SGC camera list with positions, or SGC's written consent to list per-camera links",
        ["https://www2.sgc.gov.co/Paginas/terminos-y-condiciones.aspx"]),
    "costa_rica_ovsicori_cameras": held(
        "costa_rica_ovsicori_cameras", "OVSICORI-UNA volcano cameras", "https://www.ovsicori.una.ac.cr/index.php/camaras",
        "Per-camera pages only, no published camera positions; all rights reserved.",
        "camera positions published by OVSICORI (or a documented volcano gazetteer accepted as associated_feature)",
        ["https://www.ovsicori.una.ac.cr/"]),
    "nicaragua_ineter_volcano_webcams": held(
        "nicaragua_ineter_volcano_webcams", "INETER volcano webcams",
        "https://www.ineter.gob.ni/volcanes-en-nicaragua/volcan-masaya-nicaragua/",
        "Volcano pages embed one image each but publish no camera positions; no licence or terms found.",
        "camera positions from INETER and a readable terms statement", ["https://www.ineter.gob.ni/"]),
    "guatemala_insivumeh_cameras": held(
        "guatemala_insivumeh_cameras", "INSIVUMEH volcano surveillance cameras",
        "https://insivumeh.gob.gt/camaras-de-vigilancia-volcanica/",
        "No camera list: one page describes an embedded platform without camera names, URLs or positions; all rights reserved.",
        "a published camera list with positions", ["https://insivumeh.gob.gt/camaras-de-vigilancia-volcanica/"]),
    "ipgp_ovsg_guadeloupe": held(
        "ipgp_ovsg_guadeloupe", "OVSG-IPGP La Soufrière de Guadeloupe webcams", "https://www.ipgp.fr/observation/ovsg/",
        "Observatory page re-read 2026-11-14 (full page): no webcam list, URLs or positions in it (station map loaded "
        "dynamically); IPGP terms forbid commercial use of the information without express authorisation.",
        "a readable webcam list with positions and IPGP's authorisation for listing in a paid app",
        ["https://www.ipgp.fr/mentions-legales/"]),
    "ipgp_ovsm_martinique": held(
        "ipgp_ovsm_martinique", "OVSM-IPGP Montagne Pelée webcams", "https://www.ipgp.fr/observation/ovsm/",
        "Observatory page re-read 2026-11-14 (full page): no webcam list, URLs or positions in it; IPGP terms forbid "
        "commercial use of the information without express authorisation.",
        "a readable webcam list with positions and IPGP's authorisation for listing in a paid app",
        ["https://www.ipgp.fr/mentions-legales/"]),
    "mvo_montserrat": held(
        "mvo_montserrat", "Montserrat Volcano Observatory live remote camera", "https://www.mvo.ms/",
        "Camera page URL and position not published in a list; MVO asks for permission before any use of its media.",
        "the camera page URL with a position, and MVO's agreement to a link listing",
        ["https://www.mvo.ms/who-we-are/copyright-intellectual-property/"]),
    "panama_canal_webcams": held(
        "panama_canal_webcams", "Panama Canal Authority webcams", "https://multimedia.panama-canal.com/",
        "multimedia.panama-canal.com did not serve robots.txt (unreachable, treated as disallow by the polite client) "
        "on 2026-11-14; no camera list with positions; ACP terms restrict linking the images.",
        "a reachable camera list with positions and ACP's view on plain page links",
        ["https://pancanal.com/en/terms-of-use/"]),
    "cenapred_popocatepetl": held(
        "cenapred_popocatepetl", "CENAPRED Popocatépetl volcano webcams", "https://www.cenapred.unam.mx/",
        "www.cenapred.unam.mx answered HTTP 403 on 2026-11-14 (not bypassed); gob.mx terms allow personal, "
        "non-commercial use only.", "a reachable camera page and terms allowing a link listing",
        ["https://www.gob.mx/terminos"]),
    "chile_dgac_ifis_cameras": held(
        "chile_dgac_ifis_cameras", "DGAC Chile IFIS aerodrome cameras", "https://aipchile.dgac.gob.cl/camara/",
        "No DGAC website terms found; held as the brief directs.", "DGAC terms or written permission",
        ["https://aipchile.dgac.gob.cl/camara/"]),
    "chile_sernageomin_rnvv": held(
        "chile_sernageomin_rnvv", "SERNAGEOMIN RNVV / OVDAS volcano cameras", "https://rnvv.sernageomin.cl/",
        "Single-page app with no camera list endpoint found; no terms.", "a documented camera list and terms",
        ["https://rnvv.sernageomin.cl/"]),
    "brazil_cet_sp_cameras": held(
        "brazil_cet_sp_cameras", "CET-SP São Paulo traffic cameras", "https://www.cetsp.com.br/consultas/cameras-cet.aspx",
        "Conditional in the register: one rotating viewer without a per-camera list or positions, and no terms page located.",
        "a verified CET-SP camera endpoint and terms", ["https://cameras.cetsp.com.br/"]),
}


def snet_held(reason):
    return held("el_salvador_marn_snet_cameras", "MARN / SNET El Salvador — Cámara Volcán San Miguel", SNET_PAGE,
                reason, "an official HTTPS JPEG/PNG or HLS URL for the camera and a published camera position",
                [SNET_PAGE])


def snet_camera(text):
    """What the SNET home page shows for the San Miguel camera: ('youtube'|'image'|None, url)."""
    i = text.find("VOLC&Aacute;N SAN MIGUEL")
    if i < 0:
        i = text.find("Volc&aacute;n San Miguel")
    if i < 0:
        return None, None
    m = re.search(r'src="([^"]+)"', text[i:i + 4000])
    if not m:
        return None, None
    url = m.group(1)
    host = urlsplit(url).hostname or ""
    if "youtube" in host:
        return "youtube", url
    if re.search(r"\.(?:jpe?g|png)(?:\?|$)", url, re.I):
        return "image", url
    return None, url


# ================================================================= network run
def run(out, client=None):
    out = Path(out)
    client = client or W.PoliteClient()
    pols = policies()
    report = {"family": FAMILY, "sources": [], "held": [], "hosts_refused": []}

    def save(source, name, response):
        return W.save_raw(out / "raw" / source, name, response)

    def write_policy(source, entry):
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{source}.json").write_text(json.dumps({source: entry}, ensure_ascii=False, indent=1), encoding="utf-8")

    def hold(source, entry, host=None):
        write_policy(source, entry)
        report["held"].append({"id": source, "reason": entry["held_reason"]})
        if host:
            report["hosts_refused"].append({"source": source, "host": host, "reason": entry["held_reason"][:160]})
        print(source, "HELD")

    def emit(source, items, excluded, notes, check=None):
        W.write_catalog(out / f"{source}.json", [source], items)
        write_policy(source, pols[source])
        event = None
        if check:
            event = client.check_image(check["snapshot_url"], source, check["id"], pols[source]["media_hosts"])
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

    # ESO: webcam page + copyright page + the two travel pages that carry ESO's own site positions.
    try:
        page = client.get(ESO_PAGE)
        save("eso_chile_webcams", "eso_webcams.html", page)
        save("eso_chile_webcams", "eso_copyright.html", client.get(ESO_TERMS))
        paranal = client.get(ESO_TRAVEL_PARANAL)
        save("eso_chile_webcams", "eso_travel_paranal.html", paranal)
        elt = client.get(ESO_TRAVEL_ELT)
        save("eso_chile_webcams", "eso_travel_elt.html", elt)
        items, skipped = parse_eso(page["body"].decode("utf-8", "replace"),
                                   eso_map_point(paranal["body"].decode("utf-8", "replace"), "Very+Large+Telescope"),
                                   eso_map_point(elt["body"].decode("utf-8", "replace"), "Cerro+Armazones"),
                                   page["observed_at"])
        if not items:
            raise ValueError("no ESO Chile views found on the page")
        emit("eso_chile_webcams", items, {"sections_skipped": [f"{s}: {r}" for s, r in skipped]},
             ["Positions from ESO's own travel pages: Paranal = VLT pin (associated_feature); Armazones = map centre "
              "(approximate; the register's -24.5894,-70.1922 had no cited source).",
              "Images are refreshed irregularly: records carry image_timestamp_source=http_last_modified."],
             check=items[0])
    except (W.Refused, OSError, ValueError) as e:
        hold("eso_chile_webcams", held("eso_chile_webcams", pols["eso_chile_webcams"]["source"]["name"], ESO_PAGE,
                                       f"ESO webcam page not readable now: {str(e)[:160]}", "the page answers", [ESO_PAGE]),
             host=ESO_HOST)

    # El Salvador: integrate only if the official page shows an HTTPS image (it showed a YouTube embed).
    try:
        page = client.get(SNET_PAGE)
        save("el_salvador_marn_snet_cameras", "snet_home.html", page)
        kind, url = snet_camera(page["body"].decode("utf-8", "replace"))
        reason = {"youtube": f"The San Miguel camera on the official page is a YouTube live embed ({url}), not an HTTPS "
                             "JPEG/PNG or HLS image the app may load; no camera position is published.",
                  "image": f"An image ({url}) was found but no camera position is published; review before integrating.",
                  None: "No camera image URL found on the official page; no camera position is published."}[kind]
        hold("el_salvador_marn_snet_cameras", snet_held(reason))
    except (W.Refused, OSError) as e:
        hold("el_salvador_marn_snet_cameras", snet_held(f"Official page not readable now: {str(e)[:160]}"), host="www.snet.gob.sv")

    try:
        rows, r = client.get_json(PG_API)
        save("brazil_praia_grande_aovivo", "praiagrande_api.json", r)
        items, excluded = parse_praia_grande(rows, r["observed_at"])
        emit("brazil_praia_grande_aovivo", items, excluded,
             ["Links to the city's single public camera map (no per-camera page exists)."])
    except (W.Refused, OSError, ValueError) as e:
        hold("brazil_praia_grande_aovivo", held("brazil_praia_grande_aovivo", "Praia Grande – Câmeras ao Vivo", PG_MAP,
                                                f"camera list not readable now: {str(e)[:160]}", "the list answers", [PG_API]),
             host=PG_HOST)

    refused_hosts = {"panama_canal_webcams": "multimedia.panama-canal.com", "cenapred_popocatepetl": "www.cenapred.unam.mx"}
    for source, entry in HELD.items():
        hold(source, entry, host=refused_hosts.get(source))

    report["robots"] = {base: (rule if isinstance(rule, str) else "robots.txt read and honoured")
                        for base, rule in client.robots.items()}
    report["generated_at"] = W.now()
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output folder (normalized inputs, raw/, policies/, checks/, reports/)")
    run(ap.parse_args(argv).out)


if __name__ == "__main__":
    main()
