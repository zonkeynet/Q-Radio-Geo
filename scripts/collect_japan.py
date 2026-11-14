#!/usr/bin/env python3
"""Collect Japanese official webcam sources for the Q-Globe catalogue (round of 2026-11-14).

Integrated (viewable snapshots, Public Data License 1.0):
  jma_volcano_cameras  JMA volcano monitoring cameras: the national index, the official camera
                       map positions (camicon.geojson) and each camera page (newest dated frame).
  mlit_kanto_cctv      MLIT Kanto Regional Development Bureau stills, only from office systems that
                       publish official coordinates: the Tone upstream river office (cameradb.json,
                       DMS per camera) and the Kita-shuto national highway office (CCTV.kml, WGS84).
                       The other office pages give route/kilometre posts or place names only: their
                       cameras cannot be placed and are counted, not integrated.
Held (policy fragments, no items): mlit_kyushu_road_cameras (no office publishes coordinates),
  japan_mlit_rivers_snapshot_upgrade, mlit_regional_bureaus_other, mlit_dpf_cctv,
  jcg_mics_livecamera, nexco_central_ihighway, nexco_east_driveplaza, nexco_west_ihighway.

Network only through webcam_fetch.PoliteClient (robots.txt, >= 1 s per host, HTTPS, refusals
recorded). Run without arguments' --offline to fetch; --offline rebuilds every output from the
saved raw responses. One image check per integrated viewable provider.

  python scripts/collect_japan.py --out <SCRATCH>/webcam-inputs-2026-11 [--catalog data/webcams.json]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as F  # noqa: E402

FAMILY = "japan"
REVIEWED_AT = "2026-11-14"
PDL_URL = "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0"
PDL_NAME = "Public Data License 1.0 (PDL1.0), CC BY 4.0 compatible"
JST = dt.timezone(dt.timedelta(hours=9))

# ---------------------------------------------------------------- JMA
JMA_INDEX = "https://www.data.jma.go.jp/vois/data/obs/volcam/volcam.php"
JMA_POSITIONS = "https://www.data.jma.go.jp/vois/data/obs/volcam/param/geojson/camicon.geojson"
JMA_MAP = "https://www.data.jma.go.jp/vois/data/obs/volcam/volmap.html"
JMA_TERMS = "https://www.jma.go.jp/jma/kishou/info/coment.html"
JMA_HOST = "www.data.jma.go.jp"

# ---------------------------------------------------------------- MLIT Kanto
KTR = "https://www.ktr.mlit.go.jp"
KTR_HOST = "www.ktr.mlit.go.jp"
KTR_TERMS = KTR + "/guide/copyright.html"
KTR_DIRECTORY = KTR + "/guide/guide00000012.html"
TONEJO_DB = KTR + "/tonejo/cctv/cameraimage/cameradb.json"
TONEJO_VIEW = KTR + "/tonejo/cctv/camview.htm?stname="
TONEJO_IMAGES = KTR + "/tonejo/cctv/cameraimage/"
TONEJO_LIST = KTR + "/tonejo/cctv/list_index.html"
KITASYUTO_KML = KTR + "/kitasyuto/public/CCTV.kml"
KITASYUTO_PAGE = KTR + "/kitasyuto/public/CCTV.html"
KANTO_OFFICE_NAMES = {"tonejo": "利根川上流河川事務所", "kitasyuto": "北首都国道事務所"}
# Office camera directories without coordinates: counted, never placed. (key, office, url, camera-id regex)
KANTO_UNPLACED = [
    ("sobu", "相武国道事務所", KTR + "/sobu/sobu_index018.html", r"/sobu/(sobu000\d+)\.html"),
    ("oomiya", "大宮国道事務所", KTR + "/oomiya/oomiya_livecamera01.html", r"\((\d+)\)\s*一般国道"),
    ("utunomiya", "宇都宮国道事務所", KTR + "/utunomiya/utunomiya_index002.html",
     r"/utunomiya/(utunomiya(?:_livecamera|00)\d+)\.html"),
    ("takasaki", "高崎河川国道事務所", KTR + "/takasaki/takasaki_index009.html", r"/takasaki/(takasaki00\d+)\.html"),
    ("kasumi", "霞ヶ浦河川事務所", KTR + "/kasumi/kasumi00001.html", r"/kasumi/(kasumi00(?!001)\d+)\.html"),
    ("arajo", "荒川上流河川事務所", KTR + "/arajo/arajo_index005.html", r"/arajo/live/(camera\d+)\.html"),
    ("arage", "荒川下流河川事務所", KTR + "/arage/arage00079.html", r"/arage/(arage00(?!079)\d+)\.html"),
    ("hitachi", "常陸河川国道事務所", KTR + "/hitachi/bousai2/web_pub/camera/10401_10_1.html",
     r"dispCamera\('([0-9_]+)'\)"),
    ("watarase_river", "渡良瀬川河川事務所（河川）", KTR + "/watarase/watarase00410.html", r"/river/cctv/(C\d{5})\.jpg"),
    ("watarase_sabo", "渡良瀬川河川事務所（砂防）", KTR + "/watarase/watarase00412.html", r"/river/cctv/(C\d{5})\.jpg"),
    ("tonesui", "利根川水系砂防事務所", KTR + "/tonesui/tonesui_index005.html",
     r"/tonesui/(tonesui(?:_index0(?:21|22|23|65)|00\d{3}))\.html"),
    ("sagami", "相模川水系広域ダム管理事務所", KTR + "/sagami/livecam/cameraselect/index.htm",
     r"cameraview/index\.htm\?cam=(\d+)"),
    ("nagano_r18", "長野国道事務所（国道18号のみ数えた）", KTR + "/nagano/douroinfo/road/html/map/cameraMap_18.html",
     r"data/camera/cond_m/(\d+)_L\.jpg"),
]
KANTO_NOT_COUNTED = {
    "keihin": "京浜河川事務所: camera list links to river.go.jp (already the japan_mlit_rivers provider)",
    "tonedamu": "利根川ダム統合管理事務所: viewer behind its own terms-agreement page (realtime2/E014010.html); not opened",
    "kinudamu": "鬼怒川ダム統合管理事務所: four dam cameras on a pixel map, no coordinates",
    "chiba": "千葉国道事務所: page links to city and roadside-station cameras on other hosts only",
}

# ---------------------------------------------------------------- MLIT Kyushu (held: no coordinates)
QSR = "https://www.qsr.mlit.go.jp"
KYUSHU_DIRECTORY = QSR + "/useful/road_livecam.html"
KYUSHU_OFFICES = [
    ("kitakyu", "北九州国道事務所", QSR + "/kitakyu/bousai/livecamera/index.html", r"/kitakyu/camera/(cam\d+_\d)\.jpg"),
    ("sakoku", "佐賀国道事務所", QSR + "/sakoku/bousai_doro/camera/index.html", r"/img/cctv/S?(\d{5})\.jpg"),
    ("nagasaki", "長崎河川国道事務所", QSR + "/nagasaki/bousai/road/index.html", None),
    ("kumamoto", "熊本河川国道事務所", QSR + "/kumamoto/bousai/road_live/index.html", r"(road_live\d+)\.html"),
    ("oita", "大分河川国道事務所", QSR + "/oita/bousaiinfo/cctv/douro.html", None),
    ("saiki", "佐伯河川国道事務所", QSR + "/saiki/cctv/douro.html", r'class="icon[^"]*"\s+value="?(\d{3})'),
    ("miyazaki", "宮崎河川国道事務所", QSR + "/miyazaki/bousai/top.html?gmn=mapSC4", None),
    ("nobeoka", "延岡河川国道事務所", QSR + "/nobeoka/bousai/pc/data/map_cctv.php?mid=douro", None),
    ("osumi", "大隅河川国道事務所", QSR + "/osumi/bousai/top.html?gmn=mapSK3", None),
    ("kakoku", "鹿児島国道事務所", QSR + "/kakoku/traffic/cctv/", r"/kakoku/cctvimg/([A-Za-z0-9_]+)\.jpg"),
]

# ---------------------------------------------------------------- policies
PDL_RIGHTS = ("Site content, including camera stills, is usable under PDL1.0 (copy, public transmission, adaptation, "
              "commercial use) unless a page carries its own rights notice; the camera pages used carry none. "
              "Source attribution (出典 + page URL) and an edit notice are mandatory; QGlobe must not present the "
              "result as made by the agency.")

POLICIES = {
    "jma_volcano_cameras": {
        "source": {
            "id": "jma_volcano_cameras",
            "name": "Japan Meteorological Agency volcano monitoring cameras (気象庁 監視カメラ画像)",
            "url": JMA_INDEX, "catalog_url": JMA_INDEX, "terms_url": JMA_TERMS,
            "metadata_license": PDL_NAME, "license": "Public Data License 1.0 (PDL1.0)", "license_url": PDL_URL,
            "media_rights": PDL_RIGHTS,
            "rights_note": ("「気象庁ホームページで公開している情報…は、権利表記の記載がない限り「公共データ利用規約（第1.0版）」に"
                            "準拠した利用条件の下で、利用することができます。」 PDL1.0: commercial use permitted. Camera "
                            "positions are the camera icons of JMA's official volcano camera map (0.001° precision)."),
            "attribution": ("出典：気象庁ホームページ（https://www.data.jma.go.jp/vois/data/obs/volcam/volcam.php ・各カメラの"
                            "ページURL）を加工して作成。QGlobeが名称・位置等のデータを正規化・編集し、画像を縮小表示しています"
                            "（気象庁が作成したものではありません）。Source: Japan Meteorological Agency website; data "
                            "normalized and edited by QGlobe, not a JMA product. PDL1.0."),
            "rights_status": "official_page_only", "allowed_hosts": [JMA_HOST],
            "minimum_refresh_seconds": 120,
            "image_url_lifecycle": ("Dated frames every 2 minutes (camera/<dir>/<JST yyyymmddhhmmss>.jpg); each camera page "
                                    "lists only about the last hour (31 frames). No stable 'latest' URL exists: the "
                                    "saved URL does not advance and is likely to disappear about an hour after "
                                    "collection unless the catalogue is rebuilt or a tap-time resolver picks the "
                                    "newest frame from the camera page."),
            "provider_notice": ("Dated JMA volcano camera frame; a newer image needs an updated catalogue. For eruption "
                                "warnings follow JMA and local authorities, not this image."),
            "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT,
            "held_media_note": ("Images allowed by the JMA terms (PDL 1.0 compatible), but frames are dated files kept "
                                "about an hour: listed as camera pages until the viewer can pick the newest frame at "
                                "tap time."),
            "evidence": [JMA_TERMS, PDL_URL, JMA_INDEX, JMA_POSITIONS],
        },
        "media_hosts": [], "page_hosts": [JMA_HOST], "formats": ["official_page"], "countries": ["JP"],
        "operator_hints": ["気象庁", "japan meteorological agency"], "coordinate_role": "camera_location",
        "official_map_url": JMA_MAP,
    },
    "mlit_kanto_cctv": {
        "source": {
            "id": "mlit_kanto_cctv",
            "name": "MLIT Kanto Regional Development Bureau river and road camera stills (関東地方整備局 ライブカメラ)",
            "url": KTR_DIRECTORY, "catalog_url": KTR_DIRECTORY, "terms_url": KTR_TERMS,
            "metadata_license": PDL_NAME, "license": "Public Data License 1.0 (PDL1.0)", "license_url": PDL_URL,
            "media_rights": PDL_RIGHTS,
            "rights_note": ("「関東地方整備局ウェブサイトで掲載・発信している情報…の著作権は、特記されていない限り関東地方整備局に帰属し、"
                            "権利表記の記載がない限り「公共データ利用規約(第1.0版)」(PDL1.0)に準拠した利用条件の下で、利用することが"
                            "できます。」 Required: 出典：関東地方整備局ウェブサイト(当該ページのURL), plus an edit notice; must not "
                            "look government-made. Only offices publishing official coordinates are included (Tone upstream "
                            "river office cameradb.json; Kita-shuto national highway office CCTV.kml)."),
            "attribution": ("出典：関東地方整備局ウェブサイト（利根川上流河川事務所 河川ライブカメラ映像 "
                            "https://www.ktr.mlit.go.jp/tonejo/cctv/ ・北首都国道事務所 国道298号ライブカメラ "
                            "https://www.ktr.mlit.go.jp/kitasyuto/public/CCTV.html ・各カメラのページURL）を加工して作成。"
                            "QGlobeが名称・位置等のデータを正規化・編集し、画像を縮小表示しています（国土交通省が作成したものでは"
                            "ありません）。Source: MLIT Kanto Regional Development Bureau website; data normalized and edited "
                            "by QGlobe, not an MLIT product. PDL1.0."),
            "rights_status": "official_public_feed", "allowed_hosts": [KTR_HOST],
            "minimum_refresh_seconds": 600,
            "image_url_lifecycle": "Stable still URLs replaced in place about every 10 minutes (Cache-Control max-age=300).",
            "review_status": "reviewed_for_snapshot_and_reference_use", "reviewed_at": REVIEWED_AT,
            "evidence": [KTR_TERMS, PDL_URL, TONEJO_DB, KITASYUTO_KML],
        },
        "media_hosts": [KTR_HOST], "page_hosts": [KTR_HOST], "formats": ["snapshot"], "countries": ["JP"],
        "operator_hints": ["関東地方整備局", "国土交通省", "mlit"], "coordinate_role": "camera_location",
    },
}


def held(source_id, name, url, reason, until, evidence):
    return {source_id: {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
                        "source": {"id": source_id, "name": name, "url": url}, "reviewed_at": REVIEWED_AT}}


HELD = {}
for _entry in [
    held("japan_mlit_rivers_snapshot_upgrade", "MLIT 川の防災情報 river cameras — snapshot upgrade of the existing "
         "page-only provider japan_mlit_rivers", "https://www.river.go.jp/kawabou/pcfull",
         "The river.go.jp terms allow reuse, but the still-image endpoint was not found (the JS bundle is over the 64 KiB "
         "sample) and the site bars periodic automated collection. The existing page-only policy japan_mlit_rivers is "
         "unchanged; this id only tracks the upgrade.",
         "A documented still-image URL per camera, user-tap fetch only (no polling), prefecture-owned cameras checked "
         "separately; scheduled refresh only through the FRICS distribution.",
         ["https://www.river.go.jp/kawabou/kwb_apend/html/caution.html"]),
    held("mlit_regional_bureaus_other", "MLIT other regional bureaus' live cameras (Hokkaido, Tohoku, Hokuriku, Chubu, "
         "Kinki, Chugoku, Shikoku, Okinawa)", "https://www.mlit.go.jp/",
         "Not verified: no bureau copyright page or image was checked in the research round.",
         "Per bureau: read the copyright page (PDL1.0 or not), one image check, and a camera list with official "
         "coordinates.", []),
    held("mlit_dpf_cctv", "MLIT Data Platform CCTV common-format dataset", "https://www.mlit-data.jp/",
         "The DPF API needs a registered API key; provider-level rights not checked.",
         "The user's decision to register, then each data provider's rules.", ["https://www.mlit-data.jp/"]),
    held("jcg_mics_livecamera", "Japan Coast Guard 'Umi no Anzen Joho' lighthouse and port live cameras",
         "https://www6.kaiho.mlit.go.jp/livecamera.html",
         "Pages exist but the JCG site terms were not located or read; coordinates not yet checked.",
         "Read the JCG site policy (PDL1.0 or not) and find official camera positions.",
         ["https://www6.kaiho.mlit.go.jp/livecamera.html"]),
    held("nexco_central_ihighway", "NEXCO Central expressway live cameras (iHighway)", "https://www.c-ihighway.jp/",
         "Partially verified: the site returned 403 to the research client and no terms were read.",
         "Terms read and a camera list with coordinates reachable without bypassing the block.", []),
    held("nexco_east_driveplaza", "NEXCO East expressway live cameras (ドラぷら)", "https://www.driveplaza.com/traffic/camera/",
         "Partially verified: area pages exist, but no reuse terms were found or read.",
         "Terms read and a camera list with coordinates.", ["https://www.driveplaza.com/traffic/camera/"]),
    held("nexco_west_ihighway", "NEXCO West expressway live cameras (iHighway)", "https://ihighway.jp/pcsite/",
         "Partially verified: single-page app shell only; terms not located.",
         "Terms read and a camera list with coordinates.", []),
]:
    HELD.update(_entry)


ETIQUETTE = {
    "robots": "Collectors ran in fresh processes after the RFC 9309 fix of webcam_fetch (class Robots). "
              "www.data.jma.go.jp, www.ktr.mlit.go.jp and www.qsr.mlit.go.jp serve no robots.txt (404).",
    "exploration": "Before the collector existed, 68 sequential exploration GETs through the same PoliteClient "
                   "(www.ktr.mlit.go.jp 45, www.qsr.mlit.go.jp 16, www.data.jma.go.jp 7) plus one refused request "
                   "(HTTP 503, www.qsr.mlit.go.jp/nobeoka/bousai/pc/data/map_cctv.php; 200 in the collector run). "
                   "All were re-checked with webcam_fetch.Robots after the fix: none disallowed, nothing deleted.",
    "image_checks": "One 64 KiB signature check per integrated viewable provider (JMA, Kanto); none for held sources.",
}


# ---------------------------------------------------------------- helpers
def text_of(body):
    if isinstance(body, str):
        return body
    head = body[:4000]
    m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', head)
    for enc in ([m.group(1).decode("ascii", "ignore")] if m else []) + ["utf-8", "shift_jis", "euc-jp"]:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def https(url):
    parts = urlsplit(url)
    return url if parts.scheme == "https" else "https" + url[len(parts.scheme):]


def valid_japan(lat, lng):
    return math.isfinite(lat) and math.isfinite(lng) and 20 <= lat <= 46.5 and 122 <= lng <= 154.5


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def main_content(text):
    i = text.find('id="main_content"')
    if i < 0:
        return text
    j = text.find("related_info", i)
    return text[i:j if j > 0 else None]


def base_item(provider, provider_id, name, lat, lng, region, observed_at, **extra):
    item = {"provider": provider, "provider_id": provider_id, "id": f"{provider}:{provider_id}", "name": name,
            "lat": round(lat, 6), "lng": round(lng, 6), "country": "JP", "region": region,
            "rights_status": "official_public_feed", "format": "snapshot", "stream_url": None,
            "observed_at": observed_at, "health": {"status": "unverified"}, "provider_in_service": None}
    item.update(extra)
    return item


# ---------------------------------------------------------------- JMA parsing (pure)
def parse_jma_index(text):
    """[(vc, name, region)] in page order; region is the list heading the camera sits under."""
    rows, seen = [], set()
    sections = re.split(r"<label for='REGION\d+'>", text)
    for section in sections[1:]:
        region = clean(section.split("</label>", 1)[0])
        for vc, name in re.findall(r"""href=['"]\./volcam\.php\?VC=(\d{5})['"]>(.*?)</a>""", section):
            if vc not in seen:
                seen.add(vc)
                rows.append((vc, clean(name), region))
    return rows


def parse_jma_positions(text):
    """{vc: (lat, lng, name)} from the official camera-icon GeoJSON (lon, lat order)."""
    data = json.loads(text.lstrip("﻿"))
    out = {}
    for feature in data.get("features", []):
        props, geom = feature.get("properties") or {}, feature.get("geometry") or {}
        code = str(props.get("code") or "")
        if not re.fullmatch(r"\d{5}", code) or geom.get("type") != "Point":
            continue
        lng, lat = (float(v) for v in geom["coordinates"][:2])
        if not valid_japan(lat, lng):
            raise ValueError(f"JMA camera {code} outside Japan or axis order changed")
        if code in out and out[code][:2] != (lat, lng):
            raise ValueError(f"Contradictory JMA camera position for {code}")
        out[code] = (lat, lng, clean(props.get("name")))
    return out


def parse_jma_camera_page(text):
    """The camera's frame directory, its dated frames (JST yyyymmddhhmmss, sorted) and the page title."""
    frames = re.findall(r'file_array\[\d+\]\s*=\s*"\.\./camera/([0-9A-Za-z_]+)/(\d{14})\.jpg"', text)
    dirs = {d for d, _ in frames}
    if len(dirs) > 1:
        raise ValueError("JMA camera page lists frames from several directories")
    title = re.search(r"<h1>監視カメラ画像（(.*?)）</h1>", text)
    return {"dir": next(iter(dirs)) if dirs else None, "frames": sorted({ts for _, ts in frames}),
            "title": clean(title.group(1)) if title else None}


def as_camera_pages(items):
    """JMA records as links to their official camera pages: no dated frame is published as a snapshot."""
    pages = []
    for item in items:
        page = dict(item, format="official_page", rights_status="official_page_only", snapshot_url=None, stream_url=None)
        for key in ("requires_catalog_refresh", "image_observed_at", "minimum_refresh_seconds"):
            page.pop(key, None)
        pages.append(page)
    return pages


def jst_to_utc(ts14):
    stamp = dt.datetime.strptime(ts14, "%Y%m%d%H%M%S").replace(tzinfo=JST)
    return stamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def jma_items(index, positions, pages, observed_at):
    """Items plus the left-out list. pages: {vc: parse_jma_camera_page(...) or None (not fetched)}."""
    items, left_out = [], []
    for vc, name, region in index:
        page_url = f"{JMA_INDEX}?VC={vc}"
        pos, page = positions.get(vc), pages.get(vc)
        if not pos:
            left_out.append({"provider_id": vc, "name": name, "reason": "no position on the official camera map"})
            continue
        if not page or not page.get("frames"):
            left_out.append({"provider_id": vc, "name": name, "reason": "camera page not fetched, or it lists no frame (distribution stopped)"})
            continue
        newest = page["frames"][-1]
        image = f"https://{JMA_HOST}/vois/data/obs/camera/{page['dir']}/{newest}.jpg"
        volcano = name.split(" ", 1)[0]
        notice = (f"出典：気象庁ホームページ（{page_url}）を加工して作成（QGlobeが名称・位置等を正規化・編集）。"
                  f"Dated JMA frame taken {newest[:4]}-{newest[4:6]}-{newest[6:8]} {newest[8:10]}:{newest[10:12]} JST; "
                  "the official page keeps about the last hour of frames.")
        items.append(base_item(
            "jma_volcano_cameras", vc, name, pos[0], pos[1], region, observed_at,
            snapshot_url=image, official_page=page_url, source_page=JMA_INDEX, source_catalog=JMA_INDEX,
            coordinate_role="camera_location", coordinate_reference_system="EPSG:4326",
            coordinate_source=JMA_POSITIONS,
            coordinate_note="Camera icon position on JMA's official volcano camera map, rounded to 0.001° (~100 m).",
            volcano=volcano, map_name=pos[2], image_observed_at=jst_to_utc(newest), requires_catalog_refresh=True,
            minimum_refresh_seconds=120, jma_camera_directory=page["dir"], image_interval_seconds=120,
            image_frames_listed=len(page["frames"]), provider_notice=notice, attribution=notice,
            operator="気象庁 (Japan Meteorological Agency)"))
    return items, left_out


# ---------------------------------------------------------------- Kanto parsing (pure)
def dms(deg, minute, sec, frac):
    """cameradb.json splits seconds into an integer part and a fraction ('.177', '0.9', '0'); '35.74','0' also occurs."""
    seconds = float(sec or 0) + float(frac or 0)
    return float(deg) + float(minute) / 60 + seconds / 3600


PREFECTURE = re.compile(r"^(東京都|北海道|(?:京都|大阪)府|.{2,3}県)")


def tonejo_items(text, observed_at):
    data = json.loads(text.lstrip("﻿"))
    block = data[0] if isinstance(data, list) else data
    items, left_out, seen = [], [], set()
    for cam in block.get("cameradata", []):
        o, urls = cam.get("obsrvtn") or [], cam.get("url") or []
        if len(o) < 14:
            left_out.append({"reason": "short cameradb row", "row": o})
            continue
        cam_id = o[9]
        if not re.fullmatch(r"cam\d+", cam_id) or cam_id in seen:
            left_out.append({"provider_id": cam_id, "reason": "missing or repeated camera id"})
            continue
        seen.add(cam_id)
        lat, lng = dms(*o[1:5]), dms(*o[5:9])
        image = (urls[2] if len(urls) > 2 and urls[2] else urls[0] if urls else "")  # the viewer's own choice
        if not valid_japan(lat, lng) or not re.fullmatch(r"cam\d+_\d+\.jpg", image or ""):
            left_out.append({"provider_id": cam_id, "reason": "invalid coordinates or image name"})
            continue
        page = TONEJO_VIEW + cam_id
        prefecture = PREFECTURE.match(o[12] or "")
        notice = (f"出典：関東地方整備局ウェブサイト（利根川上流河川事務所 河川ライブカメラ映像 {page}）を加工して作成"
                  "（QGlobeが名称・位置等を正規化・編集）。国土交通省が作成したものではありません。")
        items.append(base_item(
            "mlit_kanto_cctv", "tonejo-" + cam_id, f"{o[10]} {o[0]}".strip(), lat, lng,
            prefecture.group(1) if prefecture else "関東", observed_at,
            snapshot_url=TONEJO_IMAGES + image, official_page=page, source_page=TONEJO_LIST,
            source_catalog=TONEJO_DB, coordinate_role="camera_location", coordinate_reference_system="EPSG:4326",
            coordinate_source=TONEJO_DB,
            coordinate_note="Official DMS position from the office's camera database; matches river.go.jp (EPSG:4326).",
            river=o[10], river_position=o[11], address=o[12], station_name=o[13], office=KANTO_OFFICE_NAMES["tonejo"],
            minimum_refresh_seconds=600, provider_notice=notice, attribution=notice,
            operator="国土交通省 関東地方整備局 利根川上流河川事務所"))
    return items, left_out


def kitasyuto_items(text, observed_at):
    """One record per still image (C#####.jpg); placemarks with several cameras give a shared site point."""
    items, left_out, seen = [], [], {}
    for placemark in re.findall(r"<Placemark>(.*?)</Placemark>", text, re.S):
        coords = re.search(r"<coordinates>\s*([-0-9.]+)\s*,\s*([-0-9.]+)", placemark)
        site = clean((re.search(r"<name>(.*?)</name>", placemark, re.S) or [None, ""])[1])
        if not coords:
            continue
        lng, lat = float(coords.group(1)), float(coords.group(2))
        desc = (re.search(r"<description>(.*?)</description>", placemark, re.S) or [None, ""])[1]
        labels, images, order = collections.defaultdict(list), {}, []
        for href, inner in re.findall(r'<a\s+href="([^"]+CAM_[^"]+\.html)"[^>]*>(.*?)</a>', desc, re.S):
            if href not in order:
                order.append(href)
            tag = re.search(r'<img\s+src="([^"]+/river/cctv/(C\d{5})\.jpg)"[^>]*>', inner)
            if tag and href not in images:
                title = re.search(r'(?:title|alt)="([^"]*)"', tag.group(0))
                images[href] = (tag.group(1), tag.group(2), title.group(1) if title else "")
            labels[href].extend(p for p in (clean(x) for x in re.split(r"<br\s*/?>", re.sub(r"<img[^>]*>", "", inner)))
                                if p)
        cams = [(href, *images[href]) for href in order if href in images]
        for href, img, image_id, title in cams:
            role = "camera_location" if len(cams) == 1 else "station_location"
            if image_id in seen:
                if distance_m(lat, lng, *seen[image_id]) > 50:
                    left_out.append({"provider_id": image_id, "reason": "contradictory placemark positions"})
                continue
            if not valid_japan(lat, lng):
                left_out.append({"provider_id": image_id, "reason": "invalid coordinates"})
                continue
            seen[image_id] = (lat, lng)
            page = https(href)
            text_labels = labels.get(href, [])
            kp = next((x for x in text_labels if "kp" in x), None)
            address = next((x for x in text_labels if x != kp), None)
            name_title = clean(title) if title and title != "カメラ個別ページ" else site
            direction = "上り" if "上り" in (kp or name_title) else "下り" if "下り" in (kp or name_title) else None
            notice = (f"出典：関東地方整備局ウェブサイト（北首都国道事務所 国道298号ライブカメラ {page}）を加工して作成"
                      "（QGlobeが名称・位置等を正規化・編集）。国土交通省が作成したものではありません。")
            prefecture = PREFECTURE.match(address or "")
            items.append(base_item(
                "mlit_kanto_cctv", image_id, f"国道298号 {name_title}", lat, lng,
                prefecture.group(1) if prefecture else "埼玉県", observed_at,
                snapshot_url=https(img), official_page=page, source_page=KITASYUTO_PAGE,
                source_catalog=KITASYUTO_KML, coordinate_role=role, coordinate_reference_system="EPSG:4326",
                coordinate_source=KITASYUTO_KML,
                coordinate_note=("Official KML placemark of the camera site" + ("" if role == "camera_location" else
                                 f" '{site}', shared by {len(cams)} cameras (up/down lanes)") + "."),
                road="R298", kilometre_post=kp, address=address, direction=direction, site=site,
                office=KANTO_OFFICE_NAMES["kitasyuto"], minimum_refresh_seconds=600, provider_notice=notice,
                attribution=notice, operator="国土交通省 関東地方整備局 北首都国道事務所"))
    return items, left_out


def count_listed(text, pattern):
    """Distinct camera identifiers a directory page lists (main content only); None when uncountable."""
    if not pattern:
        return None
    return sorted(set(re.findall(pattern, main_content(text))))


# ---------------------------------------------------------------- overlaps (offline, informative)
def overlap_report(items, catalog_path, radius=100.0):
    if not catalog_path or not Path(catalog_path).exists():
        return {"checked": False}
    rows = json.loads(Path(catalog_path).read_text(encoding="utf-8")).get("items", [])
    grid = collections.defaultdict(list)
    for row in rows:
        if isinstance(row.get("lat"), (int, float)) and isinstance(row.get("lng"), (int, float)):
            grid[(int(row["lat"] * 100), int(row["lng"] * 100))].append(row)
    found = collections.defaultdict(list)
    for item in items:
        gy, gx = int(item["lat"] * 100), int(item["lng"] * 100)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for row in grid.get((gy + dy, gx + dx), ()):
                    d = distance_m(item["lat"], item["lng"], row["lat"], row["lng"])
                    if d <= radius and row.get("provider") != item["provider"]:
                        found[item["id"]].append({"existing": row["id"], "provider": row.get("provider"),
                                                  "name": row.get("name"), "format": row.get("format"),
                                                  "distance_m": round(d, 1)})
    by_provider = collections.Counter(m["provider"] for ms in found.values() for m in ms)
    return {"checked": True, "radius_m": radius, "records_with_nearby_existing": len(found),
            "nearby_by_existing_provider": dict(by_provider),
            "nearest_existing": {k: min(v, key=lambda m: m["distance_m"])["existing"] for k, v in sorted(found.items())},
            "examples": {k: sorted(v, key=lambda m: m["distance_m"])[:2] for k, v in list(sorted(found.items()))[:6]}}


# ---------------------------------------------------------------- acquisition (network)
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


def acquire(out):
    a = Acquirer(out)
    a.get("jma_volcano_cameras", "volcam_index.html", JMA_INDEX)
    a.get("jma_volcano_cameras", "camicon.geojson", JMA_POSITIONS)
    index = parse_jma_index(text_of((Path(out) / "raw/jma_volcano_cameras/volcam_index.html").read_bytes()))
    for vc, _, _ in index:
        a.get("jma_volcano_cameras", f"pages/VC_{vc}.html", f"{JMA_INDEX}?VC={vc}")
    a.get("mlit_kanto_cctv", "tonejo_cameradb.json", TONEJO_DB)
    a.get("mlit_kanto_cctv", "kitasyuto_CCTV.kml", KITASYUTO_KML)
    a.get("mlit_kanto_cctv", "guide00000012.html", KTR_DIRECTORY)
    for key, _, url, _ in KANTO_UNPLACED:
        a.get("mlit_kanto_cctv", f"unplaced/{key}.html", url)
    a.get("mlit_kyushu_road_cameras", "road_livecam.html", KYUSHU_DIRECTORY)
    for key, _, url, _ in KYUSHU_OFFICES:
        a.get("mlit_kyushu_road_cameras", f"offices/{key}.html", url)
    return a


def read_raw(out, source, name):
    path = Path(out) / "raw" / source / name
    if not path.exists():
        return None, None
    receipt = json.loads((path.parent / (path.name + ".receipt.json")).read_text(encoding="utf-8"))
    return text_of(path.read_bytes()), receipt


# ---------------------------------------------------------------- build (offline from raw)
def build(out, catalog=None, refused=()):
    out = Path(out)
    report = {"family": FAMILY, "generated_at": F.now(), "sources": [], "held": [], "hosts_refused": list(refused),
              "etiquette": ETIQUETTE}
    # JMA
    index_text, index_receipt = read_raw(out, "jma_volcano_cameras", "volcam_index.html")
    pos_text, _ = read_raw(out, "jma_volcano_cameras", "camicon.geojson")
    index, positions = parse_jma_index(index_text), parse_jma_positions(pos_text)
    pages = {}
    for vc, _, _ in index:
        page_text, _ = read_raw(out, "jma_volcano_cameras", f"pages/VC_{vc}.html")
        pages[vc] = parse_jma_camera_page(page_text) if page_text else None
    jma, jma_out = jma_items(index, positions, pages, index_receipt["observed_at"])
    jma = as_camera_pages(jma)
    F.write_catalog(out / "jma_volcano_cameras.json", ["jma_volcano_cameras"], jma)
    report["sources"].append({
        "id": "jma_volcano_cameras", "country": "JP", "input_file": "jma_volcano_cameras.json",
        "records": {"viewable": 0, "page_only": len(jma)}, "index_cameras": len(index),
        "map_positions": len(positions), "left_out": jma_out,
        "robots": "https://www.data.jma.go.jp/robots.txt: 404 (no rules)",
        "changes_from_register": [
            "Coordinates: official camera-icon positions from JMA's map GeoJSON (camera_location, 0.001°) instead of "
            "volcano summits as associated_feature.",
            "Camera pages, not snapshots: frames are dated files kept about an hour, so a catalogue snapshot would "
            "be a dead image soon after each build."],
        "overlaps": overlap_report(jma, catalog)})
    # Kanto
    tonejo_text, tonejo_receipt = read_raw(out, "mlit_kanto_cctv", "tonejo_cameradb.json")
    kml_text, _ = read_raw(out, "mlit_kanto_cctv", "kitasyuto_CCTV.kml")
    tonejo, tonejo_out = tonejo_items(tonejo_text, tonejo_receipt["observed_at"])
    kita, kita_out = kitasyuto_items(kml_text, tonejo_receipt["observed_at"])
    kanto = sorted(tonejo + kita, key=lambda x: x["id"])
    F.write_catalog(out / "mlit_kanto_cctv.json", ["mlit_kanto_cctv"], kanto)
    unplaced = []
    for key, office, url, pattern in KANTO_UNPLACED:
        text, receipt = read_raw(out, "mlit_kanto_cctv", f"unplaced/{key}.html")
        listed = count_listed(text, pattern) if text else None
        unplaced.append({"office": office, "url": url, "fetched": bool(text),
                         "cameras_listed": len(listed) if listed is not None else None})
    unplaced_total = sum(u["cameras_listed"] or 0 for u in unplaced)
    report["sources"].append({
        "id": "mlit_kanto_cctv", "country": "JP", "input_file": "mlit_kanto_cctv.json",
        "records": {"viewable": len(kanto), "page_only": 0},
        "by_office": dict(collections.Counter(x["office"] for x in kanto)),
        "left_out": tonejo_out + kita_out,
        "unplaced_no_official_coordinates": {"cameras_counted_lower_bound": unplaced_total, "offices": unplaced,
                                             "not_counted": KANTO_NOT_COUNTED},
        "robots": "https://www.ktr.mlit.go.jp/robots.txt: 404 (no rules)",
        "changes_from_register": [
            "Register estimated ~500 approximate records; only offices publishing official coordinates are integrated "
            "(Tone upstream river office, Kita-shuto road office). Route/km-only offices are counted and left out.",
            "Tone upstream river cameras are the same physical cameras as page-only japan_mlit_rivers records "
            "(identical coordinates): see overlaps."],
        "overlaps": overlap_report(kanto, catalog)})
    # Kyushu (held)
    offices = []
    for key, office, url, pattern in KYUSHU_OFFICES:
        text, _ = read_raw(out, "mlit_kyushu_road_cameras", f"offices/{key}.html")
        listed = count_listed(text, pattern) if text else None
        offices.append({"office": office, "url": url, "fetched": bool(text), "official_coordinates": False,
                        "cameras_listed": len(listed) if listed is not None else None})
    kyushu_total = sum(o["cameras_listed"] or 0 for o in offices)
    HELD.update(held(
        "mlit_kyushu_road_cameras", "MLIT Kyushu Regional Development Bureau national-highway live cameras",
        KYUSHU_DIRECTORY,
        (f"No office page publishes camera coordinates (pixel image maps, route/km labels or JS maps only), so none "
         f"of the cameras can be placed: at least {kyushu_total} stills/camera pages counted on the office "
         f"directory pages fetched. PDL1.0 terms are fine (bureau /pp/ and Kumamoto office)."),
        "An official camera list with coordinates (or MLIT DPF records, held for a key). Fukuoka office "
        "(road-info-prvs.mlit.go.jp) and NEXCO links stay out.",
        [QSR + "/pp/index.html", "https://www.qsr.mlit.go.jp/kumamoto/link_copyright.html", KYUSHU_DIRECTORY]))
    report["kyushu_offices"] = offices
    # policies
    for pid, policy in {**POLICIES, **HELD}.items():
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{pid}.json").write_text(json.dumps({pid: policy}, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    report["held"] = [{"id": k, "reason": v["held_reason"]} for k, v in sorted(HELD.items())]
    return report, {"mlit_kanto_cctv": kanto}


def run_checks(out, items_by_source, client=None):
    """One image check per integrated viewable provider, on the first record (sorted by id)."""
    client = client or F.PoliteClient(delay=1.2)
    results = {}
    for source, items in items_by_source.items():
        if not items:
            continue
        first = items[0]
        hosts = POLICIES[source]["media_hosts"]
        event = client.check_image(first["snapshot_url"], source, first["id"], hosts)
        (out / "checks").mkdir(parents=True, exist_ok=True)
        (out / "checks" / f"{source}.snapshot.json").write_text(json.dumps([event], ensure_ascii=False, indent=1),
                                                                 encoding="utf-8")
        results[source] = {k: event.get(k) for k in ("record_id", "url", "status", "http_status", "signature",
                                                      "content_type", "bytes_read", "inconclusive_reason")}
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--catalog", type=Path, help="current data/webcams.json, for the overlap report only")
    ap.add_argument("--offline", action="store_true", help="rebuild from saved raw responses; no network")
    ap.add_argument("--no-check", action="store_true", help="skip the image checks")
    args = ap.parse_args()
    refused = []
    if not args.offline:
        refused = acquire(args.out).refused
    report, items = build(args.out, args.catalog, refused)
    checks_path = args.out / "reports" / f"{FAMILY}.checks.json"
    if not args.offline and not args.no_check:
        checks = run_checks(args.out, {k: sorted(v, key=lambda x: x["id"]) for k, v in items.items()})
        checks_path.parent.mkdir(parents=True, exist_ok=True)
        checks_path.write_text(json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")
    if checks_path.exists():
        checks = json.loads(checks_path.read_text(encoding="utf-8"))
        for source in report["sources"]:
            source["sample_check"] = checks.get(source["id"])
    if args.offline:
        previous = args.out / "reports" / f"{FAMILY}.json"
        if previous.exists():
            report["hosts_refused"] = json.loads(previous.read_text(encoding="utf-8")).get("hosts_refused", [])
    (args.out / "reports").mkdir(parents=True, exist_ok=True)
    (args.out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({s["id"]: s["records"] for s in report["sources"]}, ensure_ascii=False))
    print("held:", [h["id"] for h in report["held"]], "refused:", report["hosts_refused"])


if __name__ == "__main__":
    main()
