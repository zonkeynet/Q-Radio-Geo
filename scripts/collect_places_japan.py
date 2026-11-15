#!/usr/bin/env python3
"""Place the Japanese road cameras held only for missing coordinates (placement round, 2026-11-14).

Sources (each was held because the operator publishes no camera position):
  mlit_kinki_road_cameras, mlit_hokuriku_road_cameras, mlit_kyushu_road_cameras, mlit_tohoku_bureau_terms
                  MLIT regional bureau national-road cameras (PDL 1.0 stills on the bureau's own host)
  mlit_kanto_cctv  the Kanto offices left out in round 1 (route/place labels only), added to the round-1
                  records (ids unchanged) in a superseding input
  nexco_east_driveplaza  NEXCO East expressway cameras, official page links only (images may not be reposted)
  mlit_hokkaido_road_info, mlit_other_bureaus_road_cameras (Shikoku part): re-checked, stay held.

Placement hierarchy (scripts/webcam_places.py, CONTRACT-PLACES.md):
  1. an interchange / junction / smart IC / SA-PA named by the camera label: 国土数値情報 高速道路時系列
     (N06, MLIT, current-year data = CC BY 4.0) joint points, role named_feature;
  2. a named bridge, tunnel, pass, rest area, roadside station or signalised junction: OpenStreetMap
     (ODbL, one Overpass query per prefecture, matched locally; the feature must be on or next to the
     camera's route), role named_feature;
  3. a place named by the label (大字 / 町丁目, with its municipality when the label gives one):
     位置参照情報 大字・町丁目レベル (MLIT, PDL 1.0 site terms + 位置参照情報利用約款), role place_centre;
  otherwise held. Sections "X IC ～ Y IC" are never placed by a midpoint: only the named camera feature is.
Every placement passes webcam_places.check (Natural Earth country JP, not at sea, near the office's area)
and a neighbour check (the office lists cameras in route order).

Steps (network only through webcam_fetch.PoliteClient, sequential, cached):
  acquire  camera list pages (+ per-camera sub-pages where the list has no image), gazetteers
  check    one 64 KiB image check per new viewable provider
  build    offline: normalized inputs, policy fragments, report

  python scripts/collect_places_japan.py --out <SCRATCH>/webcam-inputs-2026-11 acquire|check|build
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urljoin, urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webcam_fetch as F  # noqa: E402

FAMILY = "places_japan"
REVIEWED_AT = "2026-11-14"
PDL_URL = "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0"
PDL_NAME = "Public Data License 1.0 (PDL1.0), CC BY 4.0 compatible"

# ---------------------------------------------------------------- gazetteers (open official data + OSM)
ISJ_VERSION = "19.0b"   # 位置参照情報 大字・町丁目レベル, 2025 (令和7年) data
ISJ_URL = "https://nlftp.mlit.go.jp/isj/dls/data/{v}/{pref}000-{v}.zip"
ISJ_PAGE = "https://nlftp.mlit.go.jp/isj/"
ISJ_TERMS = "https://nlftp.mlit.go.jp/isj/agreement.html"
ISJ_LICENCE = "PDL1.0 / 位置参照情報利用約款 (大字・町丁目位置参照情報 国土交通省)"
N06_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N06/N06-25/N06-25_GML.zip"
N06_PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N06-2025.html"
N06_LICENCE = "CC BY 4.0 (国土数値情報 高速道路時系列 N06-25, 国土交通省; current-year data)"
KSJ_TERMS = "https://nlftp.mlit.go.jp/ksj/other/agreement.html"
GAZETTEER_NOTICE = ("位置はQGlobeの推定（カメラの正確な位置ではありません）：「国土数値情報（高速道路時系列データ）」（国土交通省）"
                    "（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N06-2025.html）、「大字・町丁目位置参照情報」"
                    "（国土交通省、令和7年 19.0b）（https://nlftp.mlit.go.jp/isj/）、OpenStreetMap（© OpenStreetMap "
                    "contributors, ODbL）をもとにQGlobe作成。")
PREFECTURES = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県", "埼玉県",
               "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県",
               "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県",
               "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県",
               "宮崎県", "鹿児島県", "沖縄県"]
KANJI_DIGITS = "〇一二三四五六七八九十"


def nfkc(value):
    return unicodedata.normalize("NFKC", value or "").replace("　", " ").strip()


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def round_up(value, step=100):
    return int(math.ceil(value / step) * step)


class Isj:
    """位置参照情報 大字・町丁目レベル: representative points of every 大字 / 町丁目, per prefecture.

    A place is a 大字 or a 町 with its 丁目 grouped (逢坂一丁目 + 逢坂二丁目 = 逢坂): its centre is the mean of
    the representative points, its extent the farthest point plus a margin, or for a single point the distance
    to the nearest other place of the same municipality (the place's own size is not published)."""

    CHOME = re.compile(r"([" + KANJI_DIGITS + r"]+丁目|\d+丁目)$")

    def __init__(self, rows):
        self.rows = rows    # (pref_code, muni_code, muni_name, code, name, lat, lng)
        groups = collections.defaultdict(list)
        for row in rows:
            groups[(row[1], self.base(row[4]))].append(row)
        self.places = {}
        by_muni = collections.defaultdict(list)
        for (muni, base), members in groups.items():
            lat = sum(r[5] for r in members) / len(members)
            lng = sum(r[6] for r in members) / len(members)
            spread = max(distance_m(lat, lng, r[5], r[6]) for r in members)
            place = {"muni_code": muni, "muni": members[0][2], "pref": members[0][0], "name": base, "lat": lat,
                     "lng": lng, "codes": sorted(r[3] for r in members), "spread_m": spread, "points": len(members)}
            self.places[(muni, base)] = place
            by_muni[muni].append(place)
        for muni, places in by_muni.items():
            for place in places:
                if place["points"] > 1:
                    radius = place["spread_m"] + 400
                else:
                    near = [distance_m(place["lat"], place["lng"], p["lat"], p["lng"]) for p in places if p is not place]
                    radius = min(near) if near else 3000
                place["uncertainty_m"] = min(5000, max(500, round_up(radius)))
        self.by_name = collections.defaultdict(list)
        for place in self.places.values():
            for key in self.keys(place["name"], index=True):
                self.by_name[key].append(place)
        self.munis = {}
        for row in rows:
            name = row[2]
            self.munis.setdefault(name, (row[0], row[1]))
            if "郡" in name:
                self.munis.setdefault(name.split("郡", 1)[1], (row[0], row[1]))
        self.pref_bbox = {}
        for row in rows:
            box = self.pref_bbox.setdefault(row[0], [90, 180, -90, -180])
            box[0], box[1] = min(box[0], row[5]), min(box[1], row[6])
            box[2], box[3] = max(box[2], row[5]), max(box[3], row[6])

    @classmethod
    def base(cls, name):
        return cls.CHOME.sub("", name)

    @staticmethod
    def keys(name, index=False):
        """Lookup keys of a place name: itself, without a leading 大字/字, without a trailing 町/村, without ヶ/ケ;
        when indexing, also the part after a former town's name ('木之本町木之本' -> '木之本')."""
        out = {name}
        for prefix in ("大字", "字"):
            if name.startswith(prefix) and len(name) > len(prefix) + 1:
                out.add(name[len(prefix):])
        if index:
            m = re.match(r"^(.{2,5}?[町村])(?:大字|字)?(.{2,})$", name)
            if m:
                out.add(m.group(2))
        for value in list(out):
            if len(value) > 2 and value[-1] in "町村":
                out.add(value[:-1])
        for value in list(out):
            plain = re.sub(r"[ヶケヵが]", "", value)
            if plain != value and len(plain) >= 2:
                out.add(plain)
        return out

    @classmethod
    def from_zip_bytes(cls, blobs):
        rows = []
        for blob in blobs:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for name in z.namelist():
                    if name.endswith(".csv"):
                        text = z.read(name).decode("cp932")
                        reader = csv.reader(io.StringIO(text))
                        next(reader, None)
                        for r in reader:
                            if len(r) >= 8 and r[6] and r[7]:
                                rows.append((r[0], r[2], r[3], r[4], r[5], float(r[6]), float(r[7])))
        return cls(rows)

    def find(self, name, prefs=None, muni=None):
        """Places named `name` (exact, with the 大字/町 variants), optionally inside prefectures / a municipality."""
        found = []
        seen = set()
        for key in self.keys(name):
            for place in self.by_name.get(key, ()):
                if id(place) in seen:
                    continue
                if prefs and place["pref"] not in prefs:
                    continue
                if muni and not (place["muni"] == muni or place["muni"].endswith(muni)):
                    continue
                seen.add(id(place))
                found.append(place)
        return found

    def municipality_in(self, label, prefs=None):
        """The longest municipality name the label starts with or contains (市区町村名), else None."""
        best = None
        for name, (pref, _) in self.munis.items():
            if prefs and pref not in prefs:
                continue
            if len(name) >= 2 and name in label and (best is None or len(name) > len(best)):
                best = name
        return best

    def pref_at(self, lat, lng):
        """Prefecture name of the nearest representative point (grid search)."""
        if not hasattr(self, "_grid"):
            self._grid = collections.defaultdict(list)
            for p in self.places.values():
                self._grid[(int(p["lat"] * 10), int(p["lng"] * 10))].append(p)
        best = None
        gy, gx = int(lat * 10), int(lng * 10)
        for ring in range(0, 6):
            for dy in range(-ring, ring + 1):
                for dx in range(-ring, ring + 1):
                    for p in self._grid.get((gy + dy, gx + dx), ()):
                        d = distance_m(lat, lng, p["lat"], p["lng"])
                        if best is None or d < best[0]:
                            best = (d, p["pref"])
            if best:
                break
        return PREFECTURES[int(best[1]) - 1] if best else ""

    def municipality_stem(self, word, prefs=None):
        """(municipality, rest) when the word starts with a municipality's name without 市/町/村 ('大鰐唐牛')."""
        best = None
        for name, (pref, _) in self.munis.items():
            if prefs and pref not in prefs:
                continue
            short = name.split("郡")[-1]
            stem = short[:-1] if short[-1:] in "市町村区" else short
            if len(stem) >= 2 and word.startswith(stem) and len(word) - len(stem) >= 2:
                if best is None or len(stem) > len(best[2]):
                    best = (name, word[len(stem):], stem)
        return (best[0], best[1]) if best else None

    def in_prefs(self, lat, lng, prefs, margin=0.15):
        for pref in prefs:
            box = self.pref_bbox.get(pref)
            if box and box[0] - margin <= lat <= box[2] + margin and box[1] - margin <= lng <= box[3] + margin:
                return True
        return False


class Joints:
    """国土数値情報 N06 (高速道路時系列) interchange / junction points in service (N06_014 = 9999)."""
    KINDS = {"1": "IC", "2": "SIC", "3": "JCT", "4": "SA/PA/接続部"}

    def __init__(self, features):
        self.by_name = collections.defaultdict(list)
        for f in features:
            p = f.get("properties") or {}
            if str(p.get("N06_014")) != "9999" or (f.get("geometry") or {}).get("type") != "Point":
                continue
            lng, lat = f["geometry"]["coordinates"][:2]
            name = nfkc(p.get("N06_018"))
            kind = str(p.get("N06_019"))
            joint = {"name": name, "kind": self.KINDS.get(kind, kind), "lat": lat, "lng": lng, "id": p.get("N06_015")}
            for key in self.keys(name, kind):
                self.by_name[key].append(joint)

    @staticmethod
    def keys(name, kind):
        out = {name}
        m = re.match(r"^(.+?)(JCT|IC|SIC)/(JCT|IC|SIC)$", name)
        if m:
            out |= {m.group(1) + m.group(2), m.group(1) + m.group(3)}
        if kind == "1" and not re.search(r"(IC|JCT|SIC)$", name):
            out.add(name + "IC")
        if name.endswith("SIC"):
            out.add(name[:-3] + "スマートIC")
        return out

    @classmethod
    def from_zip_bytes(cls, blob):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next(n for n in z.namelist() if n.endswith("UTF-8/N06-25_Joint.geojson"))
            return cls(json.loads(z.read(name).decode("utf-8"))["features"])

    def find(self, name):
        return list(self.by_name.get(name, ()))


# ---------------------------------------------------------------- OSM (Overpass, one query per prefecture)
OSM_TAGS = {
    "bridge": ("bridge:name", "name"),
    "tunnel": ("tunnel:name", "name"),
}


def overpass_query(box):
    """Named road features of one prefecture's bounding box (from 位置参照情報 points): bridges and tunnels of
    motorways and national routes (trunk/primary with a ref), and named junctions, passes, rest areas and roadside
    stations next to them. The query does not depend on the camera lists, so its cached answer stays valid."""
    s, w, n, e = (round(v, 3) for v in (box[0] - 0.05, box[1] - 0.05, box[2] + 0.05, box[3] + 0.05))
    return ("[out:json][timeout:300];\n"
            f'way[highway~"^(motorway|trunk|primary)$"][ref]({s},{w},{n},{e})->.r;\n'
            "(\n"
            " way.r[bridge][~\"^(name|bridge:name)$\"~\".\"];\n"
            " way.r[tunnel][~\"^(name|tunnel:name)$\"~\".\"];\n"
            " node(around.r:250)[name][highway~\"^(traffic_signals|motorway_junction)$\"];\n"
            " node(around.r:800)[name][mountain_pass];\n"
            " nwr(around.r:600)[name][highway~\"^(services|rest_area)$\"];\n"
            " nwr(around.r:600)[name~\"道の駅\"];\n"
            " way(around.r:120)[name][man_made=bridge];\n"
            ");\n"
            "out tags center bb;\n")


def element_extent_m(el):
    """Half the diagonal of a way's bounding box (its extent), 0 for nodes."""
    b = el.get("bounds")
    if not b:
        return 0
    return distance_m(b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]) / 2


class Osm:
    def __init__(self, elements_by_pref):
        self.by_name = collections.defaultdict(list)
        self.available = set(elements_by_pref)
        for pref, elements in elements_by_pref.items():
            for el in elements:
                tags = el.get("tags") or {}
                b = el.get("bounds") or {}   # 'out center bb' returns the bounds only: use their middle
                point = (el["lat"], el["lon"]) if el.get("type") == "node" else \
                    (el["center"]["lat"], el["center"]["lon"]) if el.get("center") else \
                    ((b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2) if b else (None, None)
                if point[0] is None:
                    continue
                kind = ("tunnel" if tags.get("tunnel") else "bridge" if tags.get("bridge") or tags.get("man_made") == "bridge"
                        else "pass" if tags.get("mountain_pass") else "services" if tags.get("highway") in ("services", "rest_area")
                        else "michinoeki" if "道の駅" in tags.get("name", "") else "junction")
                names = {tags.get(k) for k in ("name", "bridge:name", "tunnel:name", "name:ja", "official_name") if tags.get(k)}
                entry = {"pref": pref, "type": el["type"], "id": el["id"], "kind": kind, "lat": point[0], "lng": point[1],
                         "extent_m": element_extent_m(el), "ref": tags.get("ref", ""),
                         "name": (tags.get("bridge:name") if kind == "bridge" else tags.get("tunnel:name") if kind == "tunnel"
                                  else None) or tags.get("name") or tags.get("bridge:name") or tags.get("tunnel:name"),
                         "highway": tags.get("highway")}
                for name in names:
                    for key in feature_keys(name):
                        self.by_name[key].append(entry)

    def find(self, key, prefs):
        out, seen = [], set()
        for entry in self.by_name.get(key, ()):
            if entry["pref"] in prefs and (entry["type"], entry["id"]) not in seen:
                seen.add((entry["type"], entry["id"]))
                out.append(entry)
        return out


def feature_keys(name):
    """Normalized lookup keys of a feature name (OSM or camera label)."""
    n = nfkc(name).replace(" ", "")
    out = {n}
    swaps = [("トンネル", "TN"), ("パーキングエリア", "PA"), ("サービスエリア", "SA"), ("インターチェンジ", "IC"),
             ("ジャンクション", "JCT"), ("スマートIC", "SIC"), ("交差点", ""), ("道の駅", "")]
    for long, short in swaps:
        for value in list(out):
            if long in value:
                out.add(value.replace(long, short))
    return {v for v in out if v}


# ---------------------------------------------------------------- camera labels
DIRECTION = re.compile(r"[\(（]?(上り|下り|上|下|上り線|下り線|[東西南北]行き?)[\)）]?$")
QUALIFIERS = re.compile(r"(本線|付近|周辺|地先|地区|方向|側|坑口|\【[^】]*\】|【[^】]*】|\[[^\]]*\]|[\(（][^\)）]*[\)）])$")
FEATURE = re.compile(r"^(?P<name>.+?)(?P<kind>JCT|SIC|スマートIC|IC|PA|SA|TN|トンネル|大橋|高架橋|跨線橋|陸橋|橋梁|高架|橋|峠|交差点|料金所|バスストップ|BS)$")
ROUTE = re.compile(r"(?:国道|R|一般国道)\s*(\d{1,3})\s*号?")


def label_core(label):
    """Strip numbering, direction, kp and qualifiers from a camera label; keep the named thing."""
    s = nfkc(label)
    s = re.sub(r"^[\(（]?\d+[\)）.．]?\s*", "", s)
    s = re.sub(r"^(BP|ＢＰ)", "", s)
    s = re.sub(r"[❶-❿⓫-⓴①-⑳]", "", s)
    s = re.sub(r"\d+(?:\.\d+)?\s*(?:k\s*p|kp|KP|km|k)\s*\d*", " ", s)
    s = re.sub(r"\d+k\d+", " ", s)
    s = re.sub(r"(?:国道|一般国道|R)\s*\d{1,3}\s*号?(?:線|BP|バイパス)?", " ", s)
    s = re.sub(r"[（(]標高[^）)]*[）)]", " ", s)
    s = re.sub(r"[（(]\s*[）)]", " ", s)
    s = re.sub(r"[（(]\s*[）)]", " ", s)
    s = re.sub(r"(^|\s)(上|下|上り|下り|上り線|下り線|[東西南北]側)(?=\s|$)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ・-－:：")
    return s


def strip_tail(word):
    """Remove direction / side / number / qualifier suffixes repeatedly ('千原1' -> '千原', '春来トンネル鳥取側' -> '春来トンネル')."""
    prev = None
    w = word
    while prev != w:
        prev = w
        w = re.sub(r"[\(（](上り|下り|上|下|上り線|下り線)[\)）]$", "", w)
        w = re.sub(r"(上り線|下り線|上り|下り)$", "", w)
        w = re.sub(r"\d+$", "", w)
        w = re.sub(r"(本線|付近|周辺|地先|地区)$", "", w)
        w = re.sub(r"(橋|大橋)([東西南北]詰|[東西南北]側|[東西南北])$", r"\1", w)
        w = re.sub(r"(トンネル|TN)(管理棟|管理所)$", r"\1", w)
        w = re.sub(r"(トンネル|TN)(.{1,4}側|[東西南北]?坑口[東西南北]?|[東西南北]口)$", r"\1", w)
        w = re.sub(r"(トンネル|TN)[東西南北]$", r"\1", w)
        w = re.sub(r"[【\[(（][^】\])）]*[】\])）]$", "", w)
        w = w.strip(" ・-")
    return w


def parse_label(label, route_hint=None):
    """Camera label -> {'routes', 'municipality_text', 'words'}: candidate words to look up, most specific first."""
    s = nfkc(label)
    routes = sorted(set(ROUTE.findall(s)) | ({route_hint} if route_hint else set()), key=lambda x: int(x))
    core = label_core(s)
    words = [w for w in re.split(r"[\s・/／,、～~〜]+", core) if w]
    return {"routes": routes, "core": core, "words": [strip_tail(w) for w in words if strip_tail(w)]}


def feature_of(word):
    m = FEATURE.match(word)
    if not m:
        return None
    kind = m.group("kind")
    kind = {"スマートIC": "SIC", "トンネル": "TN", "バスストップ": "BS", "大橋": "橋", "高架橋": "橋", "跨線橋": "橋",
            "陸橋": "橋", "橋梁": "橋", "高架": "橋"}.get(kind, kind)
    name = m.group("name") + ({"大橋": "大橋", "高架橋": "高架橋", "跨線橋": "跨線橋", "陸橋": "陸橋", "高架": "高架", "橋": "橋", "橋梁": "橋梁"}
                              .get(m.group("kind"), ""))
    if kind == "橋":
        return kind, name
    return kind, m.group("name")


# ---------------------------------------------------------------- page parsing (pure)
def text_of(body):
    if isinstance(body, str):
        return body
    head = body[:4000]
    m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', head)
    for enc in ([m.group(1).decode("ascii", "ignore")] if m else []) + ["utf-8", "cp932", "euc-jp"]:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def https(url):
    """The same URL over HTTPS (the bureau hosts serve both; pages still embed http:// links)."""
    return "https://" + url[len("http://"):] if url.startswith("http://") else url


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


NUMBERING = re.compile(r"^([\(（]?\d{1,3}[\)）.．]?|[❶-❿⓫-⓴①-⑳⑴-⒇]|[\d\s.．]+)$")
ROUTE_HEADING = re.compile(r"(?:一般)?国道\s*(\d{1,3})\s*号[^|]{0,30}(?:ライブカメラ|ライブ画像)|^R(\d{1,3})$|^国道\s*(\d{1,3})\s*号$")


def media_stream(text, media_re, start=None, end=None):
    """Media tags (a tag whose attributes match media_re: group 1 = still id) and text tokens, in page order."""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    if start:
        i = t.find(start)
        t = t[i:] if i >= 0 else t
    if end:
        j = t.find(end)
        t = t[:j] if j >= 0 else t
    media = re.compile(media_re)
    for m in re.finditer(r"<[^>]+>|[^<]+", t):
        s = m.group(0)
        if s.startswith("<"):
            mm = media.search(s)
            if mm:
                attrs = dict((k.lower(), html.unescape(v)) for k, v in re.findall(r'([A-Za-z_:-]+)\s*=\s*"([^"]*)"', s))
                yield ("media", mm.group(1), attrs)
        else:
            x = re.sub(r"\s+", " ", html.unescape(s)).strip()
            if x:
                yield ("text", x, None)


def stream_cameras(text, media_re, *, label="alt", before_n=1, start=None, end=None, route=None, after_n=1):
    """[{id, alt, before, route}] in page order, first occurrence of each still id.
    label 'alt': the tag's alt/title; 'before': the last before_n text tokens since the previous still
    (numbering dropped); route: the latest '国道N号…ライブカメラ' / 'RN' heading seen."""
    cams, seen, buf, current, context, last = [], set(), [], route, "", None
    for kind, value, attrs in media_stream(text, media_re, start, end):
        if kind == "text":
            h = ROUTE_HEADING.search(value)
            if h and len(value) <= 40:
                current = next(g for g in h.groups() if g)
                buf = []
                continue
            r = re.match(r"^(?:一般)?国道\s*(\d{1,3})\s*号\s*(.*)$", nfkc(value))
            if label == "after" and r:
                current, context = r.group(1), r.group(2).strip(" ・")
                if NOT_A_PLACE.search(context) or "・" in context or "～" in context:
                    context = ""
                continue
            if label == "after" and last is not None and not NUMBERING.match(value):
                if len(last["after_tokens"]) < after_n:
                    last["after_tokens"].append(value)
                    last["after"] = " ".join(last["after_tokens"])
                continue
            if not NUMBERING.match(value):
                buf.append(value)
            continue
        if value not in seen:
            seen.add(value)
            alt = nfkc(attrs.get("alt") or attrs.get("title") or "")
            alt = "" if alt in ("カメラ画像", "ライブカメラ画像", "画像") else alt
            cams.append({"id": value, "alt": alt, "before": " ".join(buf[-before_n:]) if before_n else "",
                         "route": current, "after": "", "after_tokens": [], "context": context})
            last = cams[-1]
        else:
            again = next(c for c in cams if c["id"] == value)
            last = again if not again["after_tokens"] else None
        buf = []
    return cams


def subpage_links(text, link_re):
    """[(href, title)] of per-camera sub-pages, first occurrence order."""
    out, seen = [], set()
    for m in re.finditer(r"<(?:a|area)\b[^>]*>", text, re.I):
        tag = m.group(0)
        h = re.search(link_re, tag)
        if h and h.group(1) not in seen:
            seen.add(h.group(1))
            title = re.search(r'(?:title|alt)="([^"]*)"', tag)
            out.append((h.group(1), nfkc(html.unescape(title.group(1))) if title else ""))
    return out


# ---------------------------------------------------------------- matching (pure)
FACILITY = re.compile(r"^(?P<place>.+?)(除雪基地|除雪ステーション|基地|出張所|維持出張所|中継所|管理所|道路情報板)$")
NOT_A_PLACE = re.compile(r"(アンダーパス|基地|出張所|管理棟|管理所|中継所|ランプ|出入口|合流|分岐|県境|高架|バイパス|BP|カメラ|"
                         r"ライブ|方面|線|道路|自動車道|地下道|歩道橋|料金所|駐車場|ゲート|チェーン|気象|観測)$")
NEIGHBOUR_KM = 15.0      # an ambiguous name is resolved only by a candidate this close to a placed neighbour
NEIGHBOUR_MAX_KM = 40.0  # a placement farther than this from every placed neighbour (within 3 in list order) is held
UNCERTAINTY = {"IC": 500, "JCT": 600, "SIC": 400, "SA/PA/接続部": 400, "node": 250, "way_pad": 150}
KIND_SUFFIX = {"TN": "トンネル", "BS": "", "交差点": ""}
NAMED_AFTER_PLACE_M = 3000  # a feature not found, placed at the centre of the place it is named after


def candidate_features(word, kind, cam, gaz):
    """Named-feature candidates for one label word: N06 joints for IC/JCT/SIC (and SA/PA), OSM otherwise."""
    prefs = cam["prefs"]
    out = []
    if kind in ("IC", "JCT", "SIC", "PA", "SA") and gaz.get("joints"):
        names = {word + kind} if kind != "SIC" else {word + "SIC", word + "スマートIC"}
        for name in names:
            for j in gaz["joints"].find(name):
                if gaz["isj"].in_prefs(j["lat"], j["lng"], prefs):
                    out.append({"tier": "n06", "lat": j["lat"], "lng": j["lng"], "source": f"ksj-n06:{j['id']}",
                                "licence": N06_LICENCE,
                                "feature": f"{j['name']} ({j['kind']}, 国土数値情報 高速道路時系列 N06-25)",
                                "uncertainty_m": UNCERTAINTY.get(j["kind"], 500), "role": "named_feature"})
        if out:
            return merge_close(out)
    osm = gaz.get("osm")
    if osm is None or not set(prefs) & osm.available:
        return out
    keys = set(feature_keys(word + ("" if kind == "橋" else KIND_SUFFIX.get(kind, kind))))
    if kind == "交差点":
        keys.add(nfkc(word))
    for key in keys:
        for e in osm.find(key, prefs):
            if kind in ("橋", "TN") and e["kind"] not in ("bridge", "tunnel"):
                continue
            if kind in ("橋", "TN") and cam.get("routes") and e["ref"] and not cam.get("expressway") and not (
                    set(re.split(r"[;,]", e["ref"])) & set(cam["routes"])):
                continue
            if kind in ("PA", "SA") and e["kind"] != "services":
                continue
            if kind == "峠" and e["kind"] not in ("pass", "junction"):
                continue
            if kind == "交差点" and e["kind"] != "junction":
                continue
            unc = e["extent_m"] + UNCERTAINTY["way_pad"] if e["type"] != "node" else UNCERTAINTY["node"]
            out.append({"tier": "osm", "lat": e["lat"], "lng": e["lng"], "source": f"osm:{e['type']}/{e['id']}",
                        "licence": "ODbL 1.0", "feature": f"{e['name']} (OpenStreetMap {e['type']} {e['id']})",
                        "uncertainty_m": max(200, round_up(unc, 50)), "role": "named_feature"})
    uniq = {}
    for c in out:
        uniq.setdefault(c["source"], c)
    return merge_close(list(uniq.values()))


def merge_close(cands, within_m=2000):
    """Candidates of the same tier within 2 km of each other are one feature (duplicate dataset records)."""
    kept = []
    for c in cands:
        if not any(k["tier"] == c["tier"] and distance_m(k["lat"], k["lng"], c["lat"], c["lng"]) <= within_m for k in kept):
            kept.append(c)
    return kept


def candidate_places(word, cam, gaz, muni=None):
    places = gaz["isj"].find(word, cam["prefs"], muni)
    if not places and len(word) > 2 and word[-1] in "東西南北":
        places = gaz["isj"].find(word[:-1], cam["prefs"], muni)
    return [{"tier": "isj", "lat": p["lat"], "lng": p["lng"], "source": f"mlit-isj:{p['muni_code']}/{p['name']}",
             "licence": ISJ_LICENCE,
             "feature": f"{p['muni']} {p['name']} (大字・町丁目位置参照情報 {ISJ_VERSION}, 国土交通省)",
             "uncertainty_m": p["uncertainty_m"], "role": "place_centre"} for p in places]


def label_words(cam, gaz):
    """(municipality named by the label or None, feature words [(word, kind, name)], place words, other words)."""
    label = cam["label"]
    parsed = parse_label(label, None if ROUTE.search(nfkc(label)) else cam.get("route"))
    cam["routes"] = parsed["routes"] or cam.get("routes") or []
    muni = gaz["isj"].municipality_in(nfkc(label), cam["prefs"])
    words = []
    for w in (cam.get("feature_words") or []) + parsed["words"]:
        if muni and w.startswith(muni) and len(w) > len(muni):
            w = w[len(muni):]
        elif muni and w == muni:
            continue
        words.append(w)
    if not muni:
        for i, w in enumerate(words):
            hit = None if feature_of(w) else gaz["isj"].municipality_stem(w, cam["prefs"])
            if hit and gaz["isj"].find(hit[1], cam["prefs"], hit[0]):
                muni, words[i] = hit
                break
    joined = ["".join(words[i:i + 2]) for i in range(len(words) - 1)
              if not feature_of(words[i]) and not feature_of(words[i + 1]) and len(words[i + 1]) >= 2]
    features, places, other = [], [], []
    for w in joined + words:
        f = feature_of(w)
        if f:
            features.append((w, f[0], f[1]))
        elif FACILITY.match(w):
            places.append(FACILITY.match(w).group("place"))
        elif not NOT_A_PLACE.search(w) and len(w) >= 1 and not re.fullmatch(r"[\dA-Za-z.]+", w):
            places.append(w)
        else:
            other.append(w)
    return muni, features, places, other


def camera_candidates(cam, gaz):
    """(candidates of the most specific tier found, note). Feature words first, then place words. A label naming a
    feature that is not found is held, except a junction (交差点 = a street corner: the named place's centre)."""
    muni, features, places, other = label_words(cam, gaz)
    for w, kind, name in features:
        cands = candidate_features(name, kind, cam, gaz)
        if cands:
            return cands, f"feature '{w}'"
    missing = [w for w, k, _ in features if k != "交差点"]
    for w, kind, name in features:
        stem = (FEATURE.match(w).group("name") if FEATURE.match(w) else name)
        stem = re.sub(r"(新|旧)$", "", stem)
        if kind == "交差点" or len(stem) < 2 or NOT_A_PLACE.search(stem):
            continue
        cands = candidate_places(stem, cam, gaz, muni)
        for c in cands:
            c["uncertainty_m"] = max(c["uncertainty_m"], NAMED_AFTER_PLACE_M)
            c["named_after"] = w
            c["muni_in_label"] = bool(muni)
            c["feature"] = c["feature"] + f" — place the feature '{w}' is named after"
        if cands:
            return cands, f"place '{stem}' named by the feature '{w}' (feature not found)"
    if missing:
        osm = gaz.get("osm")
        why = ("OpenStreetMap lookup unavailable (Overpass did not answer)"
               if osm is None or not set(cam["prefs"]) & osm.available else "not found as a named feature")
        return [], f"feature '{missing[0]}': {why}"
    places = [name for w, k, name in features if k == "交差点"] + places
    first_multi = None
    for w in places:
        cands = candidate_places(w, cam, gaz, muni)
        if len(cands) == 1:
            return cands, f"place '{w}'" + (f" in {muni}" if muni else "")
        if cands and first_multi is None:
            first_multi = (cands, f"place '{w}'" + (f" in {muni}" if muni else ""))
    if first_multi:
        return first_multi
    if other and not places:
        return [], "label names no feature or place that can be placed (" + "/".join(other) + ")"
    return [], "no named feature or place found" + (" (" + "/".join(places) + ")" if places else "")


def resolve(cams, gaz):
    """Pick one candidate per camera: unique candidates first, then ambiguous ones resolved by placed neighbours
    (list order = route order within an office) or by the camera's section interchanges; then a neighbour check."""
    for cam in cams:
        cands, note = camera_candidates(cam, gaz)
        cam["_cands"], cam["_note"] = cands, note
        cam["_pick"] = cands[0] if len(cands) == 1 else None
        cam["_held"] = None
    by_office = collections.defaultdict(list)
    for cam in cams:
        by_office[(cam["source"], cam["office_key"])].append(cam)

    def anchors(group, i):
        out = [group[j]["_pick"] for j in range(max(0, i - 3), min(len(group), i + 4))
               if j != i and group[j].get("_pick")]
        return out + list(group[i].get("anchors") or [])

    for _round in range(3):
        for group in by_office.values():
            for i, cam in enumerate(group):
                if cam["_pick"] or len(cam["_cands"]) < 2:
                    continue
                near = anchors(group, i)
                if not near:
                    continue
                scored = sorted((min(distance_m(c["lat"], c["lng"], a["lat"], a["lng"]) for a in near) / 1000, k)
                                for k, c in enumerate(cam["_cands"]))
                (best, k1), (second, _) = scored[0], scored[1]
                if best <= NEIGHBOUR_KM and second > max(2 * best, NEIGHBOUR_KM):
                    cam["_pick"] = dict(cam["_cands"][k1],
                                        disambiguated=f"nearest to the neighbouring cameras ({best:.1f} km)")
    for group in by_office.values():
        for i, cam in enumerate(group):
            pick = cam["_pick"]
            if not pick or not pick.get("named_after") or pick.get("muni_in_label"):
                continue
            firm = [g["_pick"] for j, g in enumerate(group) if j != i and abs(j - i) <= 3 and g.get("_pick")
                    and not g["_pick"].get("named_after")] + list(cam.get("anchors") or [])
            d = min((distance_m(pick["lat"], pick["lng"], a["lat"], a["lng"]) / 1000 for a in firm), default=None)
            if d is None or d > NEIGHBOUR_KM:
                cam["_held"] = (f"feature '{pick['named_after']}' not found; the place it is named after is not confirmed by "
                                "the label's municipality or a placed neighbouring camera within 15 km")
                cam["_pick"] = None
    for group in by_office.values():
        for i, cam in enumerate(group):
            if not cam["_pick"]:
                continue
            near = [g["_pick"] for j, g in enumerate(group) if j != i and abs(j - i) <= 3 and g.get("_pick")]
            near += list(cam.get("anchors") or [])
            if near:
                d = min(distance_m(cam["_pick"]["lat"], cam["_pick"]["lng"], a["lat"], a["lng"]) for a in near) / 1000
                if d > NEIGHBOUR_MAX_KM:
                    cam["_held"] = f"placement {d:.0f} km from every placed neighbour in the office list"
                    cam["_pick"] = None
    for cam in cams:
        if not cam["_pick"] and not cam["_held"]:
            if len(cam["_cands"]) > 1:
                cam["_held"] = f"{len(cam['_cands'])} candidates for {cam['_note']}, not resolved by neighbours"
            else:
                cam["_held"] = cam["_note"]
    return cams


# ---------------------------------------------------------------- offices (camera list pages)
KKR = "https://www.kkr.mlit.go.jp"
SEISHIGA = "https://www.seishiga.kkr.mlit.go.jp"
KINKI_INDEX = KKR + "/road/strategy/camera.html"
DRIVEPLAZA = "https://www.driveplaza.com/traffic/camera/"


def kinki_office(key, office, prefs, url, folder, label="alt", before_n=0, **extra):
    return dict(source="mlit_kinki_road_cameras", key=key, office=office, prefs=prefs, url=url,
                media=r"(?:seishiga\.kkr\.mlit\.go\.jp/" + folder + r"/|^|[\"'/])pic/(C\d{5})\.jpg",
                snapshot=SEISHIGA + "/" + folder + "/pic/{id}.jpg", label=label, before_n=before_n, **extra)


OFFICES = [
    kinki_office("shiga", "滋賀国道事務所", ["25"], KKR + "/shiga/live/index.html", "shiga", label="before", before_n=1),
    *[kinki_office(f"kyoto_{r}", "京都国道事務所", ["26"], KKR + f"/kyoto/traffic/livecamera/{r}_livecamera.html", "kyoto",
                   label="before", before_n=1, route={"1gou": "1", "1goubp": "1", "9gou": "9", "24gou": "24"}[r])
      for r in ("1gou", "1goubp", "9gou", "24gou")],
    kinki_office("fukuchiyama", "福知山河川国道事務所", ["26"], KKR + "/fukuchiyama/road/cctv/", "hukuchiyama",
                 label="before", before_n=2),
    kinki_office("osaka", "大阪国道事務所", ["27", "28", "29", "30"], KKR + "/osaka/", "osaka", start='id="livecamera"',
                 end="開ける"),
    kinki_office("toyooka", "豊岡河川国道事務所", ["28", "26"], KKR + "/toyooka/bosai/road/road-camera.html", "toyooka"),
    kinki_office("himeji_r2", "姫路河川国道事務所", ["28"], KKR + "/himeji/bousai/livecam/r2.html", "himeji", route="2"),
    kinki_office("himeji_r29", "姫路河川国道事務所", ["28"], KKR + "/himeji/bousai/livecam/r29.html", "himeji", route="29"),
    kinki_office("hyogo", "兵庫国道事務所", ["28"], KKR + "/hyogo/douroinfo/cam/index.html", "hyogo"),
    kinki_office("nara", "奈良国道事務所", ["29"], KKR + "/nara/lcamera/index.html", "nara",
                 subpages=r'href="(/nara/lcamera/cctv_\d+\.html)"', sub_label="nara"),
    kinki_office("kinan", "紀南河川国道事務所", ["30"], SEISHIGA + "/kinan/map.html", "kinan", route="42",
                 subpages=r'href="(\./cam\d+\.html)"', sub_label="alt_map"),
    kinki_office("wakayama", "和歌山河川国道事務所", ["30"], KKR + "/wakayama/cam_douro/index.html", "wakayama"),
]
QSR = "https://www.qsr.mlit.go.jp"
THR = "https://www.thr.mlit.go.jp"
THR2 = "https://www2.thr.mlit.go.jp"
KTR = "https://www.ktr.mlit.go.jp"
OFFICES += [
    dict(source="mlit_kyushu_road_cameras", key="kitakyu", office="北九州国道事務所", prefs=["40"],
         url=QSR + "/kitakyu/bousai/livecamera/index.html", media=r"/kitakyu/camera/(cam\d+_\d)\.jpg",
         snapshot=QSR + "/kitakyu/camera/{id}.jpg", label="after", start="下記画像をクリック"),
    dict(source="mlit_kyushu_road_cameras", key="sakoku", office="佐賀国道事務所", prefs=["41"],
         url=QSR + "/sakoku/bousai_doro/camera/index.html", media=r"/sakoku/bousai/data/img/cctv/(S?\d{5})\.jpg",
         snapshot=QSR + "/sakoku/bousai/data/img/cctv/{id}.jpg", label="alt"),
    dict(source="mlit_kyushu_road_cameras", key="kakoku", office="鹿児島国道事務所", prefs=["46"],
         url=QSR + "/kakoku/traffic/cctv/", media=r"/kakoku/cctvimg/([A-Za-z0-9_]+)\.jpg",
         snapshot=QSR + "/kakoku/cctvimg/{id}.jpg", label="before", before_n=1),
    dict(source="mlit_tohoku_bureau_terms", key="aomori", office="青森河川国道事務所", prefs=["02"],
         url=THR + "/aomori/road/cctv/index.html", media=r"www2\.thr\.mlit\.go\.jp/aomori/roadcctv/(\d{3})\.jpg",
         snapshot=THR2 + "/aomori/roadcctv/{id}.jpg", label="alt", page_tpl=THR + "/aomori/road/cctv/{id}.html"),
    *[dict(source="mlit_tohoku_bureau_terms", key=f"yamagata_{m}", office="山形河川国道事務所", prefs=["06"],
           url=THR + f"/yamagata/camera-road/s-map-{m}.html",
           media=r"www2\.thr\.mlit\.go\.jp/yamagata/ycam/data/([0-9A-Za-z_-]+)\.jpg",
           snapshot=THR2 + "/yamagata/ycam/data/{id}.jpg", label="alt", route=re.sub(r"\D", "", m))
      for m in ("13n", "13s", "112", "113", "47e", "47w", "48")],
    dict(source="mlit_tohoku_bureau_terms", key="sakata", office="酒田河川国道事務所", prefs=["06"],
         url=THR + "/sakata/road/view/", media=r"www2\.thr\.mlit\.go\.jp/Bumon/J76301/livecam/([0-9A-Za-z_-]+)\.jpg",
         snapshot=THR2 + "/Bumon/J76301/livecam/{id}.jpg", label="alt"),
    dict(source="mlit_tohoku_bureau_terms", key="sanriku", office="三陸国道事務所", prefs=["03"],
         url=THR + "/bumon/j73501/gazou/list.html", media=r'images/(cctv\d+)\.jpg', snapshot=None, label="after",
         after_n=2, route="45"),
    dict(source="mlit_tohoku_bureau_terms", key="koriyama", office="郡山国道事務所", prefs=["07"],
         url=THR + "/koriyama/inform/index1.html", media=r"jpeg\?jpeg=(775_C\d+)_l\.jpg", snapshot=None,
         label="after", after_n=1, route="4"),
    dict(source="mlit_kanto_cctv", key="utunomiya", office="宇都宮国道事務所", prefs=["09"],
         url=KTR + "/utunomiya/utunomiya_index002.html", media=None, snapshot=KTR + "/river/cctv/{id}.jpg",
         subpages=r'href="((?:https?://www\.ktr\.mlit\.go\.jp)?/utunomiya/utunomiya(?:_livecamera|00)\d+\.html)"',
         sub_label="kanto", plain_id=True),
    dict(source="mlit_kanto_cctv", key="takasaki", office="高崎河川国道事務所", prefs=["10"],
         url=KTR + "/takasaki/takasaki_index009.html", media=None, snapshot=KTR + "/river/cctv/{id}.jpg",
         subpages=r'href="((?:https?://www\.ktr\.mlit\.go\.jp)?/takasaki/takasaki00\d+\.html)"',
         sub_label="kanto", plain_id=True),
    dict(source="mlit_kanto_cctv", key="oomiya", office="大宮国道事務所", prefs=["11"],
         url=KTR + "/oomiya/oomiya_livecamera01.html", media=None, snapshot=KTR + "/river/cctv/{id}.jpg",
         subpages=r'href="((?:https?://www\.ktr\.mlit\.go\.jp)?/oomiya/oomiya(?:00\d+|_lc_[a-z0-9_]+)\.html)"',
         sub_label="kanto", snapshot_oomiya=KTR + "/oomiya/livecamera/{id}.jpg"),
]
NEXCO_AREAS = {"hokkaido": ["01"], "tohoku": ["02", "03", "04", "05", "06", "07"],
               "kanto": ["08", "09", "10", "11", "12", "13", "14", "19", "20"],
               "shinetsu": ["15", "20", "10", "16"]}
HOLD_ONLY = {  # list pages read, nothing placeable: (source, office) -> reason
    ("mlit_kinki_road_cameras", "福井河川国道事務所"): "www.fukui.kkr.mlit.go.jp answered HTTP 403 to the collector (not retried)",
}


def office_by_key(key):
    return next(o for o in OFFICES if o["key"] == key)


def raw_name(office, sub=None):
    base = f"places/{office['key']}.html"
    if sub:
        base = f"places/{office['key']}/" + re.sub(r"[^A-Za-z0-9_.-]+", "_", sub.strip("./"))
    return base


def nara_subpage(text):
    """(name, still id) of a Nara per-camera page ('名阪国道：岩屋')."""
    name = re.search(r'm-module-borderBottomTitle01">\s*([^<]+?)\s*<', text)
    still = re.search(r"pic/(C\d{5})\.jpg", text)
    return (nfkc(html.unescape(name.group(1))) if name else None), (still.group(1) if still else None)


def office_cameras(office, text, sub_texts=None):
    """Camera rows of one office list page: {id, label, route, page, snapshot}."""
    rows = []
    if office.get("subpages"):
        links = subpage_links(text, office["subpages"])
        alts = {}
        if office["sub_label"] == "kanto":
            for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S):
                href = m.group(1)
                if not re.search(office["subpages"], f'href="{href}"'):
                    continue
                inner = m.group(2)
                alt = re.search(r'alt="([^"]*)"', inner)
                alts.setdefault(re.search(office["subpages"], f'href="{href}"').group(1),
                                nfkc(html.unescape(alt.group(1))) if alt and alt.group(1).strip() else nfkc(clean(inner)))
        if office["sub_label"] == "alt_map":   # Kinan: <area href=./camN.html alt="みなべ町南道 392.3KP">
            for href, alt in re.findall(r'<area[^>]*href="(\./cam\d+\.html)"[^>]*alt="([^"]*)"', text):
                alts.setdefault(href, nfkc(alt))
        for href, title in links:
            sub = (sub_texts or {}).get(href)
            if not sub:
                continue
            if office["sub_label"] == "kanto" and office["key"] == "oomiya":
                heading = re.search(r"<title>\s*([^<|｜]+)", sub)
                district = nfkc(html.unescape(heading.group(1))) if heading else (alts.get(href) or title)
                tokens = [x for k, x, _ in media_stream(sub, r"/oomiya/livecamera/(\d+_[A-Z])\.jpg", start="見たい場所の地区名") if k == "text"]
                labels = [nfkc(m.group(1)) for x in tokens if isinstance(x, str)
                          for m in [re.match(r"^[\(（]\d+[\)）]\s*(.+)$", x)] if m]
                stills = [x for k, x, _ in media_stream(sub, r"/oomiya/livecamera/(\d+_[A-Z])\.jpg", start="見たい場所の地区名")
                          if k == "media"]
                labels = [x for x in labels if x not in ()][: len(stills)]
                if len(labels) == len(stills):
                    muni = (re.search(r"号\s*(\S+?[市町村])", nfkc(district)) or [None, ""])[1]
                    route = (ROUTE.search(nfkc(district)) or [None, None])[1]
                    for still, lab in zip(stills, labels):
                        rows.append({"id": still, "label": f"{muni} {lab}".strip(), "route": route,
                                     "page": https(urljoin(office["url"], href)), "district": district})
                continue
            if office["sub_label"] == "kanto":
                index_label = re.sub(r"^\(\d+\)\s*", "", alts.get(href) or title)
                for m in re.finditer(r'<img[^>]*/river/cctv/(C\d{5})\.jpg[^>]*>', sub):
                    still = m.group(1)
                    alt = (re.search(r'alt="([^"]*)"', m.group(0)) or [None, ""])[1]
                    own = re.sub(r"(ライブカメラ映像|ライブ映像|の映像|画像)$", "", nfkc(html.unescape(alt or ""))).strip()
                    label = own if own and own not in ("ライブカメラ",) else index_label
                    if still not in {r["id"] for r in rows}:
                        rows.append({"id": still, "label": label, "route": office.get("route"),
                                     "page": https(urljoin(office["url"], href)), "district": index_label})
                continue
            if office["sub_label"] == "nara":
                name, still = nara_subpage(sub)
                route = "25" if name and "名阪" in name else "24" if name and "京奈和" in name else None
                label = (name or title).split("：")[-1]
            else:
                still = (re.search(r"pic/(C\d{5})\.jpg", sub) or [None, None])[1]
                label, route = alts.get(href) or title, office.get("route")
            if still:
                rows.append({"id": still, "label": label, "route": route or office.get("route"),
                             "page": https(urljoin(office["url"], href))})
        return rows
    for cam in stream_cameras(text, office["media"], label=office["label"], before_n=office.get("before_n", 0),
                              start=office.get("start"), end=office.get("end"), route=office.get("route"),
                              after_n=office.get("after_n", 1)):
        label = cam["before"] if office["label"] == "before" else \
            (cam["after"] + " " + cam["context"]).strip() if office["label"] == "after" else cam["alt"]
        label = re.sub(r"(ライブカメラ映像|ライブ映像|画像)$", "", label).strip()
        label = re.sub(r"^\d{1,3}[.．]\s*", "", label)
        route = cam["route"]
        alt_route = ROUTE.search(cam["alt"] or "")
        if alt_route:
            route = alt_route.group(1)
        page = office["page_tpl"].format(id=cam["id"]) if office.get("page_tpl") else office["url"]
        rows.append({"id": cam["id"], "label": label, "route": route, "page": page, "alt": cam["alt"]})
    return rows


def nexco_cameras(text, area):
    """NEXCO East area page: [{code, road, section, name}] of the cameras shown (commented-out ones skipped)."""
    t = re.sub(r"(?s)<!--.*?-->", " ", text)
    rows, road = [], None
    for m in re.finditer(r'<h2[^>]*>(.*?)</h2>|<img src="https?://cdn-livecamera-pic\.drivetraffic\.jp/l/([A-Za-z0-9_]+)\.jpg"'
                         r'[^>]*>.*?<h3[^>]*>(.*?)</h3>\s*<p>\s*カメラ名称\s*[:：]\s*(.*?)</p>', t, re.S):
        if m.group(1) is not None:
            road = nfkc(clean(m.group(1)))
            continue
        rows.append({"code": m.group(2), "road": road, "section": clean(m.group(3)), "name": nfkc(clean(m.group(4))),
                     "area": area})
    return rows


def section_ends(section):
    """'水上IC ～ 関越トンネル' -> ['水上IC', '関越トンネル'] (the interchanges bounding the camera's section)."""
    return [p.strip() for p in re.split(r"[～~〜]", section) if p.strip()]


# ---------------------------------------------------------------- acquisition (network, sequential, resumable)
class Acquirer:
    def __init__(self, out, client=None):
        self.out, self.client, self.refused = Path(out), client or F.PoliteClient(delay=1.2, timeout=120), []

    def path(self, source, name):
        return self.out / "raw" / source / name

    def get(self, source, name, url, max_bytes=16 * 1024 * 1024):
        target = self.path(source, name)
        if target.exists():
            return target.read_bytes()
        try:
            r = self.client.get(url, max_bytes=max_bytes)
        except F.Refused as e:
            self.refused.append({"source": source, "url": url, "host": urlsplit(url).hostname, "reason": str(e)[:200]})
            return None
        except OSError as e:
            self.refused.append({"source": source, "url": url, "host": urlsplit(url).hostname,
                                 "reason": f"{type(e).__name__}: {str(e)[:160]}"})
            return None
        if r["status"] != 200:
            self.refused.append({"source": source, "url": url, "host": urlsplit(url).hostname,
                                 "reason": f"HTTP {r['status']} (not saved)"})
            return None
        F.save_raw(target.parent, target.name, r)
        return r["body"]


def acquire_lists(a):
    for office in OFFICES:
        body = a.get(office["source"], raw_name(office), office["url"])
        if body is None or not office.get("subpages"):
            continue
        for href, _ in subpage_links(text_of(body), office["subpages"]):
            a.get(office["source"], raw_name(office, href), https(urljoin(office["url"], href)))
    for area in NEXCO_AREAS:
        a.get("nexco_east_driveplaza", f"places/{area}.html", f"{DRIVEPLAZA}{area}.html")


def needed_prefectures():
    prefs = set()
    for office in OFFICES:
        prefs.update(office["prefs"])
    for values in NEXCO_AREAS.values():
        prefs.update(values)
    return sorted(prefs)


def acquire_gazetteers(a):
    a.get("places", "places_japan/ksj/N06-25_GML.zip", N06_URL, max_bytes=40 * 1024 * 1024)
    for pref in needed_prefectures():
        a.get("places", f"places_japan/isj/{pref}000-{ISJ_VERSION}.zip", ISJ_URL.format(v=ISJ_VERSION, pref=pref))


def osm_prefectures():
    """Prefectures whose OSM features are looked up: each office's own prefecture, and the NEXCO areas."""
    first = sorted({office["prefs"][0] for office in OFFICES})
    rest = sorted({p for values in NEXCO_AREAS.values() for p in values} - set(first))
    return first + rest


def overpass_cache(out):
    return Path(out) / "raw" / "places" / "places_japan" / "overpass"


def acquire_osm(a, out, isj, attempts=3, pause_s=60, budget_s=80 * 60):
    """One Overpass query per prefecture, sequential; a failed prefecture is retried later (attempts, pause_s apart).
    Answers are cached by webcam_places.cached_json, so rebuilds never repeat a lookup."""
    import time
    import webcam_places as WP
    status, started = {}, time.monotonic()
    for attempt in range(attempts):
        for pref in osm_prefectures():
            if status.get(pref, {}).get("ok"):
                continue
            if time.monotonic() - started > budget_s:
                status.setdefault(pref, {"ok": False, "reason": "time budget for Overpass spent", "attempt": attempt})
                continue
            query = overpass_query(isj.pref_bbox[pref])
            try:
                data = WP.overpass(a.client, query, overpass_cache(out))
                ok = bool(data.get("elements")) or not data.get("remark")
                status[pref] = {"ok": ok, "elements": len(data.get("elements", [])), "remark": data.get("remark"),
                                "attempt": attempt + 1}
            except (F.Refused, OSError, ValueError) as e:
                status[pref] = {"ok": False, "reason": str(e)[:160], "attempt": attempt + 1}
            print(F.now(), pref, status[pref], flush=True)
        if all(s.get("ok") for s in status.values()):
            break
        if attempt + 1 < attempts:
            time.sleep(pause_s)
    for pref, s in status.items():
        if not s.get("ok"):
            a.refused.append({"source": "places", "url": WP.OVERPASS, "host": urlsplit(WP.OVERPASS).hostname,
                              "reason": f"JP-{pref}: {s.get('reason') or s.get('remark')}"})
    return status


def load_osm(out, isj):
    """Cached Overpass answers only (offline); a prefecture without one is 'unavailable'."""
    found = {}
    for pref in osm_prefectures():
        query = overpass_query(isj.pref_bbox[pref])
        path = overpass_cache(out) / (hashlib.sha256(("overpass:" + query).encode()).hexdigest()[:24] + ".json")
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))["data"]
            if data.get("elements") or not data.get("remark"):
                found[pref] = data.get("elements", [])
    return Osm(found) if found else None, sorted(found)


# ---------------------------------------------------------------- items (pure)
PDL_RIGHTS = ("Site content, including camera stills, is usable under PDL1.0 (copy, public transmission, adaptation, "
              "commercial use) unless a page carries its own rights notice; the camera pages used carry none. "
              "Source attribution (出典 + page URL) and an edit notice are mandatory; QGlobe must not present the "
              "result as made by the agency.")
BUREAUS = {
    "mlit_kinki_road_cameras": {"bureau": "近畿地方整備局", "site": "近畿地方整備局ホームページ", "en": "MLIT Kinki Regional Development Bureau",
                                "media_hosts": ["www.seishiga.kkr.mlit.go.jp"],
                                "page_hosts": ["www.kkr.mlit.go.jp", "www.seishiga.kkr.mlit.go.jp"],
                                "terms_url": KKR + "/link.html", "url": KINKI_INDEX,
                                "rights_clause": ("「当ホームページで公開している情報（以下「コンテンツ」といいます。）の著作権は、特記されていない限り"
                                                  "国土交通省近畿地方整備局に帰属し、権利表記の記載がない限り「 公共データ利用規約（第1.0版） 」"
                                                  "（PDL1.0）に準拠した利用条件の下で、利用することができます。」")},
    "mlit_kyushu_road_cameras": {"bureau": "九州地方整備局", "site": "九州地方整備局ホームページ",
                                 "en": "MLIT Kyushu Regional Development Bureau", "media_hosts": ["www.qsr.mlit.go.jp"],
                                 "page_hosts": ["www.qsr.mlit.go.jp"], "terms_url": QSR + "/pp/index.html",
                                 "url": QSR + "/useful/road_livecam.html",
                                 "rights_clause": ("Bureau site policy (/pp/) and the Kumamoto office copyright page apply PDL1.0 "
                                                   "to site content unless a rights notice says otherwise (research register).")},
    "mlit_tohoku_bureau_terms": {"bureau": "東北地方整備局", "site": "東北地方整備局ホームページ",
                                 "en": "MLIT Tohoku Regional Development Bureau", "media_hosts": ["www2.thr.mlit.go.jp"],
                                 "page_hosts": ["www.thr.mlit.go.jp"], "terms_url": THR + "/policy.pdf",
                                 "url": "https://www.mlit.go.jp/road/bosai/LIVEcamera.html",
                                 "rights_clause": ("「当ホームページのコンテンツの利用については、【 公共データ利用規約（第 1.0 版） "
                                                   "(digital.go.jp) ［デジタル庁］】に定めるとおりです。」「当ホームページは、原則リンクフリーです。」")},
    "mlit_kanto_cctv": {"bureau": "関東地方整備局", "site": "関東地方整備局ウェブサイト", "en": "MLIT Kanto Regional Development Bureau",
                        "media_hosts": ["www.ktr.mlit.go.jp"], "page_hosts": ["www.ktr.mlit.go.jp"],
                        "terms_url": KTR + "/guide/copyright.html", "url": KTR + "/guide/guide00000012.html", "rights_clause": ""},
}


def placed_item(base, pick, observed_at):
    import webcam_places as WP
    item = dict(base)
    WP.place(item, role=pick["role"], lat=pick["lat"], lng=pick["lng"], source=pick["source"], feature=pick["feature"],
             uncertainty_m=pick["uncertainty_m"], licence=pick["licence"])
    note = {"named_feature": "Position of the named feature the camera label refers to, not the camera itself.",
            "place_centre": "Representative point of the named place (大字・町丁目); the camera is somewhere in that place."}
    if pick.get("named_after"):
        note["place_centre"] = (f"The label names '{pick['named_after']}', not found in an open dataset: centre of the "
                                "place it is named after, with a wider uncertainty.")
    item["coordinate_note"] = note[pick["role"]] + (f" Chosen among same-named candidates: {pick['disambiguated']}."
                                                    if pick.get("disambiguated") else "")
    item["observed_at"] = observed_at
    return item


def bureau_item(cam, office, observed_at):
    source = office["source"]
    b = BUREAUS[source]
    page = cam["page"]
    routes = cam.get("routes") or []
    road = "国道" + "・".join(routes) + "号" if routes else None
    name = nfkc(cam["label"])
    if road and not ROUTE.search(name):
        name = f"{road} {name}"
    edit = "画像を縮小表示し、名称・位置等を" if office.get("snapshot") else "名称・位置等を"
    notice = (f"出典：国土交通省 {b['site']}（{office['office']} {page}）を加工して作成（QGlobeが{edit}"
              f"正規化・編集）。国土交通省が作成したものではありません。" + GAZETTEER_NOTICE)
    pid = cam["id"] if office.get("plain_id") else f"{office['key'].split('_')[0]}-{cam['id']}"
    pid = re.sub(r"[^A-Za-z0-9:_.-]", "_", pid)
    viewable = bool(office.get("snapshot"))
    return {"provider": source, "provider_id": pid, "id": f"{source}:{pid}", "name": name, "country": "JP",
            "region": cam.get("region") or "", "rights_status": "official_public_feed" if viewable else "official_page_only",
            "format": "snapshot" if viewable else "official_page",
            "snapshot_url": (office.get("snapshot_oomiya") if re.fullmatch(r"\d+_[A-Z]", cam["id"]) else office["snapshot"])
            .format(id=cam["id"]) if viewable else None, "stream_url": None,
            "official_page": page,
            "source_page": b["url"], "source_catalog": office["url"], "observed_at": observed_at,
            "health": {"status": "unverified"}, "provider_in_service": None, "road": road,
            "minimum_refresh_seconds": 600, "office": office["office"], "label": cam["label"],
            "provider_notice": notice, "attribution": notice, "operator": f"国土交通省 {b['bureau']} {office['office']}"}


def nexco_item(cam, observed_at):
    page = f"{DRIVEPLAZA}{cam['area']}.html"
    notice = ("NEXCO東日本「ドラぷら」のライブカメラページへのリンクです（画像の転載はできません）。" + GAZETTEER_NOTICE)
    return {"provider": "nexco_east_driveplaza", "provider_id": cam["code"], "id": f"nexco_east_driveplaza:{cam['code']}",
            "name": f"{cam['road']} {cam['name']}（{cam['section']}）" if cam.get("road") else f"{cam['name']}（{cam['section']}）",
            "country": "JP", "region": "", "rights_status": "official_page_only", "format": "official_page",
            "snapshot_url": None, "stream_url": None, "official_page": page, "source_page": DRIVEPLAZA,
            "source_catalog": page, "observed_at": observed_at, "health": {"status": "unverified"},
            "provider_in_service": None, "road": cam.get("road"), "section": cam["section"], "label": cam["name"],
            "provider_notice": notice, "operator": "東日本高速道路株式会社 (NEXCO東日本)"}


def nearest_place_pref(lat, lng, isj):
    """The prefecture of the nearest 大字/町丁目 representative point (the card's region)."""
    return isj.pref_at(lat, lng)


# ---------------------------------------------------------------- build (offline from raw)
def read_raw(out, source, name):
    path = Path(out) / "raw" / source / name
    if not path.exists():
        return None, None
    receipt = path.parent / (path.name + ".receipt.json")
    return path.read_bytes(), (json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {})


def load_gazetteers(out):
    blobs = []
    for pref in needed_prefectures():
        body, _ = read_raw(out, "places", f"places_japan/isj/{pref}000-{ISJ_VERSION}.zip")
        if body:
            blobs.append(body)
    isj = Isj.from_zip_bytes(blobs)
    n06, _ = read_raw(out, "places", "places_japan/ksj/N06-25_GML.zip")
    return {"isj": isj, "joints": Joints.from_zip_bytes(n06) if n06 else None}


def collect_rows(out):
    """{office: rows} for every bureau office, plus the NEXCO rows and the offices that could not be read."""
    rows_by_office, unread = {}, []
    for office in OFFICES:
        body, receipt = read_raw(out, office["source"], raw_name(office))
        if body is None:
            unread.append({"source": office["source"], "office": office["office"], "url": office["url"]})
            continue
        text = text_of(body)
        subs = {}
        if office.get("subpages"):
            for href, _ in subpage_links(text, office["subpages"]):
                sub, _ = read_raw(out, office["source"], raw_name(office, href))
                if sub:
                    subs[href] = text_of(sub)
        rows = office_cameras(office, text, subs)
        for row in rows:
            row["observed_at"] = receipt.get("observed_at")
        rows_by_office[office["key"]] = (office, rows)
    nexco = []
    for area in NEXCO_AREAS:
        body, receipt = read_raw(out, "nexco_east_driveplaza", f"places/{area}.html")
        if body is None:
            unread.append({"source": "nexco_east_driveplaza", "office": area, "url": f"{DRIVEPLAZA}{area}.html"})
            continue
        for row in nexco_cameras(text_of(body), area):
            row["observed_at"] = receipt.get("observed_at")
            nexco.append(row)
    return rows_by_office, nexco, unread


def nexco_anchor(name, prefs, gaz):
    """The N06 joint of a section end ('水上IC', '更埴JCT') when it is unique in the area, else None."""
    f = feature_of(strip_tail(nfkc(name)))
    if not f or f[0] not in ("IC", "JCT", "SIC") or not gaz.get("joints"):
        return None
    cands = [c for c in candidate_features(f[1], f[0], {"prefs": prefs}, {"joints": gaz["joints"], "isj": gaz["isj"]})]
    return cands[0] if len(cands) == 1 else None


def build(out, countries_path, catalog=None):
    import webcam_places as WP
    out = Path(out)
    gaz = load_gazetteers(out)
    rows_by_office, nexco_rows, unread = collect_rows(out)
    nexco_prefs = sorted({p for ps in NEXCO_AREAS.values() for p in ps})
    gaz["osm"], osm_prefs = load_osm(out, gaz["isj"])
    cams, seen = [], set()
    for key, (office, rows) in rows_by_office.items():
        for row in rows:
            uid = (office["source"], row["id"] if office.get("plain_id") else key.split("_")[0] + "-" + row["id"])
            if uid in seen:
                continue
            seen.add(uid)
            cams.append({"source": office["source"], "office_key": key.split("_")[0], "office": office, "label": row["label"],
                         "route": row.get("route"), "prefs": office["prefs"], "row": row})
    for row in nexco_rows:
        prefs = NEXCO_AREAS[row["area"]]
        name = strip_tail(row["name"])
        cam = {"source": "nexco_east_driveplaza", "office_key": row["area"], "label": name, "prefs": prefs,
               "expressway": True, "row": row, "anchors": [a for a in (nexco_anchor(e, prefs, gaz)
                                                                     for e in section_ends(row["section"])) if a]}
        if not feature_of(name) and gaz.get("joints") and any(gaz["isj"].in_prefs(j["lat"], j["lng"], prefs)
                                                             for j in gaz["joints"].find(name + "IC")):
            cam["label"] = name + "IC"
        cams.append(cam)
    resolve(cams, gaz)
    countries = WP.load_countries(countries_path)
    items, held = collections.defaultdict(list), collections.defaultdict(list)
    for cam in cams:
        row = cam["row"]
        if cam["source"] == "nexco_east_driveplaza":
            base = nexco_item(row, row.get("observed_at"))
        else:
            base = bureau_item(dict(row, routes=cam.get("routes")), cam["office"], row.get("observed_at"))
        if not cam["_pick"]:
            held[cam["source"]].append({"id": base["id"], "label": cam["label"], "reason": cam["_held"]})
            continue
        item = placed_item(base, cam["_pick"], row.get("observed_at"))
        item["region"] = gaz["isj"].pref_at(item["lat"], item["lng"])
        prefs = cam["prefs"]
        boxes = [gaz["isj"].pref_bbox[p] for p in prefs if p in gaz["isj"].pref_bbox]
        lat0 = sum((b[0] + b[2]) / 2 for b in boxes) / len(boxes)
        lng0 = sum((b[1] + b[3]) / 2 for b in boxes) / len(boxes)
        reach = max(distance_m(lat0, lng0, b[0], b[1]) for b in boxes) / 1000 + 30
        problems = WP.check(item, countries, expected_country="JP", centre=(lat0, lng0), max_km=round(reach))
        if problems:
            held[cam["source"]].append({"id": item["id"], "label": cam["label"], "reason": "sanity check: " + "; ".join(problems)})
            continue
        items[cam["source"]].append(item)
    return {"items": items, "held": held, "unread": unread, "osm_prefs": osm_prefs, "cams": cams}



# ---------------------------------------------------------------- outputs (policies, inputs, report)
PLACEMENT_NOTE = ("No official camera positions are published. Positions are QGlobe placements (identity_confirmed=false): "
                  "an interchange / junction / SA-PA from 国土数値情報 N06-25 (CC BY 4.0), a named bridge, tunnel, pass or rest "
                  "area from OpenStreetMap (ODbL), or the representative point of the named 大字・町丁目 from 位置参照情報 "
                  "(PDL1.0 / 位置参照情報利用約款); each record says which, with its uncertainty.")
SOURCE_NAMES = {
    "mlit_kinki_road_cameras": "MLIT Kinki Regional Development Bureau national-road live cameras (近畿地方整備局 道路ライブカメラ)",
    "mlit_kyushu_road_cameras": "MLIT Kyushu Regional Development Bureau national-highway live cameras (九州地方整備局 道路ライブカメラ)",
    "mlit_tohoku_bureau_terms": "MLIT Tohoku Regional Development Bureau road cameras (東北地方整備局 道路ライブカメラ)",
}
EXTRA_EVIDENCE = [ISJ_PAGE, ISJ_TERMS, N06_PAGE, KSJ_TERMS]


def bureau_policy(source, formats):
    b = BUREAUS[source]
    viewable = "snapshot" in formats
    attribution = (f"出典：国土交通省 {b['site']}（各事務所のライブカメラページURL）を加工して作成。QGlobeが画像を縮小表示し、名称・位置等を"
                   f"正規化・編集しています（国土交通省が作成したものではありません）。位置はQGlobeの推定（国土数値情報・位置参照情報・"
                   f"OpenStreetMap）。Source: {b['en']} website; data normalized and edited by QGlobe, not an MLIT product. PDL1.0.")
    policy = {
        "source": {
            "id": source, "name": SOURCE_NAMES[source], "url": b["url"], "catalog_url": b["url"], "terms_url": b["terms_url"],
            "metadata_license": PDL_NAME, "license": "Public Data License 1.0 (PDL1.0)", "license_url": PDL_URL,
            "media_rights": PDL_RIGHTS,
            "rights_note": (b["rights_clause"] + " Required: 出典 (bureau website + page URL) and an edit notice; must not "
                            "look government-made. " + PLACEMENT_NOTE),
            "attribution": attribution, "rights_status": "official_public_feed" if viewable else "official_page_only",
            "allowed_hosts": list(b["media_hosts"]) if viewable else [], "minimum_refresh_seconds": 600,
            "provider_notice": ("Approximate position placed by QGlobe from the camera's name (see the card); not an official "
                                "camera position."),
            "review_status": "reviewed_for_snapshot_and_reference_use" if viewable else "reviewed_for_external_references_only",
            "reviewed_at": REVIEWED_AT, "evidence": [b["terms_url"], PDL_URL, b["url"], *EXTRA_EVIDENCE],
        },
        "media_hosts": list(b["media_hosts"]) if viewable else [], "page_hosts": list(b["page_hosts"]),
        "formats": sorted(formats), "countries": ["JP"], "operator_hints": [b["bureau"], "国土交通省", "mlit"],
    }
    return policy


def nexco_policy():
    return {
        "source": {
            "id": "nexco_east_driveplaza", "name": "NEXCO East expressway live cameras (ドラぷら)", "url": DRIVEPLAZA,
            "catalog_url": DRIVEPLAZA, "terms_url": "https://www.e-nexco.co.jp/site_info/index.html",
            "metadata_license": "Company copyright (East Nippon Expressway Co.); factual links only",
            "license": "All rights reserved; linking needs no procedure",
            "media_rights": "No images shown: reposting on other sites is not allowed. Official page links only.",
            "rights_note": ("「当サイトに収録されているコンテンツの著作権は、基本的に当社に帰属しています。」「これを他のサイトや印刷媒体に転載したり"
                            "することはできません。」 リンク: 「当サイトは、手続不要です。」「当社のホームページへのリンクと分かるように表示して"
                            "ください。」 " + PLACEMENT_NOTE),
            "attribution": "NEXCO東日本「ドラぷら」高速道路ライブカメラ（https://www.driveplaza.com/traffic/camera/）へのリンク。",
            "rights_status": "official_page_only", "allowed_hosts": [],
            "provider_notice": ("Link to NEXCO East's camera page (images may not be reposted). Approximate position placed by "
                                "QGlobe from the camera's name, not an official camera position."),
            "review_status": "reviewed_for_external_references_only", "reviewed_at": REVIEWED_AT,
            "evidence": ["https://www.e-nexco.co.jp/site_info/index.html", DRIVEPLAZA, *EXTRA_EVIDENCE],
        },
        "media_hosts": [], "page_hosts": ["www.driveplaza.com"], "formats": ["official_page"], "countries": ["JP"],
        "operator_hints": ["NEXCO東日本", "東日本高速道路"], "official_map_url": DRIVEPLAZA,
    }


def kanto_policy(current):
    """mlit_kanto_cctv, started from its current fragment: attribution and note cover the offices added here."""
    policy = json.loads(json.dumps(current))
    src = policy["source"]
    src["attribution"] = ("出典：関東地方整備局ウェブサイト（利根川上流河川事務所・北首都国道事務所・宇都宮国道事務所・高崎河川国道事務所・"
                          "大宮国道事務所の各ライブカメラページURL）を加工して作成。QGlobeが名称・位置等のデータを正規化・編集し、画像を縮小"
                          "表示しています（国土交通省が作成したものではありません）。位置の一部はQGlobeの推定（位置参照情報・国土数値情報・"
                          "OpenStreetMap）。Source: MLIT Kanto Regional Development Bureau website; data normalized and edited by "
                          "QGlobe, not an MLIT product. PDL1.0.")
    src["rights_note"] = (src.get("rights_note", "") + " Placement round 2026-11-14: cameras of the Utsunomiya, Takasaki and "
                          "Omiya national-road offices added with QGlobe placements (" + PLACEMENT_NOTE + ")")
    for url in EXTRA_EVIDENCE:
        if url not in src["evidence"]:
            src["evidence"].append(url)
    src["reviewed_at"] = REVIEWED_AT
    return policy


def held_policy(source_id, name, url, reason, until, evidence):
    return {source_id: {"status": "held", "held_reason": reason, "held_until": until, "evidence": evidence,
                        "source": {"id": source_id, "name": name, "url": url}, "reviewed_at": REVIEWED_AT,
                        "countries": ["JP"]}}


STILL_HELD = {
    **held_policy("mlit_hokuriku_road_cameras", "MLIT Hokuriku Regional Development Bureau road cameras",
                  "https://www.hrr.mlit.go.jp/kanazawa/douro/michinavi/",
                  "PDL1.0 verified, but no bureau page lists the cameras in a readable form: top/live.html carries no list, "
                  "the Toyama office page now forwards to the prefecture's winter-road site, the Ishikawa みちナビ (MLIT "
                  "Kanazawa office) loads its cameras by script (text mode lists owners only), and the Niigata list is on "
                  "the prefectural portal (no terms). Nothing to place.",
                  "A camera list on an MLIT host (names + stills); then placement as for the other bureaus.",
                  ["https://www.hrr.mlit.go.jp/help.html", "https://www.hrr.mlit.go.jp/top/live.html",
                   "https://www.hrr.mlit.go.jp/kanazawa/douro/michinavi/text.html"]),
    **held_policy("mlit_hokkaido_road_info", "MLIT Hokkaido Regional Development Bureau road information cameras",
                  "https://info-road.hdb.hkd.mlit.go.jp/",
                  "Re-checked 2026-11-14 (placement round): the site still answers every scripted request, robots.txt "
                  "included, with the F5 'Request Rejected' page; terms not read; no bypass attempted.",
                  "A human reads the terms and finds a camera list reachable without the block.", []),
    **held_policy("mlit_other_bureaus_road_cameras", "MLIT Chubu, Chugoku and Shikoku bureau road cameras",
                  "https://www.mlit.go.jp/road/bosai/LIVEcamera.html",
                  "Shikoku (PDL1.0 verified): MLIT's national list links only the road-info-prvs system for the Shikoku "
                  "bureau (no stable endpoint, held as mlit_road_info_prvs); no office camera page found. Chubu and "
                  "Chugoku: terms not read (out of this round's scope).",
                  "Shikoku office camera pages on skr.mlit.go.jp, or a stable road-info-prvs list; Chubu/Chugoku terms.",
                  ["https://www.skr.mlit.go.jp/manual.html", "https://www.mlit.go.jp/road/bosai/LIVEcamera.html"]),
}
OFFICES_NOT_PLACED = [
    ("mlit_kinki_road_cameras", "福井河川国道事務所", "www.fukui.kkr.mlit.go.jp answered HTTP 403 (not retried)"),
    ("mlit_kinki_road_cameras", "和歌山河川国道事務所", "10 stills on an image map without names: nothing to place"),
    ("mlit_kyushu_road_cameras", "長崎・熊本・佐伯・大分・宮崎・延岡・大隅", "camera lists loaded by script or split over sub-area "
     "pages not read this round (Saiki: numbered icons without names)"),
    ("mlit_tohoku_bureau_terms", "岩手・湯沢・秋田・能代・仙台・福島・磐城", "not parsed this round: mixed image hosts (www.thr / "
     "www2.thr / akita) and frame or route sub-pages; Fukushima page 404; pdasv1.thr.mlit.go.jp robots.txt unreachable"),
    ("mlit_tohoku_bureau_terms", "三陸国道・郡山国道", "page links only: stills on www.thr.mlit.go.jp / roadcctv.thr.mlit.go.jp "
     "were not HTTPS-checked (one check per provider)"),
    ("mlit_kanto_cctv", "霞ヶ浦・荒川上流・荒川下流・渡良瀬川・利根川水系砂防・相模川水系ダム", "river and dam offices: the same "
     "offices' cameras are japan_mlit_rivers records with official positions (river.go.jp), not duplicated as placements"),
    ("mlit_kanto_cctv", "常陸河川国道・相武国道・長野国道", "Hitachi: list built by script; Sobu: sections 'A～B' only; Nagano: "
     "romanized camera ids without names on the map page"),
]


def median(values):
    v = sorted(values)
    return v[len(v) // 2] if v else None


def write_outputs(out, result, checks=None):
    out = Path(out)
    report = {"family": FAMILY, "generated_at": F.now(), "sources": [], "held": [], "hosts_refused": [],
              "gazetteers": {"isj": {"version": ISJ_VERSION, "url": ISJ_URL, "terms": ISJ_TERMS, "licence": ISJ_LICENCE},
                             "n06": {"url": N06_URL, "page": N06_PAGE, "licence": N06_LICENCE},
                             "osm": {"endpoint": "https://overpass.kumi.systems/api/interpreter",
                                     "prefectures_with_cached_answer": result["osm_prefs"]}},
              "offices_not_placed": [{"source": s, "office": o, "reason": r} for s, o, r in OFFICES_NOT_PLACED]}
    policies = {}
    for source in ("mlit_kinki_road_cameras", "mlit_kyushu_road_cameras", "mlit_tohoku_bureau_terms",
                   "nexco_east_driveplaza", "mlit_kanto_cctv"):
        items = sorted(result["items"].get(source, []), key=lambda x: x["id"])
        held = result["held"].get(source, [])
        if source == "mlit_kanto_cctv":
            # The round-2 Kanto document is the base. Two inputs superseding mlit_kanto_cctv would stop the
            # build, so once the places document is written the base moves to unused/ (where re-runs find it).
            base = out / "mlit_kanto_cctv_tonejo_note.json"
            retired = out / "unused" / "mlit_kanto_cctv_tonejo_note.superseded-by-places.json.txt"
            base_doc = json.loads((base if base.exists() else retired).read_text(encoding="utf-8"))
            existing = base_doc["items"]
            ids = {x["id"] for x in existing}
            added = [x for x in items if x["id"] not in ids]
            F.write_catalog(out / "mlit_kanto_cctv_places.json", ["mlit_kanto_cctv"], existing + added,
                            supersedes=["mlit_kanto_cctv"])
            if base.exists():
                retired.parent.mkdir(parents=True, exist_ok=True)
                base.replace(retired)
            import collect_japan  # round-1 collector: its mlit_kanto_cctv policy is the starting point (idempotent)
            policies[source] = kanto_policy(collect_japan.POLICIES["mlit_kanto_cctv"])
            input_file, items = "mlit_kanto_cctv_places.json", added
        elif items:
            F.write_catalog(out / f"{source}.json", [source], items)
            input_file = f"{source}.json"
            policies[source] = nexco_policy() if source == "nexco_east_driveplaza" else \
                bureau_policy(source, {x["format"] for x in items})
        else:
            input_file = None
        roles = collections.defaultdict(list)
        for x in items:
            roles[x["coordinate_role"] + ("/" + x["coordinate_source"].split(":")[0])].append(x["coordinate_uncertainty_m"])
        reasons = collections.Counter(re.sub(r"'[^']*'", "'…'", h["reason"]) for h in held)
        report["sources"].append({
            "id": source, "country": "JP", "input_file": input_file,
            "supersedes": ["mlit_kanto_cctv"] if source == "mlit_kanto_cctv" else [],
            "records": {"viewable": sum(x["format"] == "snapshot" for x in items),
                        "page_only": sum(x["format"] == "official_page" for x in items)},
            "placed_by_role": {k: {"records": len(v), "median_uncertainty_m": median(v), "max_uncertainty_m": max(v)}
                               for k, v in sorted(roles.items())},
            "listed_cameras": len(items) + len(held), "held_cameras": len(held),
            "held_reasons": dict(reasons.most_common()), "held_examples": held[:12],
            "sample_check": (checks or {}).get(source)})
    for pid, policy in {**policies, **STILL_HELD}.items():
        (out / "policies").mkdir(parents=True, exist_ok=True)
        (out / "policies" / f"{pid}.json").write_text(json.dumps({pid: policy}, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    report["held"] = [{"id": k, "reason": v["held_reason"]} for k, v in STILL_HELD.items()]
    refused = out / "raw" / "places" / "places_japan" / "acquire_refused.json"
    report["hosts_refused"] = json.loads(refused.read_text(encoding="utf-8")) if refused.exists() else []
    report["hosts_refused"] += [{"source": "mlit_kinki_road_cameras", "host": "www.fukui.kkr.mlit.go.jp",
                                 "reason": "HTTP 403 (exploration, 2026-11-14)"},
                                {"source": "mlit_hokkaido_road_info", "host": "info-road.hdb.hkd.mlit.go.jp",
                                 "reason": "F5 'Request Rejected' page for / and /robots.txt"},
                                {"source": "mlit_tohoku_bureau_terms", "host": "pdasv1.thr.mlit.go.jp",
                                 "reason": "robots.txt unreachable (treated as disallow)"}]
    if not checks:
        report["image_checks"] = ("Not run in this collection: the coordinator stopped all further network requests. "
                                  "One 64 KiB check per viewable provider is still owed (step 'check'): Kinki "
                                  "www.seishiga.kkr.mlit.go.jp, Kyushu www.qsr.mlit.go.jp, Tohoku www2.thr.mlit.go.jp "
                                  "(stills embedded as http:// on the pages; HTTPS assumed from the research), Kanto "
                                  "www.ktr.mlit.go.jp (checked in round 1).")
    status = out / "raw" / "places" / "places_japan" / "overpass_status.json"
    if status.exists():
        report["gazetteers"]["osm"]["last_run"] = json.loads(status.read_text(encoding="utf-8"))
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / f"{FAMILY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def run_checks(out, result, client=None):
    """One 64 KiB image check per viewable provider with new records (first by id)."""
    client = client or F.PoliteClient(delay=1.2)
    results = {}
    for source, items in sorted(result["items"].items()):
        snaps = sorted((x for x in items if x["format"] == "snapshot"), key=lambda x: x["id"])
        if not snaps:
            continue
        first = snaps[0]
        hosts = BUREAUS[source]["media_hosts"]
        event = client.check_image(first["snapshot_url"], source, first["id"], hosts)
        name = "mlit_kanto_cctv.places" if source == "mlit_kanto_cctv" else source
        (Path(out) / "checks").mkdir(parents=True, exist_ok=True)
        (Path(out) / "checks" / f"{name}.snapshot.json").write_text(json.dumps([event], ensure_ascii=False, indent=1),
                                                                     encoding="utf-8")
        results[source] = {k: event.get(k) for k in ("record_id", "url", "status", "http_status", "signature",
                                                      "content_type", "bytes_read", "inconclusive_reason")}
    path = Path(out) / "reports" / f"{FAMILY}.checks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--countries", type=Path, help="Natural Earth 10m countries GeoJSON")
    ap.add_argument("--catalog", type=Path, help="current data/webcams.json (overlap report only)")
    ap.add_argument("step", choices=["acquire", "osm", "check", "build"])
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out = args.out
    log = out / "progress" / f"{FAMILY}_{args.step}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if args.step == "acquire":
        a = Acquirer(out)
        acquire_lists(a)
        acquire_gazetteers(a)
        (out / "raw" / "places" / "places_japan").mkdir(parents=True, exist_ok=True)
        (out / "raw" / "places" / "places_japan" / "acquire_refused.json").write_text(
            json.dumps(a.refused, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(a.refused, ensure_ascii=False, indent=1))
    elif args.step == "osm":
        a = Acquirer(out, F.PoliteClient(delay=1.2, timeout=360))
        status = acquire_osm(a, out, load_gazetteers(out)["isj"])
        (out / "raw" / "places" / "places_japan" / "overpass_status.json").write_text(
            json.dumps({"checked_at": F.now(), "prefectures": status}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(status, ensure_ascii=False))
    elif args.step in ("build", "check"):
        if not args.countries:
            ap.error("--countries is required for build/check")
        result = build(out, args.countries, args.catalog)
        checks = None
        if args.step == "check":
            checks = run_checks(out, result)
        elif (out / "reports" / f"{FAMILY}.checks.json").exists():
            checks = json.loads((out / "reports" / f"{FAMILY}.checks.json").read_text(encoding="utf-8"))
        report = write_outputs(out, result, checks)
        print(json.dumps({s["id"]: [s["records"], s["held_cameras"]] for s in report["sources"]}, ensure_ascii=False))
    (out / "progress" / f"{FAMILY}_{args.step}.done").write_text(F.now(), encoding="utf-8")


if __name__ == "__main__":
    main()
