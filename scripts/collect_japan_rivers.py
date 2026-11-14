#!/usr/bin/env python3
"""Japanese river cameras and the round-2 Japan sources for the Q-Globe catalogue (2026-11-14, round 2).

japan_mlit_rivers (upgrade, supersedes the package records)
    The full current camera list of MLIT 川の防災情報 (per-area GeoJSON, EPSG:4326). Ownership rule: a camera
    is the State's when its owner code own_cd is a 5-digit code 20000-29999 (MLIT river/dam offices, Hokkaido
    development bureaus), cross-checked with the owner name (ownName) of the per-camera master JSON. Only those,
    when not paused (pause 0) and with an image URL, become snapshots on cam.river.go.jp; every other camera
    (prefectures, cities, other bodies: third-party content under the site terms) stays a page link to its
    river.go.jp camera page. Image URLs: simple cameras (sys_id 1) cam/now/{id}.jpg; CCTV cameras (sys_id 2)
    currProvUrl from the master JSON, looked up once (sequential, >= 1 s apart, cached in
    raw/japan_mlit_rivers/master_cache.jsonl so that rebuilds need no network).
mlit_kanto_cctv (notice)
    The Tone upstream office's CCTV operating guideline (運営指針 4-5) asks that viewers be told images may stop
    or change in emergencies: a superseding input adds that note to the office's records (ids unchanged).
japan_prefectural_road_camera_portals (page links)
    Prefectural / municipal / road-corporation camera portals from MLIT's official link page, placed at the
    prefectural office position of the Geospatial Information Authority's table (coordinate_role approximate).
Held with reasons (policy fragments only): see HELD.

Steps (network steps only through webcam_fetch.PoliteClient):
  lookup   area lists + per-camera master JSON lookups (long: run in the background; resumable; progress log
           and a .done file under <out>/progress/)
  pages    MLIT portal link page, GSI prefectural office table, NEXCO East camera index (coordinates check)
  check    one 64 KiB image check on one national camera
  build    offline: normalized inputs, policy fragments, report

  python scripts/collect_japan_rivers.py --out <SCRATCH>/webcam-inputs-2026-11 lookup|pages|check|build
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as F  # noqa: E402

FAMILY = "japan_rivers"
REVIEWED_AT = "2026-11-14"
SOURCE = "japan_mlit_rivers"

RIVER = "https://www.river.go.jp"
RIVER_HOST = "www.river.go.jp"
CAM_HOST = "cam.river.go.jp"
RIVER_TOP = RIVER + "/kawabou/pcfull"
RIVER_TERMS = RIVER + "/kawabou/kwb_apend/html/caution.html"
LIST_URL = RIVER + "/kawabou/file/gjson/scam/{area}.json"
MASTER_URL = RIVER + "/kawabou/file/files/master/obs/scam/{id}.json"
SIMPLE_IMAGE = "https://cam.river.go.jp/cam/now/{id}.jpg"
CAMERA_PAGE = (RIVER + "/kawabou/pc/tm?zm=15&clat={lat}&clon={lng}&itmkndCd={kind}&scamId={id}&ownCd={own}"
               "&sysCamId={sys_cam}&ext=1")
# The per-area lists of the package collection (Hokkaido 102-105, then prefecture NN01); 101, 106 and 4701 are
# asked as well in case a list exists there now (a 404 is recorded, not an error).
AREAS = ["102", "103", "104", "105"] + [f"{n}01" for n in range(2, 47)]
AREA_PROBES = ["101", "106", "4701"]
PREFECTURES = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県", "埼玉県",
               "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県",
               "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県",
               "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県",
               "宮崎県", "鹿児島県", "沖縄県"]


def area_prefecture(area):
    """JIS prefecture name of a list area: 101-106 are Hokkaido's sub-areas, NN01 is prefecture NN."""
    code = int(area)
    return PREFECTURES[0] if 100 <= code < 200 else PREFECTURES[code // 100 - 1]


# ---------------------------------------------------------------- ownership (the rule used)
def is_national(own_cd):
    """The research register's rule: own_cd 2xxxx (5 digits starting with 2) = MLIT river/dam offices and
    Hokkaido development bureaus, i.e. the State. Every other code (prefectures and their civil-engineering
    offices: 3-digit, 4-digit and 1xxxx codes; municipalities: 6- and 7-digit codes) is a third party under
    the site terms."""
    return type(own_cd) is int and 20000 <= own_cd <= 29999


def owner_class(own_cd):
    if is_national(own_cd):
        return "state"
    digits = len(str(own_cd)) if type(own_cd) is int and own_cd > 0 else 0
    return "prefecture" if digits in (3, 4) or digits == 5 and str(own_cd)[0] == "1" else \
        "municipality" if digits in (6, 7) else "unknown"


# A non-State owner name: bare prefecture name, prefecture + department/division, prefectural civil-engineering
# office or centre, a subprefecture, a city/town/village, or the Water Resources Agency (an independent
# administrative agency, not the State). Used only to flag a 2xxxx code whose owner name disagrees.
LOCAL_OWNER = re.compile(r"^(?:北海道(?!開発)|東京都|京都府|大阪府|[^\s]{2,3}県)(?:$|.*[部課局]$)|土木(?:建築)?(?:事務所|部)"
                         r"|土木センター|県土整備|支庁$|水資源機構|[市町村]$")


def owner_conflict(own_name):
    """True when an owner name reads as a prefecture or municipality."""
    return bool(own_name) and bool(LOCAL_OWNER.search(own_name))


# ---------------------------------------------------------------- list parsing (pure)
def parse_area_list(text, area):
    """Cameras of one area list: dicts with the list fields; GeoJSON lon,lat order turned around."""
    data = json.loads(text.lstrip("﻿"))
    crs = json.dumps(data.get("crs") or {})
    if "4326" not in crs and "CRS84" not in crs and data.get("crs") is not None:
        raise ValueError(f"area {area}: unexpected CRS {crs}")
    cams = []
    for feature in data.get("features", []):
        props, geom = feature.get("properties") or {}, feature.get("geometry") or {}
        if geom.get("type") != "Point" or not isinstance(props.get("id"), int):
            continue
        lng, lat = (float(v) for v in geom["coordinates"][:2])
        cams.append({"id": props["id"], "name": props.get("name") or "", "lat": lat, "lng": lng,
                     "lat_text": coordinate_text(geom["coordinates"][1]), "lng_text": coordinate_text(geom["coordinates"][0]),
                     "own_cd": props.get("own_cd"), "sys_id": props.get("sys_id"),
                     "sys_cam_id": str(props.get("sys_cam_id") or ""), "pause": props.get("pause"),
                     "cam_kind": props.get("cam_kind"), "date_type": props.get("date_type"), "ofc_cd": props.get("ofc_cd"),
                     "area": area})
    return cams


def coordinate_text(value):
    """The number as the list writes it (shortest repr of the parsed JSON number), for the camera page URL."""
    return str(value)


def needs_lookup(cam):
    """A national CCTV camera (sys_id 2) in service: its image name is only in the master JSON."""
    return is_national(cam["own_cd"]) and cam["sys_id"] == 2 and cam["pause"] == 0


def lookup_plan(cams):
    """Ids to look up: every national active CCTV camera, then one camera per owner code not covered by those
    (owner-name confirmation for every owner, and the sys_id 1 image-name derivation per national owner)."""
    main = sorted({c["id"] for c in cams if needs_lookup(c)})
    chosen, by_owner = set(main), collections.defaultdict(list)
    for c in cams:
        by_owner[c["own_cd"]].append(c)
    extra = []
    for own, group in sorted(by_owner.items(), key=lambda kv: str(kv[0])):
        def rank(c):
            return (c["pause"] != 0, c["sys_id"] != 1, c["id"])
        pick = min(group, key=rank)
        if is_national(own) and pick["sys_id"] == 1 and pick["pause"] == 0:
            extra.append(pick["id"])  # derivation check for this owner's simple cameras
        elif not any(c["id"] in chosen for c in group):
            extra.append(pick["id"])
    return main, sorted(set(extra) - set(main))


# ---------------------------------------------------------------- master cache
def cache_path(out):
    return Path(out) / "raw" / SOURCE / "master_cache.jsonl"


def load_cache(path):
    """{id: entry}; the last line for an id wins. Only final answers (200 with JSON, 404) are cached."""
    cache = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entry = json.loads(line)
                cache[int(entry["id"])] = entry
    return cache


def master_fields(entry):
    """The fields the build uses from one cached master JSON (None when not found)."""
    if not entry or entry.get("status") != 200:
        return None
    info = (entry.get("master") or {}).get("obsInfo") or {}
    return {k: info.get(k) for k in ("ownCd", "ownName", "sysId", "sysCamId", "pause", "currProvUrl", "normProvUrl",
                                     "currDateProvUrl", "rvrNm", "rsysNm", "addr", "twnNm", "prefNm", "lat", "lon", "name")}


# ---------------------------------------------------------------- lookup run (network, long, resumable)
class Progress:
    def __init__(self, out, name):
        self.dir = Path(out) / "progress"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_path, self.done_path = self.dir / f"{name}.log", self.dir / f"{name}.done"

    def log(self, message):
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"{F.now()} {message}\n")

    def done(self, summary):
        self.done_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_lists(client, out, progress):
    folder = Path(out) / "raw" / SOURCE / "lists"
    status = {}
    for area in AREAS + AREA_PROBES:
        url = LIST_URL.format(area=area)
        try:
            r = client.get(url, max_bytes=16 * 1024 * 1024, accept="application/json")
        except F.Refused as e:
            status[area] = {"url": url, "refused": str(e)}
            progress.log(f"list {area} refused: {e}")
            raise
        except OSError as e:
            status[area] = {"url": url, "error": f"{type(e).__name__}: {str(e)[:160]}"}
            progress.log(f"list {area} error: {e}")
            continue
        status[area] = {"url": url, "status": r["status"], "bytes": len(r["body"])}
        if r["status"] == 200:
            F.save_raw(folder, f"{area}.json", r)
        progress.log(f"list {area}: HTTP {r['status']} {len(r['body'])} B")
    (Path(out) / "raw" / SOURCE / "lists_status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
    return status


def read_lists(out):
    """All cameras of the saved area lists, plus {area: receipt}."""
    folder = Path(out) / "raw" / SOURCE / "lists"
    cams, receipts = [], {}
    for path in sorted(folder.glob("*.json")):
        if path.name.endswith(".receipt.json"):
            continue
        area = path.stem
        receipts[area] = json.loads((folder / (path.name + ".receipt.json")).read_text(encoding="utf-8"))
        cams.extend(parse_area_list(path.read_text(encoding="utf-8-sig"), area))
    return cams, receipts


def run_lookup(out, delay=1.2, refetch_lists=True):
    progress = Progress(out, "japan_rivers_lookup")
    if progress.done_path.exists():
        progress.done_path.unlink()
    started = time.monotonic()
    client = F.PoliteClient(delay=delay)
    summary = {"status": "running", "started_at": F.now()}
    try:
        if refetch_lists or not (Path(out) / "raw" / SOURCE / "lists").exists():
            summary["lists"] = fetch_lists(client, out, progress)
        cams, _ = read_lists(out)
        main, extra = lookup_plan(cams)
        cache_file = cache_path(out)
        cache = load_cache(cache_file)
        todo = [i for i in extra + main if i not in cache]
        progress.log(f"cameras {len(cams)}; lookups planned {len(main)} CCTV + {len(extra)} owner samples; "
                     f"cached {len(cache)}; to do {len(todo)}")
        errors, consecutive, done = [], 0, 0
        with cache_file.open("a", encoding="utf-8") as sink:
            for cam_id in todo:
                url = MASTER_URL.format(id=cam_id)
                try:
                    r = client.get(url, max_bytes=64 * 1024, accept="application/json")
                except F.Refused as e:
                    summary.update(status="stopped", reason=f"refused: {e}")
                    progress.log(f"STOP {cam_id}: {e}")
                    break
                except OSError as e:
                    consecutive += 1
                    errors.append({"id": cam_id, "error": f"{type(e).__name__}: {str(e)[:160]}"})
                    progress.log(f"error {cam_id}: {e}")
                    if consecutive >= 5:
                        summary.update(status="stopped", reason="5 consecutive network errors")
                        break
                    continue
                consecutive = 0
                entry = {"id": cam_id, "url": url, "status": r["status"], "fetched_at": r["observed_at"],
                         "bytes": len(r["body"]), "sha256": hashlib.sha256(r["body"]).hexdigest()}
                if r["status"] == 200:
                    try:
                        entry["master"] = json.loads(r["body"].decode("utf-8-sig"))
                    except ValueError:
                        errors.append({"id": cam_id, "error": "not JSON"})
                        continue
                elif r["status"] != 404:
                    errors.append({"id": cam_id, "error": f"HTTP {r['status']}"})
                    continue
                sink.write(json.dumps(entry, ensure_ascii=False) + "\n")
                sink.flush()
                done += 1
                if done % 50 == 0:
                    rate = (time.monotonic() - started) / max(1, done)
                    progress.log(f"{done}/{len(todo)} looked up; {len(errors)} errors; "
                                 f"about {round(rate * (len(todo) - done) / 60)} min left")
        if summary["status"] == "running":
            summary["status"] = "complete" if not errors else "complete_with_errors"
        summary.update(looked_up_this_run=done, errors=errors[:50], error_count=len(errors),
                       planned={"cctv": len(main), "owner_samples": len(extra)},
                       cached_total=len(load_cache(cache_file)), requests=len(client.log),
                       finished_at=F.now(), run_seconds=round(time.monotonic() - started))
    except F.Refused as e:
        summary.update(status="stopped", reason=f"refused: {e}", finished_at=F.now(),
                       run_seconds=round(time.monotonic() - started))
    except Exception as e:  # noqa: BLE001 - the done file must say why the run ended
        summary.update(status="failed", reason=f"{type(e).__name__}: {e}", finished_at=F.now(),
                       run_seconds=round(time.monotonic() - started))
        raise
    finally:
        log_file = Path(out) / "raw" / SOURCE / f"lookup_requests_{summary['started_at'].replace(':', '')}.json"
        log_file.write_text(json.dumps(client.log), encoding="utf-8")
        progress.log(f"end: {summary['status']} {summary.get('reason', '')}")
        progress.done(summary)
    return summary


# ---------------------------------------------------------------- river items (pure)
IMAGE_URL = re.compile(r"https://cam\.river\.go\.jp/cam/now/[A-Za-z0-9_.-]+\.jpg")


def camera_page(cam):
    """The camera's own river.go.jp page (map centred on it, camera panel open), as the package built it."""
    return CAMERA_PAGE.format(lat=cam["lat_text"], lng=cam["lng_text"], kind=200 if cam["sys_id"] == 1 else 100,
                              id=cam["id"], own=cam["own_cd"], sys_cam=cam["sys_cam_id"])


def owner_names(cams, cache):
    """{list own_cd: owner name} from the cached master JSONs (keyed by the list's code)."""
    names = {}
    for cam in sorted(cams, key=lambda c: c["id"]):
        master = master_fields(cache.get(cam["id"]))
        if master and master.get("ownName") and cam["own_cd"] not in names:
            names[cam["own_cd"]] = master["ownName"]
    return names


def image_for(cam, entry, owner_name):
    """(snapshot URL, None) for a State camera in service with a known still, else (None, reason)."""
    if not is_national(cam["own_cd"]):
        return None, f"third_party_owner_{owner_class(cam['own_cd'])}"
    if cam["pause"] != 0:
        return None, "paused"
    master = master_fields(entry)
    if master and master.get("pause") not in (None, 0):
        return None, "paused"
    if master and master.get("ownCd") is not None and not is_national(master["ownCd"]):
        return None, "master_owner_not_state"
    if owner_conflict((master or {}).get("ownName") or owner_name):
        return None, "owner_name_reads_local"
    if cam["sys_id"] == 1:
        return SIMPLE_IMAGE.format(id=cam["id"]), None
    if cam["sys_id"] != 2:
        return None, "no_image_rule_for_system"
    if entry is None:
        return None, "lookup_missing"
    if entry.get("status") == 404:
        return None, "lookup_not_found"
    url = (master or {}).get("currProvUrl") or ""
    return (url, None) if IMAGE_URL.fullmatch(url) else (None, "no_image_url_in_master")


PAGE_ONLY_NOTES = {
    "paused": "State camera marked paused (pause flag) in the official list: link to its page only.",
    "lookup_missing": "State camera whose image name was not looked up: link to its page only.",
    "lookup_not_found": "State camera without a master record (404): link to its page only.",
    "no_image_url_in_master": "State camera without a published still URL: link to its page only.",
    "master_owner_not_state": "Owner in the camera's master record is not the State: link to its page only.",
    "owner_name_reads_local": "Owner name reads as a prefecture or municipality: link to its page only.",
    "no_image_rule_for_system": "No still URL rule for this camera system: link to its page only.",
}


def river_item(cam, receipt, entry, owner_name):
    snapshot, reason = image_for(cam, entry, owner_name)
    master = master_fields(entry) or {}
    page = camera_page(cam)
    own_name = master.get("ownName") or owner_name
    item = {"provider": SOURCE, "provider_id": str(cam["id"]), "id": f"{SOURCE}:{cam['id']}", "name": cam["name"],
            "lat": cam["lat"], "lng": cam["lng"], "country": "JP", "region": area_prefecture(cam["area"]),
            "format": "snapshot" if snapshot else "official_page", "stream_url": None, "snapshot_url": snapshot,
            "source_page": RIVER_TOP, "source_catalog": LIST_URL.format(area=cam["area"]), "official_page": page,
            "reference_url": None,
            "rights_status": "official_public_feed" if snapshot else "official_page_only",
            "observed_at": receipt["observed_at"], "health": {"status": "unverified"}, "provider_in_service": None,
            "coordinate_role": "camera_location", "coordinate_reference_system": "EPSG:4326", "link_scope": "camera",
            "published_system_id": cam["sys_id"], "published_owner_code": cam["own_cd"],
            "published_system_camera_id": cam["sys_cam_id"], "published_pause_flag": cam["pause"],
            "published_camera_kind": cam["cam_kind"], "prefecture_code": cam["area"],
            "published_format": "provider_camera_page", "owner_class": owner_class(cam["own_cd"])}
    if own_name:
        item["owner_name"] = own_name
    for key, field in (("rvrNm", "river"), ("addr", "address")):
        if master.get(key):
            item[field] = master[key]
    if snapshot:
        item.update(
            minimum_refresh_seconds=600,
            image_source="list id (sys_id 1)" if cam["sys_id"] == 1 else "master JSON currProvUrl (sys_id 2)",
            operator_office=own_name or None)
        if cam["sys_id"] == 2:
            item["image_url_looked_up_at"] = entry["fetched_at"]
    elif reason.startswith("third_party_owner"):
        item["page_only_reason"] = "third_party_owner"
        item["provider_notice"] = (f"{own_name or '都道府県・市町村'}のカメラ（国以外の者のコンテンツ）：画像は川の防災情報の公式ページで"
                                   "ご覧ください。Camera of a prefecture, municipality or other body: third-party content "
                                   "under the river.go.jp terms, so only its official page is linked.")
    else:
        item["page_only_reason"] = reason
        item["provider_notice"] = PAGE_ONLY_NOTES[reason]
    return item, reason


def river_items(cams, receipts, cache):
    names = owner_names(cams, cache)
    items, reasons = [], collections.Counter()
    for cam in sorted(cams, key=lambda c: c["id"]):
        item, reason = river_item(cam, receipts[cam["area"]], cache.get(cam["id"]), names.get(cam["own_cd"]))
        items.append(item)
        reasons["viewable" if reason is None else reason] += 1
    ids = collections.Counter(x["id"] for x in items)
    if any(n > 1 for n in ids.values()):
        raise ValueError("camera id listed twice across area lists")
    return items, reasons, names


def compare_with_package(items, package_items):
    """Id continuity with the records already in the catalogue (all ids must be kept)."""
    new = {x["provider_id"]: x for x in items}
    old = {x["provider_id"]: x for x in package_items if x.get("provider") == SOURCE}
    return {"package_records": len(old), "current_records": len(new),
            "package_ids_missing_now": sorted(set(old) - set(new))[:50],
            "package_ids_missing_now_count": len(set(old) - set(new)),
            "new_ids_count": len(set(new) - set(old)),
            "official_page_changed": sum(1 for k in set(old) & set(new) if old[k]["official_page"] != new[k]["official_page"]),
            "name_changed": sum(1 for k in set(old) & set(new) if old[k]["name"] != new[k]["name"])}


# ---------------------------------------------------------------- Kanto: Tone upstream office note (pure)
TONEJO_GUIDELINE = "https://www.ktr.mlit.go.jp/tonejo/m/m-bousai/live/1421.htm"
TONEJO_NOTE = ("映像は非常時等に停止・変更する場合があります（利根川上流河川事務所 CCTV運営指針 4-5）。"
               "The images may stop or change in emergencies.")


def kanto_with_tonejo_note(doc):
    """The round-1 mlit_kanto_cctv records, the Tone upstream office's ones (tonejo-*) with the 4-5 note."""
    items, noted = [], 0
    for item in doc["items"]:
        item = dict(item)
        if item.get("provider") == "mlit_kanto_cctv" and str(item.get("provider_id", "")).startswith("tonejo-"):
            if TONEJO_NOTE not in (item.get("provider_notice") or ""):
                item["provider_notice"] = ((item.get("provider_notice") or "") + " " + TONEJO_NOTE).strip()
            item["operating_guideline_url"] = TONEJO_GUIDELINE
            noted += 1
        items.append(item)
    return items, noted


# ---------------------------------------------------------------- prefectural road camera portals (pure)
PORTALS_SOURCE = "japan_prefectural_road_camera_portals"
MLIT_LIVE = "https://www.mlit.go.jp/road/bosai/LIVEcamera.html"
AMEDAS = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
NAGANO_PAGE = "https://www.pref.nagano.lg.jp/michikanri/infra/doro/joho/hiroba/index.html"
# (key, URL as listed by MLIT, name, operator, prefecture, JMA station code, station name). Position: the JMA
# station of the prefectural capital, or of the issuing office's town when that town has its own station.
PORTALS = [
    ("aomori", "http://www.koutsu-aomori.com/Road/livecamera.html", "青森県みち情報 ライブカメラ", "青森県幹線道路協議会", "青森県", "31312", "青森"),
    ("iwate", "http://www.douro.com/allcamera.shtml", "岩手県道路情報提供サービス ライブカメラ", "岩手県 県土整備部 道路環境課", "岩手県", "33431", "盛岡"),
    ("sendai_city", "http://micos-sa.jwa.or.jp/tohoku/sendaishi_romen/real/index.html", "仙台市 路面状況カメラ", "仙台市", "宮城県", "34392", "仙台"),
    ("akita", "http://road.pref.akita.lg.jp/modules/tinyd2/index.php?id=4", "あきたの道情報 ライブカメラ", "秋田県", "秋田県", "32402", "秋田"),
    ("yamagata_r347", "http://www.pref.yamagata.jp/r347/", "一般国道347号 鍋越峠 道路情報", "山形県", "山形県", "35426", "山形"),
    ("yamagata_r348", "http://www.doro.pref.yamagata.jp/doro/dmain.html", "一般国道348号 道路情報", "山形県", "山形県", "35426", "山形"),
    ("fukushima_r115", "http://fukushima-road.net/kenpoku/r115/", "国道115号（土湯道路）・磐梯吾妻スカイライン ライブカメラ", "福島県", "福島県", "36127", "福島"),
    ("tochigi", "http://www.kendo.pref.tochigi.lg.jp/roadinfo/", "とちぎ道路管理情報", "栃木県", "栃木県", "41277", "宇都宮"),
    ("gunma", "http://www.kendobousai-gunma.jp/photo/", "群馬県 道路ライブカメラ", "群馬県", "群馬県", "42251", "前橋"),
    ("saitama_chichibu", "http://titiburomenkamera.saitama.jp/video-default.php", "秩父県土整備事務所管内 路面カメラ映像", "埼玉県 秩父県土整備事務所", "埼玉県", "43156", "秩父"),
    ("niigata", "http://www.live-cam.pref.niigata.jp/", "にいがたLIVEカメラ", "新潟県IT&ITS推進協議会", "新潟県", "54232", "新潟"),
    ("toyama", "http://www.toyama-douro.toyama.toyama.jp/", "富山県冬期道路情報（冬期間のみ）", "富山県 土木部 道路課", "富山県", "55102", "富山"),
    ("ishikawa", "https://douro.pref.ishikawa.lg.jp/", "石川みち情報ネット", "石川県", "石川県", "56227", "金沢"),
    ("gifu", "https://douro.pref.gifu.lg.jp/", "ぎふライブカメラ", "岐阜県", "岐阜県", "52586", "岐阜"),
    ("shizuoka_numazu", "http://snowlive.pref.shizuoka.jp/", "静岡県沼津土木 雪カメラ", "静岡県 沼津土木事務所", "静岡県", "50331", "静岡"),
    ("shizuoka_atami", "http://izu-e.pref.shizuoka.jp/", "静岡県熱海土木 雪カメラ", "静岡県 熱海土木事務所", "静岡県", "50331", "静岡"),
    ("shizuoka_fuji", "http://fujilive.pref.shizuoka.jp/", "静岡県富士土木 雪カメラ", "静岡県 富士土木事務所", "静岡県", "50196", "富士"),
    ("shizuoka_shimoda", "http://izu-s.pref.shizuoka.jp/", "下田土木 みちなみカメラ", "静岡県 下田土木事務所", "静岡県", "50331", "静岡"),
    ("shizuoka_road_corp", "https://camera.siz-road.or.jp/", "静岡県道路公社 ライブカメラ", "静岡県道路公社", "静岡県", "50331", "静岡"),
    ("nagoya_city", "https://www.rdcamimage.city.nagoya.jp/public_html/all_map.asp", "名古屋市 道路・河川等監視情報システム", "名古屋市", "愛知県", "51106", "名古屋"),
    ("fukui", "https://www.hozen.pref.fukui.lg.jp/hozen/yuki/", "雪みち情報ネットふくい", "福井県 土木部 道路保全課", "福井県", "57066", "福井"),
    ("shiga", "http://www.shiga-douro.jp/", "ロードネット滋賀", "滋賀県", "滋賀県", "60216", "大津"),
    ("kyoto_pref", "https://dobokubousai.pref.kyoto.jp/pc/", "京都府 道路情報管理・提供システム", "京都府", "京都府", "61286", "京都"),
    ("kyoto_road_corp", "http://www.kyo-miti.jp/livecameran/", "京都縦貫自動車道 ライブカメラ", "京都府道路公社", "京都府", "61286", "京都"),
    ("nara", "http://www2.wagamachi-guide.com/naradouro/index.asp?igmt=1&dtp=1", "奈良県 道路規制情報", "奈良県", "奈良県", "64036", "奈良"),
    ("tottori", "http://yukinavi.net/index.html", "とっとり雪みちNavi", "鳥取県 道路企画課", "鳥取県", "69122", "鳥取"),
    ("shimane", "https://www.roadi.pref.shimane.jp/", "島根県 道路カメラ情報", "島根県 土木部 道路維持課", "島根県", "68132", "松江"),
    ("hiroshima", "http://www.roadnavi.pref.hiroshima.lg.jp/", "ひろしま道路Navi", "広島県", "広島県", "67437", "広島"),
    ("yamaguchi", "http://road.pref.yamaguchi.jp/gmap/", "道路見えるナビ", "山口県 道路整備課", "山口県", "81286", "山口"),
    ("ehime", "https://www.pref.ehime.jp/dkanri/imageall.html", "えひめの道 ライブカメラ", "愛媛県", "愛媛県", "73166", "松山"),
    ("kochi", "http://kouhou.bousai.pref.kochi.jp/douro/bousai/bousai_top.html", "高知県 道路カメラ・センサー情報（冬期のみ）", "高知県", "高知県", "74182", "高知"),
    ("nagano", NAGANO_PAGE, "長野県 道路情報広場", "長野県", "長野県", "48156", "長野"),
]
PORTALS_NOT_LISTED_BY_MLIT = {"nagano": NAGANO_PAGE}
PORTALS_LEFT_OUT = {
    "三重県道路規制情報": "Mie: no portal URL in the register or on MLIT's page (only a PDF of camera towns).",
    "道の駅多古 (advan-ad.com)": "private roadside-station camera, not a public road portal",
    "甲府市道路状況 (nns-catv.co.jp)": "private cable-TV company",
    "MLIT offices, NEXCO, JARTIC, road21.jp": "national or expressway operators: other sources (held)",
}


def https_of(url):
    parts = urlsplit(url)
    return url if parts.scheme == "https" else "https" + url[len(parts.scheme):]


def mlit_listed_links(text):
    """{href: link text} of MLIT's live-camera directory page."""
    return {html.unescape(href): re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", label))).strip()
            for href, label in re.findall(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S)}


def parse_amedas(text):
    """{station code: (lat, lng, kanji name)}; the table gives degrees and decimal minutes."""
    out = {}
    for code, row in json.loads(text.lstrip("﻿")).items():
        lat, lon = row.get("lat"), row.get("lon")
        if isinstance(lat, list) and isinstance(lon, list) and len(lat) == 2 and len(lon) == 2:
            out[code] = (lat[0] + lat[1] / 60, lon[0] + lon[1] / 60, row.get("kjName"))
    return out


def portal_items(listed, stations, probes, observed_at):
    items, left_out = [], []
    for key, url, name, operator, prefecture, code, station in PORTALS:
        if key not in PORTALS_NOT_LISTED_BY_MLIT and url not in listed:
            left_out.append({"provider_id": key, "reason": "no longer on MLIT's live-camera page"})
            continue
        probe = probes.get(key) or {}
        if not probe.get("ok"):
            left_out.append({"provider_id": key, "url": https_of(url),
                             "reason": "HTTPS page not verified: " + str(probe.get("reason") or "not checked")})
            continue
        pos = stations.get(code)
        if not pos or pos[2] != station:
            raise ValueError(f"JMA station {code} is not {station}")
        page = probe["final_url"]
        items.append({
            "provider": PORTALS_SOURCE, "provider_id": key, "id": f"{PORTALS_SOURCE}:{key}", "name": name,
            "lat": round(pos[0], 5), "lng": round(pos[1], 5), "country": "JP", "region": prefecture,
            "format": "official_page", "stream_url": None, "snapshot_url": None, "official_page": page,
            "source_page": MLIT_LIVE if key not in PORTALS_NOT_LISTED_BY_MLIT else page,
            "source_catalog": MLIT_LIVE if key not in PORTALS_NOT_LISTED_BY_MLIT else page,
            "rights_status": "official_page_only", "observed_at": probe.get("checked_at") or observed_at,
            "health": {"status": "unverified"}, "provider_in_service": None, "operator": operator,
            "link_scope": "camera_portal", "listed_url": url, "coordinate_role": "approximate",
            "coordinate_reference_system": "EPSG:4326",
            "coordinate_source": f"{AMEDAS} (station {code} {station})",
            "coordinate_note": (f"Approximate: a portal for {prefecture}{'' if operator == prefecture else ' (' + operator + ')'}, "
                                f"placed at JMA observation station {station} ({code}) from JMA's official AMeDAS station "
                                "table (degrees and decimal minutes, about 200 m). It marks the area, not a camera."),
            "location_group_id": f"{PORTALS_SOURCE}:jma-{code}",
            "provider_notice": (f"{operator}のライブカメラ・ポータルへのリンク（位置は{station}付近の目安）。Link to the "
                                f"{prefecture} road-camera portal; the marker shows the area, not a camera.")})
    return items, left_out


# ---------------------------------------------------------------- NEXCO East check (pure)
def parse_driveplaza(text):
    """Camera images of a route page and whether any coordinate appears on it."""
    cams = re.findall(r'<img src="(https://cdn-livecamera-pic\.drivetraffic\.jp/l/([A-Za-z0-9_]+)\.jpg)" alt="([^"]*)"', text)
    coords = re.findall(r"(?i)\b(?:lat|lng|lon|latitude|longitude|ido|keido)\b[\"' :=]+-?\d{1,3}\.\d{3,}", text)
    return {"cameras": len({c[1] for c in cams}), "examples": [c[2] for c in cams[:3]], "coordinates_found": len(coords)}


# ---------------------------------------------------------------- policies
RIVER_CLAUSES = ("「当ホームページで公開している情報（以下「コンテンツ」といいます。）は、どなたでも以下の１）～７）に従って、"
                 "複製、公衆送信、翻訳・変形等の翻案等、自由に利用できます。商用利用も可能です。」「コンテンツの中には、第三者（国以外の者"
                 "をいいます。以下同じ。）が著作権その他の権利を有している場合があります。…当該第三者から利用の許諾を得てください。」"
                 "「ツール等による定期的なデータ収集は…お控えいただきますようお願いいたします。」")


def river_policy(lookup_summary=None):
    """japan_mlit_rivers, started from its entry in scripts/webcam_source_policies.json."""
    return {
        "source": {
            "id": SOURCE,
            "name": "Japan MLIT — river cameras (川の防災情報): State-owned camera stills, other owners' cameras as pages",
            "url": RIVER_TOP, "terms_url": RIVER_TERMS,
            "metadata_license": "Government of Japan Standard Terms of Use 2.0 (政府標準利用規約 第2.0版), CC BY 4.0 "
                                "compatible; attribution and modification notice",
            "license": "川の防災情報 利用ルール (政府標準利用規約 第2.0版), CC BY 4.0 compatible — content of the State only",
            "license_url": RIVER_TERMS,
            "media_rights": ("Stills of State-owned cameras (MLIT river/dam offices, Hokkaido development bureaus): free "
                             "reuse incl. commercial use and public transmission, with source credit and an edit note. "
                             "Cameras of prefectures, municipalities and other bodies are third-party content under the "
                             "terms: links to their official pages only."),
            "rights_note": (RIVER_CLAUSES + " Ownership rule: a camera is the State's when the list's owner code own_cd "
                            "is 20000-29999 (MLIT offices, Hokkaido development bureaus; owner names confirmed from the "
                            "master JSONs), every other code (prefectures and their offices 3/4-digit and 1xxxx, "
                            "including the Water Resources Agency dams 196xx; municipalities 6/7-digit) is a third party. "
                            "Only State cameras that are not paused are snapshots."),
            "attribution": ("出典：国土交通省 川の防災情報ホームページ（https://www.river.go.jp/ ・各カメラのページURL）を加工して作成。"
                            "QGlobeが画像を縮小表示し、名称・位置等のデータを正規化・編集しています（国土交通省が作成したものでは"
                            "ありません）。Source: MLIT River Disaster Prevention Information (川の防災情報); images resized and "
                            "metadata normalized by QGlobe, not an MLIT product."),
            "allowed_hosts": [CAM_HOST, RIVER_HOST], "rights_status": "official_public_feed",
            "minimum_refresh_seconds": 600,
            "image_url_lifecycle": ("Stable latest-still URLs on cam.river.go.jp/cam/now/, replaced in place (a sample "
                                    "was 2 minutes old, Cache-Control max-age about 280 s). Simple cameras: {id}.jpg; "
                                    "CCTV cameras: the name in the camera's master JSON (looked up once, cached)."),
            # The viewer fills {official_page} with each camera's own page (PDL 1.0: source and page URL).
            "record_notice": RECORD_NOTICE,
            "provider_notice": ("QGlobeが画像を縮小表示し、名称・位置等を正規化・編集しています（国土交通省が作成したものでは"
                                "ありません）。国の河川カメラの画像はカードを開いたときだけ読み込み、10分以上の間隔で更新します。都道府県・"
                                "市町村のカメラは公式ページへのリンクのみです。State river-camera images load only while a "
                                "card is open, at most every 10 minutes; prefecture and municipal cameras link to their "
                                "official pages. Do not poll river.go.jp automatically."),
            "collection_policy": ("One bounded collection on 2026-11-14: the 49 area lists and one master JSON per State "
                                  "CCTV camera, sequential, at least 1.2 s apart, cached for offline rebuilds. No scheduled "
                                  "polling of river.go.jp; images are fetched by viewers on tap only, never by the build "
                                  "(one 64 KiB sample check)."),
            "robots_note": ("www.river.go.jp/robots.txt answers the site's HTML shell (200, no rules); "
                            "cam.river.go.jp/robots.txt: see the sample check."),
            "review_status": "reviewed_for_snapshot_and_reference_use", "reviewed_at": REVIEWED_AT,
            "review_note": "Approved scope is limited to the formats and origins in this registry; no upstream liveness claim is accepted.",
            "evidence": [RIVER_TERMS, LIST_URL.format(area="104"), MASTER_URL.format(id="220737001")],
        },
        "media_hosts": [CAM_HOST], "page_hosts": [RIVER_HOST], "formats": ["snapshot", "official_page"],
        "countries": ["JP"], "operator_hints": ["国土交通省", "mlit"], "coordinate_role": "camera_location",
    }


def portal_policy(page_hosts):
    return {
        "source": {
            "id": PORTALS_SOURCE,
            "name": "Japanese prefectural, municipal and road-corporation road camera portals (links from MLIT's "
                    "national live-camera page)",
            "url": MLIT_LIVE, "catalog_url": MLIT_LIVE, "terms_url": MLIT_LIVE,
            "metadata_license": "No reuse licence stated by the portals; factual links from MLIT's official directory only",
            "license": "none stated",
            "media_rights": "Official page links only; no images or streams are shown (no reuse terms found on the portals).",
            "rights_note": ("MLIT's page lists the portals and says 「各映像の視聴等については各管理団体へお問い合わせ下さい」 "
                            "(ask each operator about viewing the images). None of the portals checked by the research "
                            "states a reuse licence, so each portal is one link record without media. Positions are "
                            "approximate: JMA AMeDAS station of the prefectural capital (or of the issuing office's town); "
                            "GSI's prefectural-office table was not readable (TLS renegotiation refused)."),
            "attribution": "各都道府県・市・道路公社のライブカメラ（国土交通省「全国のライブカメラ」掲載リンク）。"
                           "Portals of each prefecture, city or road corporation, as listed by MLIT.",
            "allowed_hosts": [], "rights_status": "official_page_only",
            "provider_notice": "Link to a public road-camera portal; the marker shows the area (approximate), not a camera.",
            "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT,
            "review_note": "Approved scope is limited to the formats and origins in this registry; no upstream liveness claim is accepted.",
            "evidence": [MLIT_LIVE, AMEDAS, NAGANO_PAGE],
        },
        "media_hosts": [], "page_hosts": sorted(page_hosts), "formats": ["official_page"], "countries": ["JP"],
        "operator_hints": [], "coordinate_role": "approximate", "force_coordinate_role": "approximate",
        "official_map_url": MLIT_LIVE,
    }


def held(source_id, name, url, reason, until, evidence):
    return {source_id: {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
                        "source": {"id": source_id, "name": name, "url": url}, "reviewed_at": REVIEWED_AT,
                        "countries": ["JP"]}}


NO_COORDS = ("MLIT road bureaus publish no camera coordinates (as for mlit_kyushu_road_cameras, held in round 1); "
             "mlit_kanto_cctv admits only offices with official coordinates")


def held_policies(nexco_east=None):
    east = nexco_east or {}
    entries = [
        held("nexco_east_driveplaza", "NEXCO East expressway live cameras (ドラぷら)", "https://www.driveplaza.com/traffic/camera/",
             (f"No camera has coordinates: the camera index lists {east.get('route_pages', 'about 38')} route pages and the "
              f"route page read ({east.get('page', 'shinetsu.html')}: {east.get('cameras', 24)} cameras) names cameras by "
              f"interchange section only ('X IC ～ Y IC'), with {east.get('coordinates_found', 0)} coordinates. Terms "
              "(e-nexco.co.jp/site_info): company copyright, no reposting on other sites; linking needs no procedure."),
             "Official camera (or interchange) positions from NEXCO East; then page links only (images may not be reposted).",
             ["https://www.driveplaza.com/traffic/camera/", "https://www.e-nexco.co.jp/site_info/index.html"]),
        held("nexco_central_ihighway", "NEXCO Central expressway live cameras (iHighway 中日本)", "https://www.c-ihighway.jp/",
             "Terms read (c-nexco.co.jp/site_policy): company copyright, no reprinting on other sites, links free in "
             "principle. The camera site c-ihighway.jp answered 403 to scripted clients (not retried): no camera list, "
             "no coordinates.",
             "A camera list with official coordinates reachable without bypassing the block; page links only.",
             ["https://www.c-nexco.co.jp/site_policy/"]),
        held("nexco_west_ihighway", "NEXCO West expressway live cameras (iHighway)", "https://ihighway.jp/",
             "Terms not readable: www.w-nexco.co.jp answers 403 (S3 AccessDenied) to robots.txt and pages; ihighway.jp "
             "is a single-page app shell with no camera list or coordinates.",
             "Terms read and a camera list with official coordinates; page links only expected.",
             ["https://ihighway.jp/robots.txt"]),
        held("jcg_mics_livecamera", "Japan Coast Guard 'Umi no Anzen Joho' lighthouse, radar and port live cameras (HLS)",
             "https://www6.kaiho.mlit.go.jp/livecamera.html",
             "80 live HLS streams (camera.mics.kaiho.mlit.go.jp/realmovie/{station}-live.m3u8) and current thumbnails "
             "exist. JCG's agency site applies PDL1.0, but the MICS camera site has no policy page of its own, so display "
             "of the camera video is unconfirmed; no official station coordinate list (lighthouse tables needed); the "
             "playlists send no CORS header.",
             "JCG confirms that PDL1.0 covers the MICS live cameras (one e-mail), and official station positions.",
             ["https://www.kaiho.mlit.go.jp/questions/post-1.html", "https://www6.kaiho.mlit.go.jp/livecamera.html"]),
        held("niigata_pref_live_cam", "Niigata Prefecture road live cameras (にいがたLIVEカメラ)", "https://www.live-cam.pref.niigata.jp/",
             "Per-camera JPEGs with owner tags, but no terms on the site and no geographic coordinates (pixel positions "
             "on an SVG map). The portal itself is one link record of japan_prefectural_road_camera_portals; its MLIT "
             "cameras belong to mlit_hokuriku_road_cameras (held).",
             "Reuse terms from Niigata Prefecture and official camera coordinates.",
             ["https://www.live-cam.pref.niigata.jp/"]),
        held("mlit_road_info_prvs", "MLIT 道路情報提供システム (nationwide national-road images)",
             "https://www.road-info-prvs.mlit.go.jp/roadinfo/pc/",
             "Disclaimer only (no reuse terms), and the data loads from per-timestamp, randomly named script paths: no "
             "stable camera list or image endpoint and no coordinates.",
             "A stable official camera list with coordinates and terms (or MLIT DPF records, held for a key).",
             ["https://www.road-info-prvs.mlit.go.jp/roadinfo/pc/"]),
        held("mlit_kinki_road_cameras", "MLIT Kinki Regional Development Bureau national-road live cameras",
             "https://www.kkr.mlit.go.jp/road/strategy/camera.html",
             "PDL1.0 verified (kkr.mlit.go.jp/link.html) and stills are fresh HTTPS JPEGs, but none of the 11 office "
             f"pages publishes camera coordinates (Nara: clickable image map); about 300 cameras. {NO_COORDS}.",
             "An office KML/JSON with coordinates, or MLIT DPF records (held for a key).",
             ["https://www.kkr.mlit.go.jp/link.html", "https://www.kkr.mlit.go.jp/road/strategy/camera.html"]),
        held("mlit_hokuriku_road_cameras", "MLIT Hokuriku Regional Development Bureau road cameras",
             "https://www.hrr.mlit.go.jp/kanazawa/douro/michinavi/",
             "PDL1.0 verified (hrr.mlit.go.jp/help.html); stills on www.hrr.mlit.go.jp/bosai/img/; no coordinates "
             f"(Niigata portal SVG pixel positions, Ishikawa image maps); about 200 cameras. {NO_COORDS}.",
             "Official camera coordinates (office KML/JSON) or MLIT DPF records.",
             ["https://www.hrr.mlit.go.jp/help.html"]),
        held("mlit_tohoku_bureau_terms", "MLIT Tohoku Regional Development Bureau road cameras", "https://www.thr.mlit.go.jp/",
             "PDL1.0 verified (thr.mlit.go.jp/policy.pdf), but the road camera pages and image host were not located; no "
             "coordinates; about 200 cameras.",
             "Camera pages with an official list of positions.",
             ["https://www.thr.mlit.go.jp/policy.pdf"]),
        held("mlit_other_bureaus_road_cameras", "MLIT Chubu, Chugoku and Shikoku bureau road cameras",
             "https://www.mlit.go.jp/road/bosai/LIVEcamera.html",
             "Shikoku PDL1.0 verified; Chubu and Chugoku terms not read; office pages give no coordinates and the "
             "Chugoku/Shikoku lists sit on road-info-prvs (no stable endpoint); about 400 cameras.",
             "Per bureau: terms read, one image check, official camera coordinates.",
             ["https://www.skr.mlit.go.jp/manual.html", "https://www.cbr.mlit.go.jp/livecamera.htm"]),
        held("mlit_hokkaido_road_info", "MLIT Hokkaido Regional Development Bureau road information cameras",
             "https://info-road.hdb.hkd.mlit.go.jp/",
             "The site rejects scripted clients (F5 'Request Rejected' page, also for robots.txt); terms not read; no "
             "bypass attempted.",
             "A human reads the terms and finds an official camera list with coordinates.",
             []),
        held("mlit_regional_bureaus_other", "MLIT other regional bureaus' live cameras", "https://www.mlit.go.jp/road/bosai/LIVEcamera.html",
             "Split in round 2 into per-bureau holds: mlit_kinki_road_cameras, mlit_hokuriku_road_cameras, "
             "mlit_tohoku_bureau_terms, mlit_other_bureaus_road_cameras, mlit_hokkaido_road_info (Kyushu: "
             "mlit_kyushu_road_cameras). PDL1.0 is verified for Kinki, Hokuriku, Tohoku and Shikoku; none publishes "
             "camera coordinates.",
             "See the per-bureau ids; this id carries no records.",
             [MLIT_LIVE]),
    ]
    out = {}
    for entry in entries:
        out.update(entry)
    return out


# ---------------------------------------------------------------- pages and check (network, short)
def probe_page(client, url):
    """One GET of a portal page over HTTPS (robots honoured): reachability only, the body is not kept."""
    event = {"url": url, "checked_at": F.now()}
    try:
        r = client.get(url, max_bytes=8 * 1024 * 1024)
    except F.Refused as e:
        return {**event, "ok": False, "reason": str(e)[:200]}
    except OSError as e:
        return {**event, "ok": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}
    ctype = r["headers"].get("Content-Type") or ""
    ok = r["status"] == 200 and r["final_url"].startswith("https://") and "html" in ctype.lower()
    return {**event, "ok": ok, "http_status": r["status"], "final_url": r["final_url"], "content_type": ctype,
            "bytes": len(r["body"]), "sha256": hashlib.sha256(r["body"]).hexdigest(), "redirects": r["redirects"],
            "reason": None if ok else f"HTTP {r['status']} {ctype}"}


UNREACHABLE_ROBOTS = ("robots.txt unreachable over HTTPS (connection/TLS error, timeout, 5xx or a redirect to http): "
                      "treated as a disallow, page not verified")


def explain_probes(probes, requests):
    """Reword 'robots.txt disallows' when no robots.txt answer was logged for the host: the file was unreachable
    (webcam_fetch then denies crawling, RFC 9309), which is not a Disallow rule of the site."""
    answered = {urlsplit(r["url"]).hostname for r in requests if r["url"].endswith("/robots.txt")}
    out = {}
    for key, probe in probes.items():
        probe = dict(probe)
        if not probe.get("ok") and str(probe.get("reason", "")).startswith("robots.txt disallows")                 and urlsplit(probe["url"]).hostname not in answered:
            probe["reason"] = UNREACHABLE_ROBOTS
        out[key] = probe
    return out


def run_pages(out):
    out, client, refused = Path(out), F.PoliteClient(delay=1.2), []

    def save(source, name, url):
        try:
            r = client.get(url, max_bytes=8 * 1024 * 1024)
        except (F.Refused, OSError) as e:
            refused.append({"source": source, "url": url, "host": urlsplit(url).hostname, "reason": str(e)[:200]})
            return None
        if r["status"] != 200:
            refused.append({"source": source, "url": url, "host": urlsplit(url).hostname, "reason": f"HTTP {r['status']}"})
            return None
        F.save_raw(out / "raw" / source, name, r)
        return r

    save(PORTALS_SOURCE, "LIVEcamera.html", MLIT_LIVE)
    save(PORTALS_SOURCE, "amedastable.json", AMEDAS)
    probes = {}
    for key, url, *_ in PORTALS:
        probes[key] = probe_page(client, https_of(url))
        if not probes[key]["ok"]:
            refused.append({"source": PORTALS_SOURCE, "url": https_of(url), "host": urlsplit(url).hostname,
                            "reason": probes[key]["reason"]})
    (out / "raw" / PORTALS_SOURCE / "portal_checks.json").write_text(json.dumps(probes, ensure_ascii=False, indent=1),
                                                                     encoding="utf-8")
    save("nexco_east_driveplaza", "camera_index.html", "https://www.driveplaza.com/traffic/camera/")
    save("nexco_east_driveplaza", "shinetsu.html", "https://www.driveplaza.com/traffic/camera/shinetsu.html")
    (out / "raw" / PORTALS_SOURCE / "pages_run.json").write_text(json.dumps(
        {"finished_at": F.now(), "refused": refused, "requests": client.log}, ensure_ascii=False, indent=1), encoding="utf-8")
    return refused


def run_check(out):
    """One 64 KiB check of one State camera still (the first simple camera in service, by id)."""
    out = Path(out)
    cams, _ = read_lists(out)
    first = min((c for c in cams if is_national(c["own_cd"]) and c["sys_id"] == 1 and c["pause"] == 0),
                key=lambda c: c["id"])
    client = F.PoliteClient(delay=1.2)
    event = client.check_image(SIMPLE_IMAGE.format(id=first["id"]), SOURCE, f"{SOURCE}:{first['id']}", [CAM_HOST])
    (out / "checks").mkdir(parents=True, exist_ok=True)
    (out / "checks" / f"{SOURCE}.snapshot.json").write_text(json.dumps([event], ensure_ascii=False, indent=1), encoding="utf-8")
    robots = next((r for r in client.log if r["url"].endswith("/robots.txt")), None)
    receipt = {"event": event, "robots": robots, "requests": client.log}
    (out / "raw" / SOURCE / "image_check_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=1),
                                                                   encoding="utf-8")
    return event


# ---------------------------------------------------------------- build (offline)
PACKAGE_INPUT = Path(r"C:\Users\zonke\Desktop\QPING\QGlobe_webcam_mondiali_2026-11-14\inputs\round4\apac_global.json")


ETIQUETTE = {
    "exploration": ("Before the collector: 14 sequential GETs through PoliteClient (www.river.go.jp robots.txt x2, "
                    "list 104, one master JSON; www.mlit.go.jp LIVEcamera.html; www.jma.go.jp amedastable.json; "
                    "www.driveplaza.com camera index and shinetsu.html; robots.txt of each host). www.gsi.go.jp "
                    "refused the TLS handshake (UNSAFE_LEGACY_RENEGOTIATION_DISABLED) twice: not worked around."),
    "lookups": ("One background run, 2026-11-14 14:11-15:47Z (96 min): 52 area lists (3 probes 404) and 4,612 master "
                "JSONs (about 1.2-1.4 KB each), sequential, >= 1.2 s apart, 0 errors; cached, never repeated."),
    "image_checks": "One 64 KiB check on cam.river.go.jp (robots.txt 404); none for page-only or held sources.",
    "portal_pages": ("One HTTPS GET per portal page (bodies not kept) after its robots.txt; unreachable robots.txt "
                     "counts as a disallow (RFC 9309), so those portals were left out, not retried over http."),
}


def write_policy(out, pid, entry):
    folder = Path(out) / "policies"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pid}.json").write_text(json.dumps({pid: entry}, ensure_ascii=False, indent=1), encoding="utf-8")


def build(out, package=PACKAGE_INPUT):
    out = Path(out)
    report = {"family": FAMILY, "generated_at": F.now(), "sources": [], "held": [], "hosts_refused": [
        {"source": PORTALS_SOURCE, "host": "www.gsi.go.jp", "reason": "TLS handshake refused (legacy renegotiation); "
         "the GSI prefectural-office table could not be read, JMA station positions used instead"}],
        "etiquette": ETIQUETTE}
    # ---- rivers
    cams, receipts = read_lists(out)
    cache = load_cache(cache_path(out))
    items, reasons, names = river_items(cams, receipts, cache)
    F.write_catalog(out / f"{SOURCE}.json", [SOURCE], items, supersedes=[SOURCE])
    policy = river_policy()
    check_file = out / "checks" / f"{SOURCE}.snapshot.json"
    check = json.loads(check_file.read_text(encoding="utf-8"))[0] if check_file.exists() else None
    receipt_file = out / "raw" / SOURCE / "image_check_receipt.json"
    robots = json.loads(receipt_file.read_text(encoding="utf-8")).get("robots") if receipt_file.exists() else None
    if robots:
        policy["source"]["robots_note"] = (
            "www.river.go.jp/robots.txt answers the site's HTML shell (200, no rules); cam.river.go.jp/robots.txt: "
            f"HTTP {robots['status']} ({'no rules' if robots['status'] >= 400 else 'rules honoured'}).")
    write_policy(out, SOURCE, policy)
    viewable = [x for x in items if x["format"] == "snapshot"]
    lists_status = json.loads((out / "raw" / SOURCE / "lists_status.json").read_text(encoding="utf-8")) \
        if (out / "raw" / SOURCE / "lists_status.json").exists() else {}
    done_file = out / "progress" / "japan_rivers_lookup.done"
    lookup = json.loads(done_file.read_text(encoding="utf-8")) if done_file.exists() else None
    master_codes = collections.Counter()
    for cam in cams:
        m = master_fields(cache.get(cam["id"]))
        if m and m.get("ownCd") is not None and m["ownCd"] != cam["own_cd"]:
            master_codes["differs_from_list" if is_national(m["ownCd"]) == is_national(cam["own_cd"]) else "class_differs"] += 1
    package_items = json.loads(Path(package).read_text(encoding="utf-8"))["items"] if package and Path(package).exists() else []
    report["sources"].append({
        "id": SOURCE, "country": "JP", "input_file": f"{SOURCE}.json", "supersedes": [SOURCE],
        "records": {"viewable": len(viewable), "page_only": len(items) - len(viewable)},
        "viewable_by_system": dict(collections.Counter(f"sys_id {x['published_system_id']}" for x in viewable)),
        "outcome_counts": dict(sorted(reasons.items())),
        "owner_rule": "own_cd 20000-29999 = State (MLIT offices, Hokkaido development bureaus); others third party",
        "owners": {"state_codes": len([k for k in names if is_national(k)]),
                   "state_names_sample": sorted({v for k, v in names.items() if is_national(k)})[:12],
                   "state_codes_with_local_looking_name": sorted(k for k, v in names.items() if is_national(k) and owner_conflict(v)),
                   "third_party_dam_and_office_owners": {
                       str(k): v for k, v in sorted(names.items(), key=lambda kv: str(kv[0]))
                       if not is_national(k) and re.search(r"ダム|管理所|管理事務所", v or "")},
                   "third_party_names_sample": sorted({v for k, v in names.items() if not is_national(k)})[:12],
                   "master_owner_code_vs_list": dict(master_codes)},
        "lists": {"areas_saved": len(receipts), "status": {k: v.get("status", v.get("error") or v.get("refused"))
                                                           for k, v in lists_status.items()}},
        "lookups": {"cached": len(cache), "cache_file": "raw/japan_mlit_rivers/master_cache.jsonl",
                    "run": {k: lookup.get(k) for k in ("status", "reason", "started_at", "finished_at", "run_seconds",
                                                       "requests", "error_count", "planned")} if lookup else None},
        "continuity": compare_with_package(items, package_items),
        "sample_check": {k: (check or {}).get(k) for k in ("record_id", "url", "status", "http_status", "signature",
                                                           "content_type", "bytes_read", "cors", "inconclusive_reason")},
        "robots": policy["source"]["robots_note"],
        "changes_from_register": [
            "All 6,293 State cameras in service counted from the pause flag (the register estimated 5,700 with a 90% "
            "ratio); the per-camera lookups were made once in the collector and cached (the register left that to "
            "the user: the brief chose the one-off lookup).",
            "3-digit owner codes (257 北海道, 513 青森県, 769 岩手県) are prefectures, confirmed by owner names.",
            "Water Resources Agency dams (水資源機構, codes 196xx) and prefectural dam offices are not the State: "
            "page links, like the prefectures' and municipalities' cameras."],
    })
    # ---- Kanto Tone upstream note (superseding input; ids unchanged)
    kanto_file = out / "mlit_kanto_cctv.json"
    if kanto_file.exists():
        kanto_doc = json.loads(kanto_file.read_text(encoding="utf-8"))
        kanto, noted = kanto_with_tonejo_note(kanto_doc)
        F.write_catalog(out / "mlit_kanto_cctv_tonejo_note.json", ["mlit_kanto_cctv"], kanto, supersedes=["mlit_kanto_cctv"])
        report["sources"].append({
            "id": "mlit_kanto_cctv", "country": "JP", "input_file": "mlit_kanto_cctv_tonejo_note.json",
            "supersedes": ["mlit_kanto_cctv"], "based_on": "mlit_kanto_cctv.json (round 1), ids unchanged",
            "records": {"viewable": sum(x["format"] == "snapshot" for x in kanto), "page_only": 0},
            "tone_upstream_records_with_note": noted, "note": TONEJO_NOTE, "guideline": TONEJO_GUIDELINE,
            "change": "per-record provider_notice on the Tone upstream office's records (tonejo-*); the policy is unchanged"})
    # ---- portals
    live_text, live_receipt = read_raw_text(out, PORTALS_SOURCE, "LIVEcamera.html")
    amedas_text, _ = read_raw_text(out, PORTALS_SOURCE, "amedastable.json")
    probes_file = out / "raw" / PORTALS_SOURCE / "portal_checks.json"
    probes = json.loads(probes_file.read_text(encoding="utf-8")) if probes_file.exists() else {}
    pages_run = out / "raw" / PORTALS_SOURCE / "pages_run.json"
    requests = json.loads(pages_run.read_text(encoding="utf-8"))["requests"] if pages_run.exists() else []
    probes = explain_probes(probes, requests)
    if live_text and amedas_text:
        portals, portals_out = portal_items(mlit_listed_links(live_text), parse_amedas(amedas_text), probes,
                                            live_receipt["observed_at"])
        hosts = {urlsplit(x["official_page"]).hostname for x in portals}
        F.write_catalog(out / f"{PORTALS_SOURCE}.json", [PORTALS_SOURCE], portals)
        write_policy(out, PORTALS_SOURCE, portal_policy(hosts))
        report["sources"].append({
            "id": PORTALS_SOURCE, "country": "JP", "input_file": f"{PORTALS_SOURCE}.json",
            "records": {"viewable": 0, "page_only": len(portals)}, "left_out": portals_out,
            "not_included": PORTALS_LEFT_OUT,
            "coordinates": "approximate: JMA AMeDAS station of the prefectural capital or the issuing office's town "
                           f"({AMEDAS}); GSI's prefectural-office table refused our TLS client (legacy renegotiation)",
            "robots": "each portal host's robots.txt read before its page (webcam_fetch)",
            "changes_from_register": ["Placed at JMA stations instead of prefectural road offices (no official office "
                                      "coordinates were readable); only portals whose HTTPS page answered 200 are kept."]})
        report["hosts_refused"] += [{"source": PORTALS_SOURCE, "host": urlsplit(p["url"]).hostname, "url": p["url"],
                                    "reason": p.get("reason")} for p in probes.values() if not p.get("ok")]
    # ---- NEXCO East (held: coordinates check)
    east = {}
    index_text, _ = read_raw_text(out, "nexco_east_driveplaza", "camera_index.html")
    route_text, _ = read_raw_text(out, "nexco_east_driveplaza", "shinetsu.html")
    if index_text and route_text:
        east = parse_driveplaza(route_text)
        east.update(page="shinetsu.html", route_pages=len(set(re.findall(r'href="/traffic/camera/[a-z_]+\.html"', index_text))))
    for pid, entry in held_policies(east).items():
        write_policy(out, pid, entry)
        report["held"].append({"id": pid, "reason": entry["held_reason"]})
    if lookup and lookup.get("status") not in ("complete",):
        report["hosts_refused"].append({"source": SOURCE, "host": RIVER_HOST, "reason": lookup.get("reason") or lookup["status"]})
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def read_raw_text(out, source, name):
    path = Path(out) / "raw" / source / name
    if not path.exists():
        return None, None
    receipt = json.loads((path.parent / (path.name + ".receipt.json")).read_text(encoding="utf-8"))
    body = path.read_bytes()
    return body.decode("utf-8-sig", "replace"), receipt


# ---------------------------------------------------------------- CLI
RECORD_NOTICE = "出典：国土交通省 川の防災情報ホームページ（{official_page}）を加工して作成"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keep-lists", action="store_true", help="lookup: reuse the saved area lists")
    ap.add_argument("--package", type=Path, default=PACKAGE_INPUT, help="build: package input, for the id continuity check")
    ap.add_argument("step", choices=["lookup", "pages", "check", "build"])
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.step == "lookup":
        print(json.dumps(run_lookup(args.out, refetch_lists=not args.keep_lists), ensure_ascii=False)[:2000])
    elif args.step == "pages":
        print(json.dumps(run_pages(args.out), ensure_ascii=False, indent=1))
    elif args.step == "check":
        print(json.dumps(run_check(args.out), ensure_ascii=False, indent=1))
    else:
        report = build(args.out, args.package)
        print(json.dumps({s["id"]: s["records"] for s in report["sources"]}, ensure_ascii=False))
        print("held:", [h["id"] for h in report["held"]])


if __name__ == "__main__":
    main()
