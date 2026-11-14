#!/usr/bin/env python3
"""Collect/normalize the official Norwegian CCTV publication (stdlib only).

Offline by default: --source-dir contains norway_cctv_raw.geojson and
norway_fetch.json, including the original receipt's SHA-256 and UTC timestamp.
--fetch explicitly refreshes those files. Paginated responses use additional
norway_cctv_page_NNN.geojson files and a receipt with a pages array. Media are
never requested. Normalized output is compatible with build_webcams.py
--extra-catalog; provider availability never establishes live health.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import urllib.parse as urls
import urllib.request as request

CATALOG_URL = "https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:CctvSimple/items?f=application%2Fgeo%2Bjson&limit=2000"
CATALOG_HOST = "ogckart-sn1.atlas.vegvesen.no"
CATALOG_PATH = urls.urlsplit(CATALOG_URL).path
RAW_NAME = "norway_cctv_raw.geojson"
RECEIPT_NAME = "norway_fetch.json"
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_PAGES = 20
ATTRIBUTION = ("Contains data under the Norwegian licence for Open Government data (NLOD) "
               "distributed by Statens vegvesen. Metadata normalized by QGlobe.")
SOURCE = {
    "id": "vegvesen", "name": "Statens vegvesen — Norway road cameras",
    "homepage": "https://dataut.vegvesen.no/dataset/webkamera",
    "terms_url": "https://data.norge.no/nlod/en/2.0", "license": "NLOD-2.0",
    "attribution": ATTRIBUTION, "rights_status": "official_public_feed",
    "allowed_media_hosts": ["kamera.vegvesen.no", "kamera.atlas.vegvesen.no"],
    "catalog_url": CATALOG_URL,
    "documentation": "https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/raw/3.1/NPRA_DATEXII_3_1_Specification_WFS-WMS_v1.1.pdf?at=04bd661aa183d8850153a7b547d93a705c233992",
    "commercial_reuse": "permitted_under_NLOD_attribution_and_exclusions",
    "notes": ["Official Webkamera dataset: NLOD; WFS/WMS documentation: openly available images/streams.",
              "Preserve source/license attribution and the metadata modification notice. No provider endorsement.",
              "Provider still-image availability is not an HLS health check.",
              "countyNumber is preserved; orientationDescription is a destination label, not a bearing."],
}


def checked_url(value, host, catalog=False):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError("Invalid official URL")
    u = urls.urlsplit(value)
    if (u.scheme != "https" or u.hostname != host or u.port not in (None, 443)
            or u.username is not None or u.password is not None or u.fragment):
        raise ValueError("URL outside the approved HTTPS origin")
    if catalog and urls.unquote(u.path) != CATALOG_PATH:
        raise ValueError("URL outside the official CCTV collection")
    return value


class CatalogRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, CATALOG_HOST, catalog=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def page_name(index):
    return RAW_NAME if index == 0 else f"norway_cctv_page_{index + 1:03d}.geojson"


def page_info(data, base_url):
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("Expected a GeoJSON FeatureCollection")
    matched, returned = data.get("numberMatched"), data.get("numberReturned")
    if type(matched) is not int or matched < 0 or type(returned) is not int or returned != len(data["features"]):
        raise ValueError("Missing/inconsistent OGC completeness counts")
    links = [link for link in data.get("links", []) if isinstance(link, dict) and link.get("rel") == "next"]
    if len(links) > 1:
        raise ValueError("Ambiguous OGC next-page links")
    following = checked_url(urls.urljoin(base_url, links[0]["href"]), CATALOG_HOST, catalog=True) if links else None
    return matched, following


def validate_pages(pages):
    expected, next_url, count, seen = None, CATALOG_URL, 0, set()
    for receipt, data, _ in pages:
        current = receipt["url"]
        if current != next_url or current in seen:
            raise ValueError("Broken or cyclic pagination chain")
        seen.add(current)
        matched, next_url = page_info(data, receipt["final_url"])
        expected = matched if expected is None else expected
        if matched != expected:
            raise ValueError("Catalog size changed between pages; retry the complete collection")
        count += len(data["features"])
    if not pages or next_url or count != expected:
        raise ValueError("Incomplete catalog: next page missing or numberMatched differs")


def load_pages(folder):
    manifest = json.loads((folder / RECEIPT_NAME).read_text(encoding="utf-8"))
    receipts = manifest.get("pages", [dict(manifest, file=RAW_NAME)])
    if not isinstance(receipts, list) or not 1 <= len(receipts) <= MAX_PAGES:
        raise ValueError("Invalid receipt page count")
    pages, total = [], 0
    for index, original in enumerate(receipts):
        r = dict(original)
        if r.get("file") != page_name(index):
            raise ValueError("Unexpected raw page filename")
        checked_url(r["url"], CATALOG_HOST, catalog=True)
        checked_url(r["final_url"], CATALOG_HOST, catalog=True)
        timestamp = dt.datetime.fromisoformat(r["retrieved_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() != dt.timedelta(0):
            raise ValueError("Receipt must contain an actual UTC retrieval timestamp")
        with (folder / r["file"]).open("rb") as stream:
            body = stream.read(MAX_PAGE_BYTES + 1)
        total += len(body)
        if len(body) > MAX_PAGE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("Catalog exceeds bounded read limit")
        if r.get("status") != 200 or r.get("bytes") != len(body) or r.get("sha256") != hashlib.sha256(body).hexdigest():
            raise ValueError("Receipt status, size or SHA-256 does not match raw catalog")
        pages.append((r, json.loads(body), body))
    validate_pages(pages)
    return pages


def fetch_pages():
    opener = request.build_opener(CatalogRedirect())
    pages, next_url, total, seen = [], CATALOG_URL, 0, set()
    while next_url:
        if len(pages) >= MAX_PAGES or next_url in seen:
            raise ValueError("Pagination limit or cycle")
        seen.add(next_url)
        checked_url(next_url, CATALOG_HOST, catalog=True)
        req = request.Request(next_url, headers={"User-Agent": "QGlobe-public-catalog/1.0", "Accept": "application/geo+json"})
        with opener.open(req, timeout=30) as response:
            final_url = checked_url(response.url, CATALOG_HOST, catalog=True)
            body = response.read(MAX_PAGE_BYTES + 1)
            total += len(body)
            if response.status != 200 or len(body) > MAX_PAGE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("Unsuccessful or oversized catalog response")
            receipt = {"file": page_name(len(pages)), "url": next_url, "final_url": final_url,
                       "status": response.status, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                       "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                       "content_type": response.headers.get("Content-Type")}
        data = json.loads(body)
        pages.append((receipt, data, body))
        _, next_url = page_info(data, final_url)
    validate_pages(pages)
    return pages


def normalize_feature(feature, observed_at):
    if feature.get("type") != "Feature" or feature.get("geometry", {}).get("type") != "Point":
        raise ValueError("Camera must have GeoJSON Point geometry")
    d = feature["properties"]
    camera_id = d.get("cameraId")
    if not isinstance(camera_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", camera_id):
        raise ValueError("Invalid official cameraId")
    point = feature["geometry"]["coordinates"]
    if not isinstance(point, list) or len(point) not in (2, 3) or any(type(x) not in (int, float) for x in point[:2]):
        raise ValueError("Invalid camera coordinates")
    lng, lat = point[:2]
    if not (math.isfinite(lat) and math.isfinite(lng) and 57 <= lat <= 82 and -10 <= lng <= 40):
        raise ValueError("Coordinates outside plausible Norwegian bounds (GeoJSON uses longitude, latitude)")
    snapshot = d.get("stillImageUrl") or None
    video = d.get("videoUrl") or None
    if snapshot:
        checked_url(snapshot, "kamera.atlas.vegvesen.no")
    if video:
        checked_url(video, "kamera.vegvesen.no")
    stream = video if video and d.get("videoEncodingStandard") == "hls" else None
    if stream and not urls.urlsplit(stream).path.lower().endswith(".m3u8"):
        raise ValueError("Declared HLS URL lacks the expected manifest path")
    if not stream and not snapshot:
        raise ValueError("Camera has no published supported media")
    status = d.get("status.stillImageAvailability")
    available = True if status == "videoOrImagesAvailable" else False if isinstance(status, str) and status.startswith("videoOrImagesUnavailable") else None
    direction = d.get("orientationDescription") or ""
    return {
        "id": f"vegvesen:{camera_id}", "provider": "vegvesen", "provider_id": camera_id,
        "name": (d.get("description") or camera_id) + (" — " + direction if direction else ""),
        "lat": lat, "lng": lng, "country": "NO", "region": f"countyNumber:{d.get('countyNumber')}",
        "district": None, "format": "hls" if stream else "snapshot", "stream_url": stream,
        "snapshot_url": snapshot, "source_page": SOURCE["homepage"], "source_catalog": CATALOG_URL,
        "attribution": ATTRIBUTION, "rights_status": "official_public_feed", "observed_at": observed_at,
        "provider_in_service": available, "health": {"status": "unverified"}, "source_status": status,
        "source_updated_at": d.get("lastUpdateTime"), "road_number": d.get("roadNumber"),
        "county_number": d.get("countyNumber"), "orientation_description": direction,
        "orientation_is_bearing": False, "unclassified_video_url": video if video and not stream else None,
        "invalid_source_video_url": False,
    }


def normalize(pages):
    validate_pages(pages)
    items = [normalize_feature(feature, receipt["retrieved_at"])
             for receipt, page, _ in pages for feature in page["features"]]
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Duplicate official cameraId; do not silently discard or merge records")
    return {"schema_version": 1, "sources": [SOURCE], "source_fetches": [r for r, _, _ in pages],
            "items": sorted(items, key=lambda item: item["id"])}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("work/vegvesen"))
    parser.add_argument("--fetch", action="store_true", help="Explicitly refresh only the official bulk metadata catalog")
    parser.add_argument("--out", type=Path, help="Default: SOURCE_DIR/normalizzato.json")
    args = parser.parse_args(argv)
    try:
        pages = fetch_pages() if args.fetch else load_pages(args.source_dir)
        catalog = normalize(pages)
        output = args.out or args.source_dir / "normalizzato.json"
        inputs = [args.source_dir / RECEIPT_NAME] + [args.source_dir / r["file"] for r, _, _ in pages]
        if output.resolve() in {path.resolve() for path in inputs}:
            raise ValueError("Output cannot overwrite raw metadata or retrieval receipts")
        if args.fetch:
            args.source_dir.mkdir(parents=True, exist_ok=True)
            for receipt, _, body in pages:
                (args.source_dir / receipt["file"]).write_bytes(body)
            write_json(args.source_dir / RECEIPT_NAME, {"schema_version": 1, "pages": [r for r, _, _ in pages]})
        write_json(output, catalog)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(output), "records": len(catalog["items"]),
                      "hls": sum(i["format"] == "hls" for i in catalog["items"]), "health": "unverified"}))


if __name__ == "__main__":
    main()
