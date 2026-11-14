#!/usr/bin/env python3
"""Build the public webcam companion catalog; never relabel OSM cameras as live.

Python 3.10+, standard library only. The default is an offline reproducible build.
--fetch downloads the 12 documented Caltrans metadata catalogs, not any video.
Health evidence must come from explicit probes, not the provider's inService flag.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
import warnings
from urllib.parse import unquote_plus, urlsplit, urlunsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

try:  # CLI execution and repository-root unittest imports use different paths.
    from snapshot_access import apply_snapshot_access_checks
except ModuleNotFoundError:
    from scripts.snapshot_access import apply_snapshot_access_checks

CALTRANS_DOCS = "https://cwwp2.dot.ca.gov/documentation/cctv/cctv.htm"
SOURCE = {
    "id": "caltrans", "name": "California Department of Transportation",
    "url": CALTRANS_DOCS, "terms_url": "https://dot.ca.gov/conditions-of-use",
    "attribution": "Traffic cameras: Caltrans. No endorsement by Caltrans.",
    "rights_status": "official_public_feed",
    "metadata_license": "Caltrans CWWP2 / Conditions of Use",
    "media_rights": "Official published camera feed; Caltrans terms and any third-party rights apply. No footage redistribution.",
    "rights_note": "CWWP2 expressly provides these metadata for application integration at no charge. "
                   "Caltrans Conditions of Use apply; third-party works may have separate rights. "
                   "This catalog does not archive or redistribute footage.",
}
ALLOWED_HOSTS = {"cwwp2.dot.ca.gov", "wzmedia.dot.ca.gov"}
VEGVESEN_SOURCE = {
    "id": "vegvesen", "name": "Statens vegvesen — Norway road cameras",
    "url": "https://dataut.vegvesen.no/dataset/webkamera",
    "terms_url": "https://data.norge.no/nlod/en/2.0", "license": "NLOD-2.0",
    "metadata_license": "NLOD-2.0", "media_rights": "Official NLOD webcam publication; preserve attribution and source terms.",
    "attribution": "Contains data under the Norwegian licence for Open Government data (NLOD) "
                   "distributed by Statens vegvesen. Metadata normalized by QGlobe.",
    "rights_status": "official_public_feed",
    "rights_note": "The official webcam publication is marked NLOD. Keep attribution and licence links visible. "
                   "No endorsement by Statens vegvesen is claimed; this catalog does not archive footage.",
    "catalog_url": "https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:CctvSimple/items?f=application%2Fgeo%2Bjson&limit=2000",
    "documentation": "https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/raw/3.1/NPRA_DATEXII_3_1_Specification_WFS-WMS_v1.1.pdf?at=04bd661aa183d8850153a7b547d93a705c233992",
}
# Adding an input file cannot approve a provider, media host, or rights claim.
# Each adapter must be reviewed and added here before --extra-catalog can use it.
PROVIDER_POLICIES = {
    "caltrans": {"source": SOURCE, "media_hosts": ALLOWED_HOSTS,
                 "operator_hints": ("caltrans", "california department of transportation")},
    "vegvesen": {"source": VEGVESEN_SOURCE,
                 "media_hosts": {"kamera.vegvesen.no", "kamera.atlas.vegvesen.no"},
                 "operator_hints": ("vegvesen", "norwegian public roads administration")},
}
EXTRA_CATALOG_PROVIDERS = {"vegvesen"}
# This reviewed registry is repository code, never a path supplied by a catalog.
# Metadata publication and permission to load media are independent decisions.
WORLD_POLICY_PATH = Path(__file__).with_name("webcam_source_policies.json")
if WORLD_POLICY_PATH.exists():
    for _provider, _policy in json.loads(WORLD_POLICY_PATH.read_text(encoding="utf-8")).items():
        if _provider in PROVIDER_POLICIES:
            raise ValueError("World policy cannot override an existing approved adapter")
        _policy["media_hosts"] = set(_policy.get("media_hosts", []))
        PROVIDER_POLICIES[_provider] = _policy
        EXTRA_CATALOG_PROVIDERS.add(_provider)
INCOMPLETE_PROBE_STATUSES = {"budget_exhausted", "stopped", "interrupted"}
OSM_ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0; https://www.openstreetmap.org/copyright"

# Privacy filter. Whatever its source, a published URL never carries a login in its query
# (or fragment), never names a home dynamic-DNS host, and, for community-sourced records
# (OpenStreetMap, Wikidata), never points at a camera's own device endpoint: those are
# somebody's camera or home connection, listed by a third party. js/webcams.mjs applies
# the same rules (privateUrlReason); tests/webcam_privacy_vectors.json holds the cases both
# must agree on. Nothing here makes a request.
CREDENTIAL_QUERY_KEYS = frozenset({
    "user", "usr", "username", "user_name", "login", "pass", "pwd", "password", "passwd", "passwort",
    "loginuse", "loginpas", "auth", "token", "key", "apikey", "api_key", "access_token", "auth_token"})
# Public APIs that need one of those keys, as {host: frozenset(keys)}: only a key the operator
# publishes for anonymous use, with its reason next to it. Every approved input was checked on
# 2026-11-14; this is the only one.
PUBLIC_QUERY_KEY_ALLOWLIST = {
    # QLDTraffic Website API v1.10, section 2.1.1.1, prints this anonymous shared public key
    # (shared limit of 100 requests a minute). Catalog provenance only, never a media URL.
    "api.qldtraffic.qld.gov.au": frozenset({"apikey"}),
}
# Dynamic-DNS names given to home routers, NAS boxes and camera recorders. Whole-label suffixes.
DYNAMIC_DNS_SUFFIXES = frozenset({
    "myfritz.net",  # AVM FRITZ!Box
    "ddns.net", "hopto.org", "zapto.org", "sytes.net", "servehttp.com", "serveftp.com", "servebeer.com",
    "myftp.org", "myftp.biz", "redirectme.net", "bounceme.net", "webhop.me", "ddnsking.com", "3utilities.com",
    "gotdns.ch", "myvnc.com",  # No-IP
    "dyndns.org", "homeip.net", "dnsalias.com", "dnsalias.net", "dnsalias.org", "dynalias.com", "dynalias.net",
    "dynalias.org", "homelinux.com", "homelinux.net", "homelinux.org", "is-a-geek.com", "is-a-geek.net",
    "is-a-geek.org", "selfip.com", "selfip.net", "selfip.org", "gotdns.com", "gotdns.org", "mine.nu",  # Dyn
    "duckdns.org", "dynv6.net", "mooo.com", "dy.fi",
    "dynu.net", "ddnsfree.com", "mywire.org", "kozow.com", "ooguy.com", "accesscam.org", "camdvr.org",
    "casacam.net", "giize.com", "gleeze.com", "loseyourip.com", "webredirect.org", "ddnsgeek.com",  # Dynu
    "synology.me", "myds.me", "diskstation.me", "i234.me", "dscloud.biz", "dscloud.me", "dscloud.mobi",
    "familyds.com", "familyds.net", "familyds.org",  # Synology
    "myqnapcloud.com", "asuscomm.com", "tplinkdns.com", "mynetgear.com", "dlinkddns.com",  # NAS, routers
    "viewnetcam.com", "miemasu.net",  # Panasonic network cameras
    "spdns.de", "spdns.eu", "spdns.org", "goip.de", "dynvpn.de", "selfhost.de", "selfhost.eu", "selfhost.bz",
    "dnshome.de", "feste-ip.net"})
# Any TLD: dyndns.*, no-ip.*, noip.*, freeddns.*, ddns.*, ddnss.*; and Dyn's dyndns-*.com.
DYNAMIC_DNS_PATTERN = re.compile(
    r"(?:^|\.)(?:(?:dyndns|no-ip|noip|freeddns|ddns|ddnss|dyn-dns|dynamic-dns)\.[a-z]{2,}(?:\.[a-z]{2})?|dyndns-[a-z]+\.com)$")
# Device endpoints of IP cameras and recorders (Axis, Mobotix, ZoneMinder, Panasonic, Sony,
# Hikvision, Foscam/Instar, generic CGI), matched on the lower-case path.
DEVICE_PATH_PATTERN = re.compile(
    r"/axis-cgi/|/axis-media/|/cgi-bin/|nph-zms|/getdata\.cgi|/record/current\.jpe?g|/mjpg/"
    r"|/(?:snapshot|video|videostream|getimage|image|snap)\.cgi|/view/(?:view|index|viewer_index)\.shtml"
    r"|/jpg/image\.jpe?g|faststream\.jpe?g|nphmotionjpeg|snapshotjpeg|/cgistart|oneshotimage"
    r"|/isapi/|/streaming/channels|/tmpfs/|webcapture\.jpe?g|/onvif")
# A bare image.jpg is a device snapshot when it sits at the host root or takes a query.
DEVICE_IMAGE_PATTERN = re.compile(r"/image\.jpe?g$")
PRIVACY_RULES = {
    "credential_query": "query or fragment key among " + ", ".join(sorted(CREDENTIAL_QUERY_KEYS))
                        + " (case-insensitive; a published public-API key may be allow-listed per host)",
    "dynamic_dns_host": "host under a home dynamic-DNS service (DYNAMIC_DNS_SUFFIXES and DYNAMIC_DNS_PATTERN "
                        "in scripts/build_webcams.py)",
    "device_path": "OpenStreetMap/Wikidata record pointing at a camera device endpoint (axis-cgi, cgi-bin, nph-zms, "
                   "GetData.cgi, /record/current.jpg, mjpg/, snapshot.cgi, video.cgi, image.jpg?..., ...), "
                   "also when the endpoint or a camera IP address is embedded in the link's query",
    "nested_urls": "a URL carried in a query value is checked by the same rules",
}
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.I)


class PrivacyFiltered(ValueError):
    """A record whose own link would publish a private camera; the reason never includes the URL."""
    def __init__(self, reason, field):
        super().__init__(f"Privacy filter: {reason} in {field}")
        self.reason, self.field = reason, field


def dynamic_dns_host(host):
    host = (host or "").lower().rstrip(".")
    labels = host.split(".")
    return any(".".join(labels[i:]) in DYNAMIC_DNS_SUFFIXES for i in range(len(labels))) or bool(DYNAMIC_DNS_PATTERN.search(host))


def device_path(path, query=""):
    path = (path or "").lower()
    return bool(DEVICE_PATH_PATTERN.search(path)) or bool(
        DEVICE_IMAGE_PATTERN.search(path) and (query or path.count("/") == 1))


def ip_literal(host):
    try:
        ipaddress.ip_address((host or "").strip("[]"))
        return True
    except ValueError:
        return False


def private_url_reason(value, *, community=False, check_query=True, _depth=0):
    """Why a URL must not be published (credential_query, dynamic_dns_host, device_path), or None.

    check_query=False only for URLs a provider's own manifest names (their session tokens
    are the provider's, not published by this catalog).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        u = urlsplit(value.strip())
        host = (u.hostname or "").lower().rstrip(".")
    except ValueError:
        return None  # Malformed URLs are rejected by canonical_url on their own.
    allowed = PUBLIC_QUERY_KEY_ALLOWLIST.get(host, frozenset())
    nested = []
    for part in (u.query, u.fragment):
        for piece in re.split(r"[&;]", part):
            key, _, raw = piece.partition("=")
            key = unquote_plus(key).strip().lower()
            if check_query and key in CREDENTIAL_QUERY_KEYS and key not in allowed:
                return "credential_query"
            inner = unquote_plus(raw)
            if "://" in inner:
                nested.append(inner)
    if dynamic_dns_host(host):
        return "dynamic_dns_host"
    if community and device_path(u.path, u.query):
        return "device_path"
    for inner in nested if _depth < 2 else ():
        reason = private_url_reason(inner, community=community, check_query=check_query, _depth=_depth + 1)
        if reason:
            return reason
        try:
            if community and ip_literal(urlsplit(inner).hostname):
                return "device_path"  # A community link carrying a camera's IP address.
        except ValueError:
            pass
    return None


# Legal and safety exclusions: a reviewed, versioned rule list (reason and evidence per rule),
# applied at every build so offline rebuilds keep those records out.
EXCLUSIONS_PATH = Path(__file__).with_name("webcam_exclusions.json")
EXCLUSION_ACTIONS = ("remove_record", "image_page_to_reference", "media_page_to_reference")
# A page is never a stream or a media file: playlists, manifests, segments, images, clips.
MEDIA_EXTENSIONS = (".m3u8", ".m3u", ".mpd", ".ts", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
                    ".mjpg", ".mjpeg", ".mp4", ".m4v", ".webm", ".mov", ".flv")
MEDIA_REPORTED_FORMATS = frozenset({"hls", "dash", "mjpeg", "mp4", "jpeg", "jpg", "image", "snapshot", "rtsp"})
# Image endpoints without a file extension, found given as pages (round-2 research): Land Oberösterreich
# /webcam/a/{id}/KAM{n}, ŘSD CameraImage.ashx, RMI getWebcamImage.php, HAK cam.asp.
MEDIA_PATH_PATTERN = re.compile(r"/webcam/a/[^/]+/kam\d+$|/cameraimage\.ashx$|/getwebcamimage\.php$|/cam\.asp$")


def media_url(value, row=None):
    """A stream or media file by its path, or a URL its own row reports as media (reported_media_format)."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        path = urlsplit(value.strip()).path.lower()
    except ValueError:
        return False
    if path.endswith(MEDIA_EXTENSIONS) or MEDIA_PATH_PATTERN.search(path):
        return True
    return bool(row) and str(row.get("reported_media_format") or "").lower() in MEDIA_REPORTED_FORMATS and value in (
        row.get("reference_url"), row.get("stream_url"), row.get("snapshot_url"))


def media_reference_field(value, row):
    path = urlsplit(value).path.lower()
    if path.endswith((".m3u8", ".m3u")) or str(row.get("reported_media_format") or "").lower() == "hls":
        return "reference_hls_url"
    if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
        return "reference_snapshot_url"
    if path.endswith((".mp4", ".m4v", ".webm", ".mov", ".flv")):
        return "reported_clip_url"
    return "reference_url"


def media_page_records(items):
    """(id, field) of every record whose page or source page is still a media URL: the build stops on any."""
    return [(x["id"], f) for x in items for f in ("official_page", "source_page") if media_url(x.get(f), x)]


def load_exclusions(path=EXCLUSIONS_PATH, policies=None):
    """Read and check the rule list; every policy marked excluded must be covered by a provider rule."""
    if not Path(path).exists():
        return {"version": None, "sha256": None, "rules": []}
    body = Path(path).read_bytes()
    doc = json.loads(body)
    rules, seen = doc.get("rules"), set()
    if not isinstance(rules, list):
        raise ValueError("Exclusion file needs a rules list")
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("id") in seen or not re.fullmatch(r"[a-z0-9-]{3,60}", str(rule.get("id"))):
            raise ValueError(f"Exclusion rule id missing or repeated: {rule!r}"[:200])
        seen.add(rule["id"])
        if rule.get("action") not in EXCLUSION_ACTIONS or not isinstance(rule.get("match"), dict):
            raise ValueError(f"Exclusion rule {rule['id']}: unknown action or match")
        if not str(rule.get("reason", "")).strip() or not rule.get("evidence"):
            raise ValueError(f"Exclusion rule {rule['id']} needs a reason and evidence")
        for area in rule["match"].get("areas", []):
            if len(area.get("ring", [])) < 3 or not area.get("countries"):
                raise ValueError(f"Exclusion rule {rule['id']}: an area needs countries and a ring")
        if rule["action"] == "image_page_to_reference":
            rule["_pattern"] = re.compile(rule["match"]["url_pattern"])
    covered = {p for rule in rules if rule["action"] == "remove_record" for p in rule["match"].get("providers", [])}
    for provider, policy in (policies if policies is not None else PROVIDER_POLICIES).items():
        if policy.get("status") == "excluded" and provider not in covered:
            raise ValueError(f"Policy {provider} is marked excluded but no exclusion rule removes it")
    return {"version": doc.get("version"), "sha256": hashlib.sha256(body.replace(b"\r\n", b"\n")).hexdigest(), "rules": rules}


def host_under(host, domains):
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def inside_ring(lat, lng, ring):
    """Even-odd test on a [lng, lat] ring."""
    hit = False
    x0, y0 = ring[-1]
    for x1, y1 in ring:
        if (y1 > lat) != (y0 > lat) and lng < (x0 - x1) * (lat - y1) / (y0 - y1) + x1:
            hit = not hit
        x0, y0 = x1, y1
    return hit


def record_hosts(value):
    """Hosts of every URL in a record's strings (pages, references, media, provenance)."""
    if isinstance(value, str):
        hosts = set()
        for url in URL_IN_TEXT.findall(value):
            try:
                hosts.add((urlsplit(url).hostname or "").lower())
            except ValueError:
                pass
        return hosts
    if isinstance(value, dict):
        return set().union(*(record_hosts(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(record_hosts(v) for v in value)) if value else set()
    return set()


def exclusion_rule(item, rules):
    """The first remove_record rule matching a normalized record, or None."""
    for rule in rules:
        if rule["action"] != "remove_record":
            continue
        match = rule["match"]
        hit = item.get("provider") in match.get("providers", ()) or item.get("country") in match.get("countries", ())
        if not hit and match.get("hosts"):
            hit = any(host_under(h, match["hosts"]) for h in record_hosts(item))
        if not hit:
            hit = any(("*" in area["countries"] or item.get("country") in area["countries"])
                      and inside_ring(item["lat"], item["lng"], area["ring"]) for area in match.get("areas", ()))
        if hit and rule.get("keep_hosts"):
            own = item.get("official_page") or primary_url(item) or ""
            if host_under(urlsplit(own).hostname, rule["keep_hosts"]):
                hit = False
        if hit:
            return rule
    return None


def apply_exclusions(items, rules):
    kept, log = [], []
    for item in items:
        rule = exclusion_rule(item, rules)
        if rule:
            log.append({"id": item["id"], "provider": item["provider"], "country": item.get("country"),
                        "rule": rule["id"], "action": "record_removed"})
        else:
            kept.append(item)
    return kept, log


def repair_raw(raw, rules, log=None):
    """Input-level repairs, before normalization (an image given as the page becomes an image reference)."""
    if not isinstance(raw, dict):
        return raw
    for rule in rules:
        if rule["action"] == "media_page_to_reference":
            raw = repair_media_page(raw, rule, log)
            continue
        if rule["action"] != "image_page_to_reference":
            continue
        field = rule["match"]["field"]
        value = raw.get(field)
        if not isinstance(value, str) or not rule["_pattern"].fullmatch(value.strip()) or private_url_reason(value):
            continue
        raw = dict(raw)
        raw[field] = None
        if value not in {raw.get(f) for f in REFERENCE_FIELDS}:
            raw["reference_snapshot_url"] = value
        if log is not None:
            log.append({"id": raw.get("id") or f"{raw.get('provider')}:{raw.get('provider_id')}", "provider": raw.get("provider"),
                        "rule": rule["id"], "action": "image_moved_to_reference", "field": field})
    return raw


def repair_media_page(raw, rule, log=None):
    """A stream or media URL given as the page becomes a reference of its kind (never enabled media);
    the page becomes the operator's camera map from the policy, else the record's source page."""
    moved = False
    community = community_source(raw.get("provider"))
    for field in rule["match"].get("fields", ["official_page"]):
        value = raw.get(field)
        # A private link is left where it is, so the privacy filter removes the whole record.
        if not media_url(value, raw) or private_url_reason(value, community=community):
            continue
        raw, moved = dict(raw), True
        raw[field] = None
        action = "media_page_cleared"
        if value not in {raw.get(f) for f in (*REFERENCE_FIELDS, "stream_url", "snapshot_url")}:
            target = media_reference_field(value, raw)
            target = target if not raw.get(target) else "reference_url" if not raw.get("reference_url") else None
            if target:
                raw[target], action = value, "media_moved_to_reference"
        if log is not None:
            log.append({"id": raw.get("id") or f"{raw.get('provider')}:{raw.get('provider_id')}", "provider": raw.get("provider"),
                        "rule": rule["id"], "action": action, "field": field})
    if moved and not raw.get("official_page") and not raw.get("webcam_page"):
        page = PROVIDER_POLICIES.get(raw.get("provider"), {}).get("official_map_url")
        if page:
            raw["official_page"] = page
    return raw


# Duplicates. A community link (OSM, Wikidata) adds nothing when an official record within the matching
# radius already carries every link it has (same page, so same operator site). And for the reviewed provider
# pairs below, the first provider's record of a camera gives way to the second provider's viewable record of the
# same camera when the names match; its page then stays on the viewable record as a reference.
SAME_CAMERA_PAGE_PAIRS = {
    # MLIT Kanto Regional Development Bureau cameras (Tone upstream river office) are also listed, as pages, on
    # MLIT's national river-information site (www.river.go.jp, provider japan_mlit_rivers).
    ("japan_mlit_rivers", "mlit_kanto_cctv"): "same MLIT camera listed on www.river.go.jp",
}
GENERIC_NAME_WORDS = ("水位", "ライブカメラ", "カメラ", "観測所", "CCTV")


CACHE_BUSTER = re.compile(r"^(?:\d{6,}|(?:v|t|ts|_|time|timestamp)=\d+)$")


def link_key(url):
    """A URL for comparison: host case, trailing slash and a bare cache-buster query do not count."""
    u = urlsplit(url)
    query = "" if CACHE_BUSTER.match(u.query or "") else u.query
    return (u.hostname or "").lower() + u.path.rstrip("/") + ("?" + query if query else "")


def record_links(item, provenance=False):
    fields = ("official_page", "stream_url", "snapshot_url", *REFERENCE_FIELDS)
    urls = [item.get(f) for f in fields] + ([item.get("source_page")] if provenance else [])
    return {link_key(u) for u in urls if isinstance(u, str) and u}


def name_tokens(name):
    text = re.sub(r"\(.*?\)", " ", unicodedata.normalize("NFKC", str(name or "")))
    for word in GENERIC_NAME_WORDS:
        text = text.replace(word, " ")
    return [t for t in re.split(r"[\s・,/\-]+", text) if len(t) >= 2]


def same_name(a, b):
    na, nb = unicodedata.normalize("NFKC", str(a or "")), unicodedata.normalize("NFKC", str(b or ""))
    return any(t in nb for t in name_tokens(a)) or any(t in na for t in name_tokens(b))


def drop_duplicates(items, radius):
    """Remove the two kinds of duplicate above; returns kept items and one log entry per removed record."""
    community = {x["id"] for x in items if community_source(x.get("provider"))}
    grid = collections.defaultdict(list)
    for x in items:
        if x["id"] not in community:
            grid[(round(x["lat"], 2), round(x["lng"], 2))].append(x)

    def near(x):
        cells = {(round(x["lat"] + dy, 2), round(x["lng"] + dx, 2)) for dy in (-.01, 0, .01) for dx in (-.01, 0, .01)}
        found = [(distance_m(x["lat"], x["lng"], o["lat"], o["lng"]), o) for c in cells for o in grid.get(c, []) if o is not x]
        return sorted(((d, o) for d, o in found if d <= radius), key=lambda pair: (pair[0], pair[1]["id"]))

    gone, log = set(), []
    firsts = {a for a, _ in SAME_CAMERA_PAGE_PAIRS}
    for x in sorted(items, key=lambda i: i["id"]):  # same camera from a reviewed provider pair -> the viewable record
        if x["id"] in community or x["provider"] not in firsts:
            continue
        for d, v in near(x):
            if (x["provider"], v["provider"]) in SAME_CAMERA_PAGE_PAIRS and v["format"] in ("hls", "snapshot") \
                    and v["id"] not in gone and same_name(x["name"], v["name"]):
                if v.get("reference_url") not in (None, x["official_page"]):
                    break  # nowhere to keep its page: keep the record (uncertain)
                v["reference_url"] = x["official_page"]
                gone.add(x["id"])
                log.append({"id": x["id"], "provider": x["provider"], "superseded_by": v["id"], "distance_m": round(d, 1),
                            "rule": "page-duplicate-of-viewable", "note": SAME_CAMERA_PAGE_PAIRS[(x["provider"], v["provider"])]})
                break
    for x in sorted(items, key=lambda i: i["id"]):  # community link -> official record with every one of its links
        if x["id"] not in community:
            continue
        own = record_links(x) - ({link_key(x["source_page"])} if x.get("source_page") else set())
        for d, o in near(x):
            if o["id"] not in gone and own and own <= record_links(o, provenance=True):
                gone.add(x["id"])
                log.append({"id": x["id"], "provider": x["provider"], "superseded_by": o["id"], "distance_m": round(d, 1),
                            "rule": "community-duplicate-of-official"})
                break
    return [x for x in items if x["id"] not in gone], log


def duplicate_summary(log, radius):
    return {"radius_m": radius, "records_removed": len(log),
            "by_rule": dict(sorted(collections.Counter(e["rule"] for e in log).items())),
            "by_provider_and_official_source": dict(sorted(collections.Counter(
                f"{e['provider']} -> {e['superseded_by'].split(':', 1)[0]}" for e in log).items())),
            "note": "A community record goes only when an official record within the radius carries every one of its "
                    "links; page-only official records go only for reviewed same-operator provider pairs with matching "
                    "names, their page kept as a reference. Anything uncertain is kept."}


def exclusion_summary(exclusions, log):
    removed = [e for e in log if e["action"] == "record_removed"]
    repaired = [e for e in log if e["action"] != "record_removed"]
    return {"rules_file": "scripts/webcam_exclusions.json", "rules_version": exclusions["version"],
            "rules_sha256": exclusions["sha256"],
            "rules": [{k: r[k] for k in ("id", "action", "reason", "evidence", "decided") if k in r} for r in exclusions["rules"]],
            "records_removed": len(removed),
            "records_removed_by_rule": dict(sorted(collections.Counter(e["rule"] for e in removed).items())),
            "records_removed_by_rule_and_country": {rule: dict(sorted(collections.Counter(e["country"] for e in removed if e["rule"] == rule).items()))
                                                    for rule in sorted({e["rule"] for e in removed})},
            "fields_repaired_by_rule": dict(sorted(collections.Counter(e["rule"] for e in repaired).items()))}


def community_source(provider):
    source = PROVIDER_POLICIES.get(provider, {}).get("source", {})
    return source.get("provenance_type") == "community_directory"


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def canonical_url(value, allowed_hosts=None, *, allow_nonstandard_port=False):
    """Conservative metadata validation. Query tokens are not stripped or rewritten.

    Actual network clients must additionally pin/check DNS and each redirect.
    This builder only fetches a fixed official catalog host.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        return None
    value = value.strip()
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        return None
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower().rstrip(".")
        if u.scheme.lower() not in ("https", "http") or not host or "%" in host or u.username is not None or u.password is not None:
            return None
        if u.port is not None and (u.port == 0 or not allow_nonstandard_port and u.port not in (80, 443)):
            return None
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost", ".lcl", ".localdomain", ".intranet", ".corp", ".home.arpa")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            # Reject alternate numeric IPv4 notation, rather than trusting DNS.
            if all(c in "0123456789.xabcdef" for c in host) and "." not in host:
                return None
        if allowed_hosts is not None and host not in allowed_hosts:
            return None
        if private_url_reason(value):  # Credentials in the query, home dynamic-DNS hosts.
            return None
        netloc = (f"[{host}]" if ":" in host else host)
        if u.port is not None and u.port != (443 if u.scheme.lower() == "https" else 80):
            netloc += f":{u.port}"
        return urlunsplit((u.scheme.lower(), netloc, u.path or "/", u.query, ""))
    except (ValueError, TypeError):
        return None


class CatalogRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe = canonical_url(newurl, {"cwwp2.dot.ca.gov"})
        if not safe or not safe.startswith("https://"):
            raise ValueError("Catalog redirect outside the approved HTTPS source")
        return super().redirect_request(req, fp, code, msg, headers, safe)


def fetch_caltrans(folder):
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    opener = build_opener(CatalogRedirect())
    for district in range(1, 13):
        url = f"https://cwwp2.dot.ca.gov/data/d{district}/cctv/cctvStatusD{district:02d}.json"
        req = Request(url, headers={"User-Agent": "Q-Globe public metadata collector", "Accept": "application/json"})
        with opener.open(req, timeout=40) as response:
            body = response.read(20 * 1024 * 1024 + 1)
            if len(body) > 20 * 1024 * 1024:
                raise ValueError("Catalog exceeds the bounded metadata download")
            if not isinstance(json.loads(body).get("data"), list):
                raise ValueError("Unexpected Caltrans schema")
            row = {"district": district, "url": url, "observed_at": utcnow(),
                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                   "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
        path = folder / f"caltrans_d{district:02d}.json"
        path.with_suffix(".tmp").write_bytes(body)
        path.with_suffix(".tmp").replace(path)
        manifest.append(row)
        time.sleep(1)
    # Only replace the successful inventory when every district completed.
    write_json(folder / "fetch_manifest.json", manifest)


def truth(value):
    if value in (True, "true", "yes", 1):
        return True
    if value in (False, "false", "no", 0):
        return False
    return None


def unverified_health():
    return {"status": "unverified", "checked_at": None, "manifest_ok": None, "segment_ok": None, "advancing": None}


def normalize_caltrans(c, district, observed_at):
    loc, image = c.get("location", {}), c.get("imageData", {})
    lat, lng = float(loc["latitude"]), float(loc["longitude"])
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError("Invalid coordinates")
    image_url = canonical_url(image.get("static", {}).get("currentImageURL"), ALLOWED_HOSTS)
    supplied_stream = canonical_url(image.get("streamingVideoURL"), ALLOWED_HOSTS)
    stream = supplied_stream if supplied_stream and urlsplit(supplied_stream).path.lower().endswith(".m3u8") else None
    # Caltrans's index is a source row number, not a globally stable camera id.
    # The current-image path is unique in the observed catalog and anchors identity.
    identity = image_url or supplied_stream
    if not identity or (not image_url and not stream):
        raise ValueError("No usable official media reference")
    camera_id = "caltrans:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return {
        "id": camera_id, "provider": "caltrans", "provider_id": f"{district}:{c.get('index', '')}",
        "identity_basis": "official_current_image_url" if image_url else "official_stream_url",
        "name": str(loc.get("locationName") or f"Caltrans district {district}").strip(),
        "lat": lat, "lng": lng, "country": "US", "region": "California", "district": district,
        "county": loc.get("county"), "road": loc.get("route"), "direction": loc.get("direction"),
        "format": "hls" if stream else "snapshot", "stream_url": stream, "snapshot_url": image_url,
        "unclassified_video_url": supplied_stream if supplied_stream and not stream else None,
        "source_video_url": image.get("streamingVideoURL") or None,
        "invalid_source_video_url": bool(image.get("streamingVideoURL") and not supplied_stream),
        "source_page": CALTRANS_DOCS,
        "source_catalog": f"https://cwwp2.dot.ca.gov/data/d{district}/cctv/cctvStatusD{district:02d}.json",
        "attribution": SOURCE["attribution"], "rights_status": SOURCE["rights_status"],
        "metadata_license": SOURCE["metadata_license"], "media_rights": SOURCE["media_rights"],
        "coordinate_role": "camera_location", "terms_url": SOURCE["terms_url"],
        "provider_in_service": truth(c.get("inService")),
        "provider_record_timestamp": c.get("recordTimestamp"), "observed_at": observed_at,
        "health": unverified_health(),
    }


def load_caltrans(folder, fallback_time):
    observations, expected_hashes = {}, {}
    manifest_path = folder / "fetch_manifest.json"
    if manifest_path.exists():
        inventory = json.loads(manifest_path.read_text())
        observations = {int(x["district"]): x["observed_at"] for x in inventory}
        expected_hashes = {int(x["district"]): x["sha256"] for x in inventory}
        if set(expected_hashes) != set(range(1, 13)):
            raise ValueError("Incomplete source fetch manifest")
    elif (folder / "caltrans_normalized.json").exists():
        for row in json.loads((folder / "caltrans_normalized.json").read_text()):
            observations.setdefault(int(row["district"]), row.get("observed_at", fallback_time))
    items, rejected, provenance = [], [], []
    for district in range(1, 13):
        path = folder / f"caltrans_d{district:02d}.json"
        body = path.read_bytes()  # Missing districts fail the build, not silent deletion.
        if district in expected_hashes and hashlib.sha256(body).hexdigest() != expected_hashes[district]:
            raise ValueError(f"District {district} does not match its fetch manifest; rerun the complete fetch")
        data = json.loads(body)["data"]
        provenance.append({"source": "caltrans", "district": district, "file": path.name,
                           "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                           "records": len(data), "observed_at": observations.get(district, fallback_time)})
        for raw in data:
            try:
                items.append(normalize_caltrans(raw["cctv"], district, observations.get(district, fallback_time)))
            except (KeyError, ValueError, TypeError) as e:
                rejected.append({"provider": "caltrans", "district": district, "source_index": raw.get("cctv", {}).get("index"), "reason": str(e)})
    ids = collections.Counter(x["id"] for x in items)
    if any(n > 1 for n in ids.values()):
        raise ValueError("Duplicate camera identity; review source aliases rather than discard silently")
    return sorted(items, key=lambda x: x["id"]), provenance, rejected


def normalize_extra_item(raw, observed_at, privacy_log=None):
    """Adapt only an independently approved official provider, ignoring imported health."""
    if not isinstance(raw, dict):
        raise ValueError("Extra catalog item must be an object")
    provider = raw.get("provider")
    if provider not in EXTRA_CATALOG_PROVIDERS:
        raise ValueError("Unapproved extra-catalog provider")
    if PROVIDER_POLICIES[provider].get("status") == "held":
        raise ValueError("Source is held until its conditions are met (see its policy)")
    if provider != "vegvesen":
        return normalize_world_item(raw, observed_at, privacy_log)
    if raw.get("rights_status") != "official_public_feed":
        raise ValueError("Extra catalog item lacks the approved official_public_feed rights status")
    source = PROVIDER_POLICIES[provider]["source"]
    provider_id = raw.get("provider_id")
    if not isinstance(provider_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", provider_id):
        raise ValueError("Invalid official provider camera identifier")
    camera_id = f"{provider}:{provider_id}"
    if raw.get("id", camera_id) != camera_id:
        raise ValueError("Camera identity does not match its provider identifier")
    lat, lng = float(raw["lat"]), float(raw["lng"])
    # Broad Norwegian road-network bounds, including Jan Mayen and Svalbard;
    # this is a coordinate sanity check, not a national-boundary assertion.
    if raw.get("country") != "NO" or not (math.isfinite(lat) and math.isfinite(lng)
                                           and 57 <= lat <= 82 and -10 <= lng <= 40):
        raise ValueError("Vegvesen item must have plausible Norwegian coordinates and country NO")
    media = {}
    for field in ("stream_url", "snapshot_url"):
        value = raw.get(field)
        url = canonical_url(value, PROVIDER_POLICIES[provider]["media_hosts"])
        if value not in (None, "") and (not url or not url.startswith("https://")):
            raise ValueError(f"Unapproved official media URL in {field}")
        media[field] = url
    format_ = raw.get("format")
    if format_ == "hls":
        if not media["stream_url"] or not urlsplit(media["stream_url"]).path.lower().endswith(".m3u8"):
            raise ValueError("HLS record requires an approved .m3u8 stream URL")
    elif format_ == "snapshot":
        if not media["snapshot_url"] or media["stream_url"]:
            raise ValueError("Snapshot record requires an image URL and no stream URL")
    else:
        raise ValueError("Unsupported official media format")
    source_page = canonical_url(raw.get("source_page") or source["url"],
                                {"dataut.vegvesen.no", "www.vegvesen.no", "vegvesen.no"})
    source_catalog = canonical_url(raw.get("source_catalog") or source["catalog_url"],
                                   {"ogckart-sn1.atlas.vegvesen.no"})
    if not source_page or not source_catalog or not source_page.startswith("https://") or not source_catalog.startswith("https://"):
        raise ValueError("Unapproved official catalog or source-page URL")
    # Keep provider-specific factual metadata, but do not retain imported probe
    # claims or repair flags that could inflate the health/audit summary.
    item = {k: v for k, v in raw.items() if k not in ("health", "url_repair", "media_access")}
    item.update({"id": camera_id, "provider": provider, "provider_id": provider_id,
                 "identity_basis": "official_camera_id", "name": str(raw.get("name") or camera_id).strip(),
                 "lat": lat, "lng": lng, "country": "NO", "region": "Norway", "district": None,
                 "county": raw.get("county_number"), "road": raw.get("road_number", raw.get("road")),
                 "direction": raw.get("direction"), "format": format_, **media,
                 "source_page": source_page, "source_catalog": source_catalog,
                 "attribution": source["attribution"], "rights_status": source["rights_status"],
                 "metadata_license": source["metadata_license"], "media_rights": source["media_rights"],
                 "coordinate_role": "camera_location", "terms_url": source["terms_url"],
                 "provider_in_service": truth(raw.get("provider_in_service")),
                 "provider_record_timestamp": raw.get("provider_record_timestamp", raw.get("source_updated_at")),
                 "observed_at": raw.get("observed_at") or observed_at,
                 "source_video_url": media["stream_url"], "unclassified_video_url": None,
                 "invalid_source_video_url": False, "health": unverified_health()})
    return item


def page_url(value, *, community=False):
    """Validate a public web link without requesting it; keep meaningful anchors.

    community: the link comes from a community directory (OSM, Wikidata), so camera
    device endpoints are refused as well (see private_url_reason).
    """
    # External references may legitimately use an operator's published HTTPS
    # port. This does not authorize that URL for embedded media or network probes.
    normalized = canonical_url(value, allow_nonstandard_port=True)
    if not normalized or private_url_reason(value, community=community):
        return None
    host = urlsplit(normalized).hostname
    if not host or "." not in host or host.endswith((".onion", ".lan", ".home", ".test", ".invalid")):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # Directory links are hostnames, not exposed camera IPs.
    except ValueError:
        pass
    if (not any(c.isalpha() for c in host) or host.startswith("0x")
            or all(re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", part) for part in host.split("."))):
        return None
    if any(host == h or host.endswith("." + h) for h in ("insecam.org", "opentopia.com", "shodan.io")):
        return None
    return normalized + ("#" + urlsplit(value.strip()).fragment if urlsplit(value.strip()).fragment else "")


REFERENCE_FIELDS = ("reference_url", "reported_clip_url", "reference_hls_url", "reference_snapshot_url")


def normalize_world_item(raw, observed_at, privacy_log=None):
    """Use the reviewed source policy; never promote a page or imported health to video.

    privacy_log, when given, receives one entry per private link removed from a kept
    record (by field and reason, never the URL). A private primary link removes the
    record: PrivacyFiltered.
    """
    provider = raw["provider"]
    policy = PROVIDER_POLICIES[provider]
    source = policy["source"]
    community = community_source(provider)
    # The record's own links first, so the reason is reported rather than a generic one.
    for field in ("official_page", "webcam_page", "source_page", "stream_url", "snapshot_url", "source_catalog"):
        reason = private_url_reason(raw.get(field), community=community)
        if reason:
            raise PrivacyFiltered(reason, field)
    references, dropped = {}, []
    for field in REFERENCE_FIELDS:
        reason = private_url_reason(raw.get(field), community=community)
        if reason:
            dropped.append({"id": f"{provider}:{raw.get('provider_id')}", "provider": provider,
                            "field": field, "reason": reason, "action": "link_removed"})
        references[field] = None if reason else page_url(raw.get(field), community=community)
    provider_id = raw.get("provider_id")
    if not isinstance(provider_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,159}", provider_id):
        raise ValueError("Invalid stable provider identifier")
    camera_id = f"{provider}:{provider_id}"
    if len(camera_id) > 160 or raw.get("id", camera_id) != camera_id:
        raise ValueError("Camera identity does not match provider identifier")
    lat, lng = float(raw["lat"]), float(raw["lng"])
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise ValueError("Missing or invalid published coordinates")
    country = str(raw.get("country") or "ZZ").upper()
    if not re.fullmatch(r"[A-Z]{2}", country) or policy.get("countries") and country not in policy["countries"]:
        raise ValueError("Country outside reviewed provider scope")
    format_ = raw.get("format")
    if format_ not in policy.get("formats", ["official_page"]):
        raise ValueError("Format not authorized by source policy")
    media = {"stream_url": None, "snapshot_url": None}
    if format_ == "official_page":
        if raw.get("rights_status") != "official_page_only":
            raise ValueError("External page must carry a metadata-only rights status")
        if raw.get("stream_url") or raw.get("snapshot_url"):
            raise ValueError("Metadata-only page cannot authorize embedded media")
        official_page = page_url(raw.get("official_page") or raw.get("webcam_page") or raw.get("source_page"),
                                 community=community)
        if not official_page:
            raise ValueError("Page record requires a published, safe web link")
        page_hosts = policy.get("page_hosts") or source.get("official_page_hosts")
        supplied = raw.get("official_page") or raw.get("webcam_page")
        if (supplied and page_hosts and urlsplit(official_page).hostname not in page_hosts
                and supplied != policy.get("official_map_url")):
            raise ValueError("Page host is outside the reviewed publisher list")
        rights = "official_page_only"
    else:
        if raw.get("rights_status") != "official_public_feed":
            raise ValueError("Media record lacks the approved public feed rights status")
        for field in media:
            value = raw.get(field)
            media[field] = canonical_url(value, policy["media_hosts"])
            if value and (not media[field] or not media[field].startswith("https://")):
                raise ValueError(f"Media host is not approved for {provider}: {field}")
        if format_ == "snapshot" and (not media["snapshot_url"] or media["stream_url"]):
            raise ValueError("Snapshot requires an image URL and no video URL")
        if format_ == "hls" and (not media["stream_url"] or not urlsplit(media["stream_url"]).path.lower().endswith(".m3u8")):
            raise ValueError("HLS requires an approved manifest URL")
        official_page = page_url(raw.get("official_page"), community=community)
        rights = "official_public_feed"
    source_page = page_url(raw.get("source_page") or source["url"], community=community)
    source_catalog = page_url(raw.get("source_catalog") or source.get("catalog_url") or source["url"], community=community)
    if not source_page or not source_catalog:
        raise ValueError("Source provenance URL missing or unsafe")
    role = policy.get("force_coordinate_role") or raw.get("coordinate_role") or policy.get("coordinate_role", "camera_location")
    if role not in ("camera_location", "station_location", "associated_feature", "feature_center", "approximate"):
        raise ValueError("Unknown coordinate role")
    # Preserve factual adapter metadata, but source policy and evidence win over
    # any claims embedded in downloaded catalog files.
    item = {k: v for k, v in raw.items() if k not in ("health", "url_repair", "media_access")}
    item.update({"id": camera_id, "provider_id": provider_id, "name": str(raw.get("name") or camera_id).strip(),
                 "lat": lat, "lng": lng, "country": country, "region": str(raw.get("region") or ""),
                 "district": raw.get("district"), "road": raw.get("road"), "direction": raw.get("direction"),
                 "format": format_, **media, "official_page": official_page, "source_page": source_page,
                 "source_catalog": source_catalog, **references,
                 "metadata_license": source.get("metadata_license", source.get("license")),
                 "terms_url": source["terms_url"], "license_url": source.get("license_url"),
                 "media_rights": source.get("media_rights"), "rights_status": rights,
                 "attribution": source["attribution"], "coordinate_role": role,
                 "provider_in_service": truth(raw.get("provider_in_service")),
                 "observed_at": raw.get("observed_at") or observed_at,
                 "source_video_url": media["stream_url"], "unclassified_video_url": None,
                 "invalid_source_video_url": False, "health": unverified_health()})
    if privacy_log is not None:
        privacy_log.extend(dropped)
    return item


def private_strings(value, community, path=""):
    """(field, reason) for each private URL or dynamic-DNS host name anywhere in a record's strings."""
    if isinstance(value, str):
        for url in URL_IN_TEXT.findall(value):
            reason = private_url_reason(url, community=community)
            if reason:
                yield path, reason
        for name in re.findall(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
            if dynamic_dns_host(name):
                yield path, "dynamic_dns_host"
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from private_strings(child, community, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from private_strings(child, community, f"{path}[{index}]")


def privacy_sweep(items, sources):
    """Last check before anything is written: fields copied from an input are not validated
    one by one, so no kept record may hold a private URL anywhere, and no source either."""
    for source in sources:
        found = next(private_strings(source, False), None)
        if found:
            raise ValueError(f"Reviewed source {source.get('id')!r} carries a private URL in {found[0]}")
    kept, log = [], []
    for item in items:
        found = next(private_strings(item, community_source(item.get("provider"))), None)
        if found:
            log.append({"id": item["id"], "provider": item["provider"], "field": found[0], "reason": found[1],
                        "action": "record_removed"})
        else:
            kept.append(item)
    return kept, log


def privacy_summary(log):
    removed = [e for e in log if e["action"] == "record_removed"]
    links = [e for e in log if e["action"] == "link_removed"]
    return {"rules": PRIVACY_RULES, "public_query_key_allowlist": {h: sorted(k) for h, k in PUBLIC_QUERY_KEY_ALLOWLIST.items()},
            "records_removed": len(removed), "links_removed_from_kept_records": len(links),
            "records_removed_by_reason": dict(sorted(collections.Counter(e["reason"] for e in removed).items())),
            "records_removed_by_provider": dict(sorted(collections.Counter(e["provider"] for e in removed).items())),
            "links_removed_by_reason": dict(sorted(collections.Counter(e["reason"] for e in links).items())),
            "note": "Entries name the record, field and rule only: removed URLs and host names are not reproduced."}


def load_extra_catalogs(paths, fallback_time, privacy_log=None, exclusions=None, exclusion_log=None):
    """Load normalized metadata without trusting the input's provider/rights policy.

    The first approved adapter used {sources, items} without schema_version;
    absence denotes that version-1 shape. Any explicit different version fails.
    A newer collection can replace a provider's records from an older input file
    with "supersedes": [provider, ...]; it must declare that provider itself.
    """
    items, sources, provenance, rejected = [], {}, [], []
    docs = [(Path(path), Path(path).read_bytes()) for path in paths]
    docs = [(path, body, json.loads(body)) for path, body in docs]
    superseded = {}
    for path, _, obj in docs:
        for provider in (obj.get("supersedes") or []) if isinstance(obj, dict) else []:
            declared_here = {x.get("id") for x in obj.get("sources", []) if isinstance(x, dict)}
            if provider not in declared_here:
                raise ValueError(f"{path.name} supersedes {provider!r} without declaring it")
            if superseded.setdefault(provider, path.name) != path.name:
                raise ValueError(f"Two input files supersede {provider!r}")
    for path, body, obj in docs:
        if (not isinstance(obj, dict) or obj.get("schema_version", 1) != 1
                or not isinstance(obj.get("sources"), list) or not isinstance(obj.get("items"), list)):
            raise ValueError(f"Unsupported extra-catalog schema: {path}")
        declared = set()
        for source in obj["sources"]:
            provider = source.get("id") if isinstance(source, dict) else None
            if provider not in EXTRA_CATALOG_PROVIDERS:
                raise ValueError(f"Unapproved extra-catalog source: {provider!r}")
            if provider in declared:
                raise ValueError(f"Duplicate source declaration: {provider}")
            if provider == "vegvesen" and source.get("rights_status", "official_public_feed") != "official_public_feed":
                raise ValueError(f"Unapproved source rights status: {provider}")
            declared.add(provider)
            # Registry metadata comes from the reviewed policy, not from an
            # input-supplied host list, licence, or attribution override.
            sources[provider] = dict(PROVIDER_POLICIES[provider]["source"])
        if not declared:
            raise ValueError(f"Extra catalog declares no approved sources: {path}")
        observed_times = [row.get("observed_at") for row in obj["items"]
                          if isinstance(row, dict) and isinstance(row.get("observed_at"), str) and row["observed_at"]]
        file_time = obj.get("generated_at") or (min(observed_times) if observed_times else fallback_time)
        counts = collections.Counter(row.get("provider") if isinstance(row, dict) and isinstance(row.get("provider"), str)
                                     else "unknown" for row in obj["items"])
        for provider in sorted(declared):
            if superseded.get(provider, path.name) != path.name:
                provenance.append({"source": provider, "file": path.name, "kind": "superseded_input",
                                   "superseded_by": superseded[provider], "records": 0,
                                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "observed_at": file_time})
                continue
            provenance.append({"source": provider, "file": path.name,
                               "kind": "normalized_extra_catalog", "input_schema_version": obj.get("schema_version", 1),
                               "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                               "records": len(obj["items"]) if len(declared) == 1 else counts[provider],
                               "file_records": len(obj["items"]), "provider_records": dict(counts),
                               "observed_at": file_time})
        for index, raw in enumerate(obj["items"]):
            if isinstance(raw, dict) and superseded.get(raw.get("provider"), path.name) != path.name:
                continue  # replaced by a newer collection of the same provider
            try:
                if not isinstance(raw, dict) or raw.get("provider") not in declared:
                    raise ValueError("Item provider is not an approved declared source")
                raw = repair_raw(raw, (exclusions or {}).get("rules", []), exclusion_log)
                items.append(normalize_extra_item(raw, file_time, privacy_log))
            except PrivacyFiltered as exc:
                if privacy_log is not None:
                    privacy_log.append({"id": raw.get("id") or f"{raw.get('provider')}:{raw.get('provider_id')}",
                                        "provider": raw.get("provider"), "field": exc.field, "reason": exc.reason,
                                        "action": "record_removed"})
                rejected.append({"file": path.name, "source_index": index, "source": raw.get("provider"),
                                 "provider": raw.get("provider"), "provider_id": raw.get("provider_id"),
                                 "reason": str(exc)})
            except (KeyError, ValueError, TypeError) as exc:
                rejected.append({"file": path.name, "source_index": index,
                                 "source": next(iter(declared)) if len(declared) == 1 else raw.get("provider") if isinstance(raw, dict) else "unknown",
                                 "provider": raw.get("provider") if isinstance(raw, dict) else None,
                                 "provider_id": raw.get("provider_id") if isinstance(raw, dict) else None,
                                 "reason": str(exc)})
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Duplicate camera identity across extra catalogs; review source overlap")
    return sorted(items, key=lambda x: x["id"]), [sources[k] for k in sorted(sources)], provenance, rejected


def load_probe_events(paths, parse_warnings=None):
    """Read valid evidence without modifying a resumed JSONL checkpoint.

    A killed writer can leave a partial line before later complete records. Keep
    the original bytes, warn visibly, and optionally collect audit diagnostics.
    Malformed whole-document JSON still fails instead of losing an entire run.
    """
    events = []
    for path in paths:
        raw = Path(path).read_bytes()
        if Path(path).suffix == ".jsonl":
            rows = []
            for line_number, line in enumerate(raw.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line.decode("utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    diagnostic = {"file": str(path), "line": line_number,
                                  "reason": "invalid_json" if isinstance(exc, json.JSONDecodeError) else "invalid_utf8",
                                  "column": exc.colno if isinstance(exc, json.JSONDecodeError) else exc.start + 1,
                                  "line_bytes": len(line), "line_sha256": hashlib.sha256(line).hexdigest(),
                                  "action": "skipped_line_original_file_preserved"}
                    if parse_warnings is not None:
                        parse_warnings.append(diagnostic)
                    warnings.warn(f"Probe evidence {path}:{line_number}: malformed JSONL line skipped; original bytes preserved",
                                  RuntimeWarning, stacklevel=2)
        else:
            obj = json.loads(raw)
            rows = obj if isinstance(obj, list) else obj.get("checks", obj.get("results", []))
        for row in rows:
            if isinstance(row, dict) and row.get("url"):
                events.append(row)
    return events


def apply_verified_repairs(items, rows):
    """Only adopt an explicitly tested correction; preserve the official source string."""
    by_id = {x["provider_id"]: x for x in items if x.get("provider") == "caltrans"}
    events = []
    for r in rows:
        item = by_id.get(r.get("provider_id"))
        url = canonical_url(r.get("candidate_url"), ALLOWED_HOSTS)
        if (not item or r.get("original_url") != item.get("source_video_url") or not url
                or not urlsplit(url).path.lower().endswith(".m3u8")
                or r.get("http_status") != 200 or r.get("hls_manifest_valid") is not True or r.get("error")):
            continue
        item["stream_url"], item["format"] = url, "hls"
        item["url_repair"] = {"original_url": r["original_url"], "repair_kind": r.get("repair_kind"),
                              "checked_at": r.get("checked_at"), "evidence": "corrected master playlist returned HTTP 200 and EXTM3U"}
        events.append({"url": url, "checked_at": r.get("checked_at"), "http_status": 200,
                       "manifest_valid": True, "live_verified": False, "status": "manifest_reachable"})
    return events


def event_health(e):
    """Accept facts from both bounded-checker versions. Never infer progression from HTTP 200."""
    stamp = e.get("refresh_master_at") or e.get("rechecked_at") or e.get("checked_at") or e.get("observed_at")
    try:
        parsed_stamp = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if parsed_stamp.tzinfo is None:
            stamp = None
        else:
            stamp = parsed_stamp.astimezone(dt.timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, TypeError):
        stamp = None
    manifest = e.get("manifest_valid", e.get("valid", e.get("manifest_ok")))
    segment = e.get("segment_ok")
    if segment is None and e.get("segment_bytes_sampled", 0) > 0:
        segment = e.get("segment_http_status") in (200, 206) and str(e.get("segment_content_type", "")).lower().startswith(("video/", "application/octet-stream"))
    advancing = e.get("advancing", e.get("manifest_advanced", e.get("playlist_advanced")))
    if e.get("pair_first") and e.get("pair_second"):
        first, second, latest = e["pair_first"], e["pair_second"], e.get("latest_segment", {})
        manifest = first.get("valid") is True and second.get("valid") is True
        segment = latest.get("mpeg_ts_signature") is True and latest.get("http_status") in (200, 206) and latest.get("bytes", 0) >= 377
        advancing = (e.get("same_media_url") is True and e.get("elapsed_seconds", 0) >= 2 * second.get("target_duration", 999999)
                     and (e.get("sequence_advanced") is True or e.get("segment_identity_changed") is True)
                     and not first.get("endlist") and not second.get("endlist"))
    status, error = e.get("status", ""), str(e.get("error", ""))
    code = e.get("recheck_http_status", e.get("http_status"))
    error_code = re.search(r"HTTP Error (\d{3})", error)
    if error_code:
        code = int(error_code.group(1))
    # If the master succeeded but a volatile variant/segment failed, do not
    # report that the published master URL itself returned 404.
    partial_failure = bool(error and manifest is True)
    if partial_failure:
        state = "network_unverified"
    elif status in ("network_error", "timeout", "network_unverified", "rate_limited") or code == 429 or (isinstance(code, int) and code >= 500) or "timed out" in error.lower() or "timeout" in error.lower():
        state = "network_unverified"
    elif code in (401, 403) or any(s in error for s in ("HTTP Error 401", "HTTP Error 403")):
        state = "auth_required"
    elif code in (404, 410) or any(s in error for s in ("HTTP Error 404", "HTTP Error 410")):
        state = "unavailable"
    elif e.get("live_verified") is True and stamp and manifest is True and segment is True and advancing is True and not e.get("endlist", e.get("is_endlist", False)) and not error:
        state = "live_confirmed"
    elif status == "stale":
        state = "stale"
    elif segment is True:
        state = "segment_ok"
    elif manifest is True:
        state = "playlist_ok"
    else:
        state = "network_unverified" if error or status else "unverified"
    return {"status": state, "checked_at": stamp, "manifest_ok": manifest,
            "segment_ok": segment, "advancing": advancing,
            "http_status": e.get("http_status") if partial_failure else code,
            "failure_stage": ("segment_or_variant" if partial_failure else "manifest") if error else None,
            "failure_http_status": code if error else None, "error": error or None,
            "verification_scope": "collector_network; not an Android/web/Tor playback certification"}


def group_probe_events(events):
    """Associate evidence only with hosts approved for that particular provider."""
    grouped = collections.defaultdict(list)
    for e in events:
        for provider, policy in PROVIDER_POLICIES.items():
            if e.get("provider") not in (None, provider):
                continue
            url = canonical_url(e.get("url"), policy["media_hosts"])
            if url:
                grouped[(provider, url)].append(e)
    return grouped


def incomplete_probe(event):
    """Local cancellation is not evidence that an upstream stream failed."""
    return event.get("status") in INCOMPLETE_PROBE_STATUSES


def apply_health(items, events):
    grouped = group_probe_events(events)
    rank = {"unverified": 0, "network_unverified": 1, "playlist_ok": 2, "segment_ok": 3,
            "live_confirmed": 4, "stale": 5, "auth_required": 5, "unavailable": 5}
    for item in items:
        policy = PROVIDER_POLICIES.get(item.get("provider"))
        if not policy:
            continue
        url = canonical_url(item.get("stream_url"), policy["media_hosts"])
        checks = grouped.get((item["provider"], url), []) if url else []
        if not checks:
            continue
        completed = [e for e in checks if not incomplete_probe(e)]
        states = [event_health(e) for e in completed]
        # A newer explicit failure supersedes a positive; a later shallow success
        # must not pretend to be a new temporal verification. A locally stopped
        # run contributes audit metadata but cannot erase completed evidence.
        states.sort(key=lambda s: s.get("checked_at") or "")
        selected = states[0] if states else dict(item.get("health") or unverified_health())
        for state in states[1:]:
            if state["status"] in ("network_unverified", "unavailable", "auth_required", "stale") or selected["status"] in ("network_unverified", "unavailable", "auth_required", "stale") or rank[state["status"]] >= rank[selected["status"]]:
                selected = state
        all_times = [event_health(e).get("checked_at") for e in checks]
        item["health"] = {**selected, "last_probe_at": max((t for t in all_times if t), default=None),
                          "last_completed_probe_at": states[-1].get("checked_at") if states else
                                                     selected.get("last_completed_probe_at", selected.get("checked_at")),
                          "probe_count": len(checks), "incomplete_probe_count": len(checks) - len(completed)}


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def coordinate_crs(item):
    return str(item.get("coordinate_reference_system") or item.get("coordinate_crs") or "EPSG:4326")


def wgs84_coordinates(item):
    return coordinate_crs(item).upper().startswith(("EPSG:4326", "WGS84", "WGS 84"))


def candidate_matches(db, item, radius=100):
    """Return geographic associations, never an identity merge; all SQL values are bound."""
    if item.get("coordinate_role") in ("associated_feature", "feature_center", "approximate"):
        return []  # A city's/landmark's coordinates do not locate its camera.
    if not wgs84_coordinates(item):
        return []  # Preserve a supplied datum; don't silently call it WGS84.
    lat, lon = item["lat"], item["lng"]
    dy = radius / 110000
    dx = 180 if abs(lat) + dy >= 90 else min(180, radius / max(1, 110000 * math.cos(math.radians(lat))))
    ranges = [(max(-180, lon-dx), min(180, lon+dx))]
    if lon-dx < -180:
        ranges.append((lon-dx+360, 180))
    if lon+dx > 180:
        ranges.append((-180, lon+dx-360))
    rows = []
    for low, high in ranges:
        rows.extend(db.execute("SELECT osm_node_id,lat,lon,operator,name,direction FROM surveillance_nodes "
                              "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                              (lat-dy, lat+dy, low, high)))
    matches = []
    hints = PROVIDER_POLICIES.get(item.get("provider"), {}).get("operator_hints", ())
    for oid, y, x, operator, name, direction in rows:
        meters = distance_m(lat, lon, y, x)
        if meters <= radius:
            matches.append({"webcam_id": item["id"], "osm_node_id": oid, "distance_m": round(meters, 2),
                            "operator": operator, "name": name, "direction": direction,
                            "match_status": "geographic_candidate_only", "identity_confirmed": False,
                            "operator_hint": any(hint in str(operator or "").lower() for hint in hints),
                            "attribution": OSM_ATTRIBUTION})
    return sorted(matches, key=lambda m: (m["distance_m"], m["osm_node_id"]))


def provider_statistics(items, provenance, rejected, events, matches):
    """Separate camera records, unique streams, completed checks and proximity links."""
    grouped = group_probe_events(events)
    n_by_cam = collections.Counter(m["webcam_id"] for m in matches)
    providers = {x["provider"] for x in items} | {x["source"] for x in provenance}
    stats = {}
    for provider in sorted(providers):
        cameras = [x for x in items if x["provider"] == provider]
        hls = [x for x in cameras if x["format"] == "hls"]
        urls = {x["stream_url"] for x in hls}
        url_health = {x["stream_url"]: x["health"]["status"] for x in hls}
        probes = [e for url in urls for e in grouped.get((provider, url), [])]
        stats[provider] = {
            "source_records": sum(p["records"] for p in provenance if p["source"] == provider),
            "accepted_cameras": len(cameras),
            "rejected_records": sum(r.get("source", r.get("provider")) == provider for r in rejected),
            "hls_camera_records": len(hls), "distinct_hls_urls": len(urls),
            "snapshot_only_records": sum(x["format"] == "snapshot" for x in cameras),
            "official_page_records": sum(x["format"] == "official_page" for x in cameras),
            "distinct_primary_urls": len({primary_url(x) for x in cameras if primary_url(x)}),
            "provider_in_service_false": sum(x["provider_in_service"] is False for x in cameras),
            "health_camera_counts": dict(collections.Counter(x["health"]["status"] for x in cameras)),
            "hls_health_counts": dict(collections.Counter(x["health"]["status"] for x in hls)),
            "hls_url_health_counts": dict(collections.Counter(url_health.values())),
            "probe_events": len(probes), "incomplete_probe_events": sum(incomplete_probe(e) for e in probes),
            "completed_probe_events": sum(not incomplete_probe(e) for e in probes),
            "attempted_distinct_hls_urls": sum(bool(grouped.get((provider, url))) for url in urls),
            "probed_distinct_hls_urls": sum(any(not incomplete_probe(e) for e in grouped.get((provider, url), [])) for url in urls),
            "osm_candidate_links": sum(n_by_cam[x["id"]] for x in cameras),
            "cameras_with_osm_candidate": sum(x["id"] in n_by_cam for x in cameras),
            "hls_cameras_with_osm_candidate": sum(x["id"] in n_by_cam for x in hls),
            "cameras_with_multiple_osm_candidates": sum(n_by_cam[x["id"]] > 1 for x in cameras),
        }
    return stats


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)


def primary_url(item):
    return item.get({"hls": "stream_url", "snapshot": "snapshot_url", "official_page": "official_page"}.get(item["format"], ""))


def published_links(item):
    """Many camera views can share one URL; store the URL exactly once in SQLite."""
    first = primary_url(item)
    for field, purpose in (("stream_url", "hls"), ("snapshot_url", "snapshot"),
                           ("official_page", "web_page"), ("reference_url", "reference_only"),
                           ("reported_clip_url", "clip_reference_only"),
                           ("reference_hls_url", "hls_reference_only"),
                           ("reference_snapshot_url", "snapshot_reference_only")):
        url = item.get(field)
        if url:
            yield {"url": url, "purpose": purpose, "is_primary": url == first and not purpose.endswith("reference_only")}


def viewer_catalog(catalog):
    """Small view projection. Full records and evidence remain in SQLite/GeoJSON.

    Source-wide licences and attribution are inherited by prepareWebcams instead
    of being repeated tens of thousands of times in the browser payload.
    """
    fields = {"id", "provider", "name", "lat", "lng", "country", "region", "road", "road_number",
              "format", "stream_url", "snapshot_url", "official_page", "source_page", "rights_status",
              "provider_in_service", "observed_at", "coordinate_role", "country_inferred",
              "coordinate_reference_system", "coordinate_crs", "coordinate_transform_applied",
              "image_observed_at", "requires_catalog_refresh", "minimum_refresh_seconds", "provider_notice", "media_access"}
    rows = []
    for item in catalog["items"]:
        row = {k: v for k, v in item.items() if k in fields and v not in (None, "")}
        # Reference URLs remain external: the view must retain them without
        # creating media permissions or losing a second image/video per camera.
        references = {}
        primary_links = {primary_url(item), item.get("official_page")}
        for link in published_links(item):
            if link["purpose"].endswith("reference_only") and link["url"] not in primary_links:
                references[link["url"]] = link["purpose"]
        if references:
            row["reference_links"] = [{"url": url, "purpose": purpose} for url, purpose in references.items()]
        health = item["health"]
        row["health"] = {"status": "unverified"} if health["status"] == "unverified" and not health.get("checked_at") else health
        rows.append(row)
    return {**catalog, "payload_kind": "viewer_projection", "full_record_formats": ["SQLite", "GeoJSON"], "items": rows}


# The viewable-webcam file: what the globe loads first. Values repeated across rows are
# stored once per field (row cells hold their index, 0 = absent); js/webcams.mjs
# expandLiveCatalog rebuilds exactly the rows of the full view, so a card does not change.
LIVE_TABLE_FIELDS = frozenset({
    "provider", "country", "region", "road", "road_number", "format", "source_page", "official_page", "observed_at",
    "rights_status", "coordinate_role", "coordinate_reference_system", "coordinate_crs", "coordinate_transform_applied",
    "image_observed_at", "requires_catalog_refresh", "minimum_refresh_seconds", "provider_in_service",
    "provider_notice", "media_access", "health", "country_inferred"})
# Source fields the viewer reads (prepareWebcams); the rest stays in the full catalog.
LIVE_SOURCE_FIELDS = ("id", "name", "terms_url", "license_url", "license", "metadata_license",
                      "coordinate_reference_system", "coordinate_crs", "provider_notice", "requires_catalog_refresh",
                      "minimum_refresh_seconds", "media_rights", "attribution", "provenance_type", "record_notice")


def viewable(row):
    """An admitted HLS stream or snapshot: what can be played or loaded from the card."""
    return row.get("rights_status") == "official_public_feed" and (
        row.get("format") == "hls" and bool(row.get("stream_url"))
        or row.get("format") == "snapshot" and bool(row.get("snapshot_url")))


def live_view_catalog(view, full_url="data/webcams.json"):
    """Viewable webcams only, as columns with value tables (schema 3, payload viewer_live)."""
    rows = [r for r in view["items"] if viewable(r)]
    fields = sorted({k for r in rows for k in r})
    values = {f: [None] for f in fields if f in LIVE_TABLE_FIELDS}
    index = {f: {"null": 0} for f in values}
    cells = []
    for row in rows:
        if not row["id"].startswith(row["provider"] + ":"):
            raise ValueError("Viewer rows must carry provider-prefixed identities")
        out = []
        for f in fields:
            value = row.get(f)
            if f in values:
                key = json.dumps(value, sort_keys=True, ensure_ascii=False)
                if key not in index[f]:
                    index[f][key] = len(values[f])
                    values[f].append(value)
                out.append(index[f][key])
            elif f == "id":
                out.append(value[len(row["provider"]) + 1:])
            elif f == "reference_links":
                out.append([[link["url"], link["purpose"]] for link in value] if value else None)
            else:
                out.append(value)
        cells.append(out)
    providers = {r["provider"] for r in rows}
    return {"schema_version": 3, "payload_kind": "viewer_live", "generated_at": view.get("generated_at"),
            "full_catalog": {"url": full_url, "records": len(view["items"]),
                             "note": "Every record, web links included; loaded on request."},
            "sources": [{k: s[k] for k in LIVE_SOURCE_FIELDS if k in s} for s in view["sources"] if s.get("id") in providers],
            "fields": fields, "values": values, "rows": cells}


def expand_live_catalog(live):
    """The rows of a viewer_live file as the full view has them (twin of js/webcams.mjs expandLiveCatalog)."""
    rows = []
    for cells in live["rows"]:
        row = {}
        for field, value in zip(live["fields"], cells):
            if field in live["values"]:
                if live["values"][field][value] is not None:
                    row[field] = live["values"][field][value]
            elif field == "reference_links":
                if value:
                    row[field] = [{"url": url, "purpose": purpose} for url, purpose in value]
            elif value is not None:
                row[field] = value
        row["id"] = f"{row['provider']}:{row['id']}"
        rows.append(row)
    return {"schema_version": 2, "generated_at": live.get("generated_at"), "sources": live.get("sources", []), "items": rows}


def geojson_feature(item):
    properties = {k: v for k, v in item.items() if k not in ("lat", "lng")}
    geometry = {"type": "Point", "coordinates": [item["lng"], item["lat"]]}
    if not wgs84_coordinates(item):
        # RFC 7946 uses WGS84. Null geometry preserves the record without falsely
        # labelling untouched native-datum coordinates as a transformed point.
        geometry = None
        properties["source_coordinates"] = {"lat": item["lat"], "lng": item["lng"], "crs": coordinate_crs(item)}
        properties["geometry_note"] = "Native datum retained; transform to WGS84 before using as GeoJSON geometry."
    return {"type": "Feature", "id": item["id"], "geometry": geometry, "properties": properties}


def link_statistics(items):
    by_primary = collections.defaultdict(list)
    urls = set()
    for item in items:
        if primary_url(item):
            by_primary[primary_url(item)].append(item["id"])
        urls.update(link["url"] for link in published_links(item))
    playable_hls = {x["stream_url"] for x in items if x.get("stream_url")}
    published_hls = {url for url in urls if urlsplit(url).path.lower().endswith(".m3u8")}
    return {"distinct_primary_urls": len(by_primary), "distinct_published_urls_including_references": len(urls),
            "distinct_published_hls_urls_all_rights_states": len(published_hls),
            "hls_reference_urls_not_enabled_in_player": len(published_hls-playable_hls),
            "distinct_mp4_clip_reference_urls": len({url for url in urls if urlsplit(url).path.lower().endswith(".mp4")}),
            "shared_primary_url_groups": sum(len(ids) > 1 for ids in by_primary.values()),
            "records_with_shared_primary_url": sum(len(ids) for ids in by_primary.values() if len(ids) > 1)}, [
                {"url": url, "record_ids": ids, "note": "Shared URL; physical camera identity is not assumed"}
                for url, ids in sorted(by_primary.items()) if len(ids) > 1]


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            # Metadata includes public, user-edited OSM names. Prevent spreadsheet
            # formula evaluation on CSV open; JSON retains the original strings.
            safe = {k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v) for k, v in row.items()}
            w.writerow(safe)


def write_database(path, catalog, matches, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
      PRAGMA foreign_keys=ON;
      CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE sources(id TEXT PRIMARY KEY,name TEXT,url TEXT,terms_url TEXT,attribution TEXT,rights_status TEXT,notes TEXT,
        metadata_license TEXT,media_rights TEXT,source_json TEXT NOT NULL);
      CREATE TABLE public_webcams(id TEXT PRIMARY KEY,provider TEXT REFERENCES sources(id),provider_id TEXT,name TEXT,
        lat REAL NOT NULL CHECK(lat BETWEEN -90 AND 90),lon REAL NOT NULL CHECK(lon BETWEEN -180 AND 180),
        country TEXT,region TEXT,district TEXT,format TEXT,snapshot_url TEXT,provider_in_service INTEGER,
        observed_at TEXT,source_catalog TEXT,health_status TEXT,health_checked_at TEXT,
        official_page TEXT,reference_url TEXT,coordinate_role TEXT,coordinate_crs TEXT,location_group_id TEXT,record_json TEXT NOT NULL);
      CREATE TABLE published_urls(id TEXT PRIMARY KEY,url TEXT UNIQUE NOT NULL);
      CREATE TABLE webcam_url_links(webcam_id TEXT REFERENCES public_webcams(id),url_id TEXT REFERENCES published_urls(id),
        purpose TEXT NOT NULL,is_primary INTEGER NOT NULL,PRIMARY KEY(webcam_id,url_id,purpose));
      CREATE TABLE snapshot_access_checks(webcam_id TEXT PRIMARY KEY REFERENCES public_webcams(id),
        url_id TEXT REFERENCES published_urls(id),status TEXT NOT NULL,checked_at TEXT NOT NULL,
        http_status INTEGER,signature TEXT,bytes_read INTEGER,record_json TEXT NOT NULL);
      CREATE TABLE webcam_streams(id TEXT PRIMARY KEY,url TEXT UNIQUE NOT NULL,format TEXT NOT NULL,health_json TEXT);
      CREATE TABLE webcam_stream_links(webcam_id TEXT REFERENCES public_webcams(id),stream_id TEXT REFERENCES webcam_streams(id),
        PRIMARY KEY(webcam_id,stream_id));
      CREATE TABLE osm_candidate_links(webcam_id TEXT REFERENCES public_webcams(id),osm_node_id INTEGER,distance_m REAL,
        match_status TEXT CHECK(match_status='geographic_candidate_only'),operator_hint INTEGER,osm_operator TEXT,
        osm_name TEXT,osm_direction TEXT,attribution TEXT,PRIMARY KEY(webcam_id,osm_node_id));
      CREATE INDEX idx_webcams_geo ON public_webcams(lat,lon);
      CREATE INDEX idx_webcams_health ON public_webcams(health_status,format);
      CREATE INDEX idx_webcams_provider ON public_webcams(provider,provider_id);
      CREATE INDEX idx_webcams_country ON public_webcams(country,format);
      CREATE INDEX idx_candidates_osm ON osm_candidate_links(osm_node_id);
    """)
    for s in catalog["sources"]:
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(s.get(k) for k in ("id", "name", "url", "terms_url", "attribution", "rights_status", "rights_note", "metadata_license", "media_rights")) + (json.dumps(s, ensure_ascii=False),))
    for x in catalog["items"]:
        h = x["health"]
        db.execute("INSERT INTO public_webcams VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (x["id"], x["provider"], x["provider_id"], x["name"], x["lat"], x["lng"], x["country"], x["region"],
                    x["district"], x["format"], x["snapshot_url"], x["provider_in_service"], x["observed_at"], x["source_catalog"],
                    h["status"], h.get("checked_at"), x.get("official_page"), x.get("reference_url"),
                    x.get("coordinate_role", "camera_location"), coordinate_crs(x), x.get("location_group_id"), json.dumps(x, ensure_ascii=False)))
        for link in published_links(x):
            uid = hashlib.sha256(link["url"].encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO published_urls VALUES(?,?)", (uid, link["url"]))
            db.execute("INSERT INTO webcam_url_links VALUES(?,?,?,?)", (x["id"], uid, link["purpose"], link["is_primary"]))
        if x.get("media_access"):
            access = x["media_access"]
            uid = hashlib.sha256(access["url"].encode()).hexdigest()
            db.execute("INSERT INTO snapshot_access_checks VALUES(?,?,?,?,?,?,?,?)", (x["id"], uid,
                       access["status"], access["checked_at"], access.get("http_status"), access.get("signature"),
                       access["bytes_read"], json.dumps(access, ensure_ascii=False)))
        if x.get("stream_url"):
            sid = hashlib.sha256(x["stream_url"].encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO webcam_streams VALUES(?,?,?,?)", (sid, x["stream_url"], x["format"], json.dumps(h)))
            db.execute("INSERT INTO webcam_stream_links VALUES(?,?)", (x["id"], sid))
    db.executemany("INSERT INTO osm_candidate_links VALUES(?,?,?,?,?,?,?,?,?)",
                   ((m["webcam_id"], m["osm_node_id"], m["distance_m"], m["match_status"], m["operator_hint"], m["operator"], m["name"], m["direction"], m["attribution"]) for m in matches))
    for k, v in {"schema_version": 2, "generated_at": catalog["generated_at"], "report": report,
                 "osm_links_license": OSM_ATTRIBUTION, "proximity_is_identity": False,
                 "data_license_note": "Per-source terms apply. OSM-derived records and candidate associations retain ODbL-1.0. Catalog metadata grants no new rights to linked media."}.items():
        db.execute("INSERT INTO metadata VALUES(?,?)", (k, json.dumps(v)))
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    db.close()
    tmp.replace(path)
    with path.open("rb") as src, path.with_suffix(path.suffix + ".gz").open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=9) as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)


def protect_baseline(baseline, output_paths):
    target = baseline.resolve()
    for path in output_paths:
        if path.resolve() == target:
            raise ValueError("An output would overwrite the read-only OSM baseline")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--fetch", action="store_true", help="Fetch only the 12 official metadata catalogs")
    ap.add_argument("--extra-catalog", type=Path, action="append", default=[],
                    help="Normalized version-1 catalog from an approved additional provider; repeatable")
    ap.add_argument("--osm-db", type=Path, required=True, help="Existing uncompressed surveillance DB, opened read-only")
    ap.add_argument("--health", type=Path, action="append", default=[], help="JSON/JSONL explicit probe evidence; repeatable")
    ap.add_argument("--snapshot-checks", type=Path, action="append", default=[], help="Bounded image access observations, separate from live-video health")
    ap.add_argument("--url-repairs", type=Path, help="Explicit URL corrections with successful manifest evidence")
    ap.add_argument("--out", type=Path, default=Path("data/webcams.json"))
    ap.add_argument("--compact-web", action="store_true", help="Keep full records in SQLite/audit; emit a smaller browser view to --out")
    ap.add_argument("--live-out", type=Path, help="With --compact-web: also write the viewable webcams (HLS, snapshots) the globe loads first")
    ap.add_argument("--db", type=Path, default=Path("db/qp1ng-webcams.sqlite"))
    ap.add_argument("--audit-dir", type=Path, default=Path("reports/webcams"))
    ap.add_argument("--radius", type=float, default=100)
    ap.add_argument("--generated-at", default=None)
    ap.add_argument("--baseline-commit", default=None, help="Commit of the supplied baseline, if known")
    args = ap.parse_args()
    if not 0 < args.radius <= 500:
        ap.error("Matching radius must be 0 < r <= 500 metres")
    if args.live_out and not args.compact_web:
        ap.error("--live-out needs --compact-web")
    outputs = [args.out, args.out.with_suffix(args.out.suffix + ".tmp"), *([args.live_out] if args.live_out else []), args.db,
               args.db.with_suffix(args.db.suffix + ".tmp"), args.db.with_suffix(args.db.suffix + ".gz")]
    outputs += [args.audit_dir / name for name in ("import_report.json", "source_fetches.json", "rejected_records.json", "probe_evidence.json", "probe_parse_warnings.json", "webcams.geojson", "webcams.csv", "osm_candidate_links.csv", "shared_url_groups.json", "published_links.csv", "country_counts.json", "snapshot_access_evidence.json", "privacy_filter.json", "exclusions.json", "duplicates.json")]
    protect_baseline(args.osm_db, outputs + [p.with_suffix(p.suffix + ".tmp") for p in outputs])
    stamp = args.generated_at or utcnow()
    if args.fetch:
        fetch_caltrans(args.source_dir)
    items, provenance, rejected = load_caltrans(args.source_dir, stamp)
    privacy_log, exclusion_log = [], []
    exclusions = load_exclusions()
    extra_items, extra_sources, extra_provenance, extra_rejected = load_extra_catalogs(
        args.extra_catalog, stamp, privacy_log, exclusions, exclusion_log)
    items = sorted(items + extra_items, key=lambda x: x["id"])
    if len({x["id"] for x in items}) != len(items):
        raise ValueError("Duplicate camera identity across providers/catalogs")
    sources = [SOURCE] + extra_sources
    provenance += extra_provenance
    rejected += extra_rejected
    items, swept = privacy_sweep(items, sources)
    privacy_log += swept
    rejected += [{"source": e["provider"], "provider": e["provider"], "provider_id": e["id"].split(":", 1)[-1],
                  "reason": f"Privacy filter: {e['reason']} in {e['field']}"} for e in swept]
    items, excluded = apply_exclusions(items, exclusions["rules"])
    exclusion_log += excluded
    rejected += [{"source": e["provider"], "provider": e["provider"], "provider_id": e["id"].split(":", 1)[-1],
                  "reason": f"Excluded: {e['rule']} (scripts/webcam_exclusions.json)"} for e in excluded]
    items, duplicates = drop_duplicates(items, args.radius)
    rejected += [{"source": e["provider"], "provider": e["provider"], "provider_id": e["id"].split(":", 1)[-1],
                  "reason": f"Duplicate of {e['superseded_by']} ({e['rule']})"} for e in duplicates]
    stray = media_page_records(items)
    if stray:
        raise ValueError(f"{len(stray)} records still give a stream or media file as their page, e.g. {stray[:3]}")
    # A source left without records (an excluded policy) is not listed either.
    kept_providers = {x["provider"] for x in items}
    sources = [s for s in sources if s["id"] in kept_providers]
    probe_parse_warnings = []
    events = load_probe_events(args.health, probe_parse_warnings)
    if args.url_repairs:
        known_events = {json.dumps(e, sort_keys=True) for e in events}
        for event in apply_verified_repairs(items, json.loads(args.url_repairs.read_text())):
            if json.dumps(event, sort_keys=True) not in known_events:
                events.append(event)
    apply_health(items, events)
    snapshot_events = load_probe_events(args.snapshot_checks, probe_parse_warnings)
    snapshot_audit = apply_snapshot_access_checks(items, snapshot_events, PROVIDER_POLICIES)
    baseline_sha = hashlib.sha256(args.osm_db.read_bytes()).hexdigest()
    baseline = sqlite3.connect(args.osm_db.resolve().as_uri() + "?mode=ro", uri=True)
    baseline_rows = baseline.execute("SELECT count(*) FROM surveillance_nodes").fetchone()[0]
    matches = [m for x in items for m in candidate_matches(baseline, x, args.radius)]
    baseline.close()
    n_by_cam = collections.Counter(m["webcam_id"] for m in matches)
    hls = [x for x in items if x["format"] == "hls"]
    url_health = {x["stream_url"]: x["health"]["status"] for x in hls}
    provider_stats = provider_statistics(items, provenance, rejected, events, matches)
    link_stats, shared_urls = link_statistics(items)
    scope = ["All 12 official Caltrans metadata catalogs"]
    scope.extend(f"supplied {s['name']} normalized catalog(s)" for s in sources if s["id"] != SOURCE["id"])
    report = {
        "generated_at": stamp, "baseline_commit": args.baseline_commit,
        # Hashes of the files as committed (LF), whatever line endings the checkout uses.
        "policy_registry_sha256": hashlib.sha256(WORLD_POLICY_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if WORLD_POLICY_PATH.exists() else None,
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "baseline_osm_nodes": baseline_rows, "baseline_db_sha256": baseline_sha,
        "source_records": sum(x["records"] for x in provenance), "accepted_cameras": len(items), "rejected_records": len(rejected),
        "hls_camera_records": len(hls), "distinct_hls_urls": len({x["stream_url"] for x in hls}),
        "snapshot_only_records": sum(x["format"] == "snapshot" for x in items),
        "official_page_records": sum(x["format"] == "official_page" for x in items),
        **link_stats,
        "country_counts": dict(sorted(collections.Counter(x["country"] for x in items).items())),
        "known_country_codes": len({x["country"] for x in items if x["country"] != "ZZ"}),
        "coordinate_role_counts": dict(collections.Counter(x.get("coordinate_role", "camera_location") for x in items)),
        "records_excluded_from_proximity_matching": sum(x.get("coordinate_role") in ("associated_feature", "feature_center", "approximate") for x in items),
        "records_with_untransformed_crs_excluded_from_matching": sum(not wgs84_coordinates(x) for x in items),
        "geojson_null_geometry_records": sum(not wgs84_coordinates(x) for x in items),
        "country_inferred_records": sum(bool(x.get("country_inferred")) for x in items),
        "unclassified_video_urls": sum(bool(x["unclassified_video_url"]) for x in items),
        "invalid_source_video_urls": sum(x["invalid_source_video_url"] for x in items),
        "verified_url_repairs_adopted": sum(bool(x.get("url_repair")) for x in items),
        "provider_in_service_false": sum(x["provider_in_service"] is False for x in items),
        "health_camera_counts": dict(collections.Counter(x["health"]["status"] for x in items)),
        "hls_health_counts": dict(collections.Counter(x["health"]["status"] for x in hls)),
        "hls_url_health_counts": dict(collections.Counter(url_health.values())),
        "provider_counts": dict(collections.Counter(x["provider"] for x in items)), "provider_stats": provider_stats,
        "probe_events": len(events), "incomplete_probe_events": sum(incomplete_probe(e) for e in events),
        "completed_probe_events": sum(not incomplete_probe(e) for e in events),
        "attempted_distinct_hls_urls": sum(s["attempted_distinct_hls_urls"] for s in provider_stats.values()),
        "probed_distinct_hls_urls": sum(s["probed_distinct_hls_urls"] for s in provider_stats.values()),
        "probe_parse_warning_count": len(probe_parse_warnings), "probe_evidence_import_complete": not probe_parse_warnings,
        "snapshot_access_events": len(snapshot_audit["accepted_events"]),
        "snapshot_access_rejected_events": len(snapshot_audit["rejected_events"]),
        "snapshot_access_status_counts": snapshot_audit["status_counts"],
        "matching_radius_m": args.radius, "osm_candidate_links": len(matches),
        "cameras_with_osm_candidate": len(n_by_cam), "cameras_with_multiple_osm_candidates": sum(n > 1 for n in n_by_cam.values()),
        "hls_cameras_with_osm_candidate": sum(x["id"] in n_by_cam for x in hls),
        "cameras_without_osm_candidate": len(items) - len(n_by_cam),
        "identity_merges_performed": 0, "original_osm_rows_modified": 0,
        "privacy_filter": privacy_summary(privacy_log),
        "exclusions": exclusion_summary(exclusions, exclusion_log),
        "duplicates": duplicate_summary(duplicates, args.radius),
        "scope": "; ".join(scope) + ". Only these approved sources are included; this is not a complete worldwide catalog.",
        "scope_providers": [s["id"] for s in sources],
        "scope_countries": sorted({x["country"] for x in items}),
        "health_note": "A published URL is not verified live. Checks are point-in-time collector-network observations; replay/placeholder imagery and device compatibility require separate assessment.",
        "count_note": "Records describe published cameras, views/presets or associated places. They are not a count of distinct physical cameras. URLs are deduplicated in published_urls; shared links never imply identity. External pages authorize no media embedding.",
    }
    catalog = {"schema_version": 2, "generated_at": stamp, "sources": sources, "items": items}
    view = viewer_catalog(catalog) if args.compact_web else catalog
    write_json(args.out, view)
    if args.live_out:
        write_json(args.live_out, live_view_catalog(view, args.out.as_posix() if not args.out.is_absolute() else "data/webcams.json"))
    write_json(args.audit_dir / "import_report.json", report)
    write_json(args.audit_dir / "source_fetches.json", provenance)
    write_json(args.audit_dir / "rejected_records.json", rejected)
    write_json(args.audit_dir / "probe_evidence.json", events)
    write_json(args.audit_dir / "probe_parse_warnings.json", probe_parse_warnings)
    write_json(args.audit_dir / "snapshot_access_evidence.json", snapshot_audit)
    write_json(args.audit_dir / "privacy_filter.json", {**privacy_summary(privacy_log), "entries": privacy_log})
    write_json(args.audit_dir / "exclusions.json", {**exclusion_summary(exclusions, exclusion_log), "entries": exclusion_log})
    write_json(args.audit_dir / "duplicates.json", {**duplicate_summary(duplicates, args.radius), "entries": duplicates})
    write_json(args.audit_dir / "shared_url_groups.json", shared_urls)
    write_json(args.audit_dir / "country_counts.json", report["country_counts"])
    write_json(args.audit_dir / "webcams.geojson", {"type": "FeatureCollection", "features": [geojson_feature(x) for x in items]})
    write_csv(args.audit_dir / "webcams.csv", ({**x, "coordinate_crs": coordinate_crs(x), "health_status": x["health"]["status"], "health_checked_at": x["health"].get("checked_at")} for x in items),
              ["id", "provider", "provider_id", "name", "lat", "lng", "country", "region", "district", "road", "direction", "format", "stream_url", "snapshot_url", "official_page", "reference_url", "reference_hls_url", "reference_snapshot_url", "reported_clip_url", "coordinate_role", "coordinate_crs", "location_group_id", "metadata_license", "media_rights", "rights_status", "provider_in_service", "health_status", "health_checked_at", "image_observed_at", "requires_catalog_refresh", "source_catalog", "attribution"])
    write_csv(args.audit_dir / "published_links.csv", ({"webcam_id": x["id"], "provider": x["provider"],
              "country": x["country"], "rights_status": x["rights_status"], **link} for x in items for link in published_links(x)),
              ["webcam_id", "provider", "country", "url", "purpose", "is_primary", "rights_status"])
    write_csv(args.audit_dir / "osm_candidate_links.csv", matches,
              ["webcam_id", "osm_node_id", "distance_m", "operator", "name", "direction", "match_status", "identity_confirmed", "operator_hint", "attribution"])
    write_database(args.db, catalog, matches, report)
    if hashlib.sha256(args.osm_db.read_bytes()).hexdigest() != baseline_sha:
        raise RuntimeError("Baseline was unexpectedly modified")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
