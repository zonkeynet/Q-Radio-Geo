#!/usr/bin/env python3
"""Offline adapters for reviewed reference catalogs, AviationWX and GeoNet.

Inputs are downloaded separately with receipts. No camera or page is requested.
Upstream health claims and dataset licences never authorize embedded media.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import urljoin, urlsplit
from build_webcams import page_url, published_links

LES_REPO = "https://github.com/william-ricchiuti/Live-Environment-Streams"
LES_COMMIT = "462171be74a94963277dd76c8b2f8cd18f928cda"
LES_RAW = f"https://raw.githubusercontent.com/william-ricchiuti/Live-Environment-Streams/{LES_COMMIT}/"
# Individually reviewed public operator origins. Sources already represented by
# complete official inputs are excluded, even if an old aggregate has new aliases.
LES_HOSTS = {
    "vdot": [f"media-sfs{i}.vdotcameras.com" for i in range(1, 9)],
    "mndot": ["video.dot.state.mn.us"],
    "seattle_sdot": ["61e0c5d388c2e.streamlock.net"],
    "ladotd_511": ["itsstreamingbr2.dotd.la.gov", "itsstreamingbr.dotd.la.gov", "itsstreamingno.dotd.la.gov"],
    "goakamai_hdot": ["cdn3.wowza.com"],
    "trafficvision": ["streaming1.highwaytraffic.go.th", "streaming2.highwaytraffic.go.th"],
    "tdx_city_cctv": ["cctv.klcg.gov.tw"],
    "atcs-bandung": ["atcs-dishub.bandung.go.id"],
    "atcs-cianjur": ["atcs.cianjurkab.go.id"],
    "atcs-denpasar": ["atcs.denpasarkota.go.id"],
    "atcs-palembang": ["stream.palembang.go.id"],
    "atcs-pekanbaru": ["cctv.pekanbaru.go.id"],
    "atcs-tasikmalaya": ["atcs.tasikmalayakota.go.id"],
    "cctv-cirebon": ["cctv.cirebonkota.go.id"],
    "cctv-jogjakota": ["cctvjss.jogjakota.go.id"],
    "cctv-kebumen": ["cctv.kebumenkab.go.id"],
    "cctv-magelang": ["restreamer.magelangkota.go.id", "dev.cctv.magelangkota.go.id"],
    "cctv-padang": ["streamcctv.padang.go.id"],
    "cctv-salatiga": ["restreamer.salatiga.go.id"],
    "cctv-wonosobo": ["mata.wonosobokab.go.id"],
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def receipted(folder, name):
    body = (folder / name).read_bytes()
    receipt = json.loads((folder / (name + ".receipt.json")).read_text())
    if receipt.get("status") != 200 or hashlib.sha256(body).hexdigest() != receipt.get("sha256"):
        raise ValueError(f"Missing successful matching receipt for {name}")
    return json.loads(body), receipt


def policy(provider, name, url, catalog, terms, metadata, media, attribution,
           countries, hosts=(), page_hosts=(), formats=("official_page",), role="approximate", **extra):
    source = {"id": provider, "name": name, "url": url, "catalog_url": catalog,
              "terms_url": terms, "metadata_license": metadata, "license": metadata,
              "media_rights": media, "rights_note": media, "attribution": attribution,
              "rights_status": "official_public_feed" if "snapshot" in formats else "official_page_only",
              "allowed_hosts": list(hosts), **extra}
    return {"source": source, "media_hosts": list(hosts), "page_hosts": list(page_hosts),
            "formats": list(formats), "countries": countries, "force_coordinate_role": role,
            "operator_hints": []}


def base(provider, native_id, name, lat, lng, country, receipt, source, **extra):
    lat, lng = float(lat), float(lng)
    if not all(map(math.isfinite, [lat, lng])) or not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == lng == 0):
        raise ValueError("Invalid published coordinates")
    return {"id": f"{provider}:{native_id}", "provider": provider, "provider_id": native_id,
            "name": name, "lat": lat, "lng": lng, "country": country,
            "coordinate_reference_system": "EPSG:4326", "coordinate_role": "approximate",
            "format": "official_page", "rights_status": "official_page_only",
            "stream_url": None, "snapshot_url": None, "source_page": source["url"],
            "source_catalog": receipt["url"], "observed_at": receipt["observed_at"],
            "source_sha256": receipt["sha256"], **extra}


def geonet_timestamp(value):
    """Convert the provider's explicit NZDT/NZST label without locale guessing."""
    if not isinstance(value, str): return None
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*([ap]m)\s*\((NZDT|NZST)\)\s*(\d{1,2})\s*([A-Za-z]{3})\s*(\d{4})\s*", value)
    if not m: return None
    hour, minute, half, zone, day, month, year = m.groups()
    months = {v:i+1 for i,v in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
    try:
        if not 1 <= int(hour) <= 12: return None
        stamp = dt.datetime(int(year), months[month], int(day), int(hour) % 12 + (12 if half == "pm" else 0), int(minute),
                            tzinfo=dt.timezone(dt.timedelta(hours=13 if zone == "NZDT" else 12)))
    except (ValueError, KeyError): return None
    return stamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def geonet_rows(data, receipt, source):
    """This specific official feed uses EPSG latitude,longitude axis order.

    Its repeated volcano collections can share one camera ID. Different camera
    IDs at one station remain distinct. Reject contradictions, never guess axes.
    """
    seen, rows = {}, []
    for group in data:
        for feature in group["features"]:
            camera_id = feature["id"]
            lat, lng = map(float, feature["geometry"]["coordinates"])
            if not (-49 <= lat <= -28 and (165 <= lng <= 180 or -180 <= lng <= -175)):
                raise ValueError("GeoNet feed no longer has the reviewed NZ latitude/longitude order")
            props = feature["properties"]
            image = page_url(urljoin("https://images.geonet.org.nz/volcano/cameras/", props["latest-image-large"]))
            if not image or urlsplit(image).hostname != "images.geonet.org.nz":
                raise ValueError("GeoNet image outside the reviewed host")
            signature = (lat, lng, image)
            if camera_id in seen:
                if seen[camera_id] != signature:
                    raise ValueError("Contradictory duplicate GeoNet camera ID")
                continue
            seen[camera_id] = signature
            rows.append(base("geonet_volcano", camera_id, props["title"], lat, lng, "NZ", receipt, source,
                format="snapshot", rights_status="official_public_feed", snapshot_url=image,
                coordinate_role="station_location", official_page="https://www.geonet.org.nz/volcano/cameras",
                coordinate_transform_applied="Axis-order normalization only: source [latitude, longitude]",
                source_coordinates=feature["geometry"]["coordinates"], source_coordinate_axis_order="latitude,longitude",
                provider_image_timestamp=props.get("latest-timestamp"), image_observed_at=geonet_timestamp(props.get("latest-timestamp")),
                direction=props.get("azimuth"),
                minimum_refresh_seconds=600))
    return rows


def normalize(root, baseline_db, known_catalogs):
    agg, extra = root / "aggregators", root / "extra"
    policies, rows, skipped = {}, [], []
    with sqlite3.connect(f"file:{baseline_db}?mode=ro", uri=True) as db:
        known = {r[0] for r in db.execute("SELECT url FROM published_urls")}
    for path in known_catalogs:
        for row in json.loads(path.read_text()).get("items", []):
            known.update(u for link in published_links(row) if (u := page_url(link["url"])))

    data, receipt = receipted(agg, "live-environment-streams-streams.geojson")
    source_info, _ = receipted(agg, "live-environment-streams-sources.json")
    seen = {}
    for feature in data["features"]:
        p = feature["properties"]
        family, raw_url = p["source_family"], p["url"]
        url = page_url(raw_url)
        reason = None
        if family not in LES_HOSTS: reason = "official_input_preferred_or_family_not_approved"
        elif p.get("coordinates_quality") == "country_centroid": reason = "country_centroid_not_camera_position"
        elif not url or urlsplit(url).hostname not in LES_HOSTS[family]: reason = "url_outside_reviewed_family_origins"
        elif url in known: reason = "url_already_represented_by_existing_or_primary_input"
        if reason:
            skipped.append({"source": "live_environment_streams", "family": family, "reason": reason,
                            "value_sha256": hashlib.sha256(raw_url.encode()).hexdigest()})
            continue
        lng, lat = feature["geometry"]["coordinates"]
        identity = hashlib.sha256(url.encode()).hexdigest()[:24]
        provider = "les_" + family.replace("-", "_")
        key = (provider, identity)
        if key in seen:
            if seen[key] != (lat, lng): raise ValueError("Conflicting positions for one aggregate URL")
            skipped.append({"source": "live_environment_streams", "family": family,
                            "reason": "identical_url_and_position", "value_sha256": hashlib.sha256(raw_url.encode()).hexdigest()})
            continue
        seen[key] = (lat, lng)
        info = source_info[family]
        if provider not in policies:
            policies[provider] = policy(provider, info["full_name"] + " — published references via Live Environment Streams",
                LES_REPO, LES_RAW + "streams.geojson", LES_REPO + "/blob/" + LES_COMMIT + "/LICENSE",
                "CC-BY-4.0 (Live Environment Streams metadata); operator media rights separate",
                "External references only. The dataset grants no licence to footage; no embedded playback authorized.",
                "Live Environment Streams (William Ricchiuti), CC BY 4.0; " + p["attribution"] + ". Metadata normalized by QGlobe.",
                [p["country_code"]], page_hosts=LES_HOSTS[family], license_url="https://creativecommons.org/licenses/by/4.0/",
                upstream_terms_url=info.get("terms_url"), upstream_operator_url=info.get("website"),
                dataset_version="4.0.0", dataset_commit=LES_COMMIT,
                coordinate_note="Aggregate quality labels are not independently verified camera positions.")
        rows.append(base(provider, identity, p["name"], lat, lng, p["country_code"], receipt, policies[provider]["source"],
            official_page=url, reference_url=url, reported_media_format=p.get("url_type"),
            upstream_source_family=family, upstream_attribution=p["attribution"],
            upstream_coordinate_quality=p.get("coordinates_quality"),
            upstream_reported_status=p.get("status"), upstream_reported_check_at=p.get("last_verified"),
            upstream_health_trusted=False, identity_basis="published_reference_url_hash"))

    # LiveTrafficCam explicitly publishes reusable factual camera references and
    # asks clients to retain agency attribution. The repository's CC-BY licence
    # covers its authored registry/docs, not these generated agency rows. Keep
    # that narrower basis explicit and admit only FAA public page references.
    tcs, tcs_receipt = receipted(agg, "traffic-camera-sources-data__cameras.geojson")
    provider = "livetraf_faa_links"
    policies[provider] = policy(provider, "FAA WeatherCams page references via LiveTrafficCam",
        "https://github.com/bzsasson/traffic-camera-sources", tcs_receipt["url"],
        "https://bzsasson.github.io/traffic-camera-sources/api.html",
        "Public factual camera references under LiveTrafficCam API reuse conventions; retain FAA attribution. Repository CC-BY grant does not cover generated camera rows.",
        "External FAA page references only; no images licensed or embedded by this adapter.",
        "Camera: FAA WeatherCams. References aggregated by LiveTrafficCam (https://livetrafficcam.com/); metadata normalized by QGlobe.",
        ["US"], page_hosts=["weathercams.faa.gov"], role="approximate",
        coordinate_note="Positions and US states reported by the aggregate; not independently surveyed camera mounts.")
    faa_seen = set()
    for feature in tcs["features"]:
        p = feature["properties"]
        if p.get("attribution") != "Camera: FAA WeatherCams": continue
        url = page_url(p.get("official_url"))
        match = re.fullmatch(r"https://weathercams\.faa\.gov/cameras/cameraSite/(\d+)/details/camera/(\d+)", url or "")
        if not match or url in known or url in faa_seen:
            skipped.append({"source":"livetraf_faa_links", "source_record_id":p.get("id"),
                            "reason":"missing_specific_public_page_or_already_represented"})
            continue
        faa_seen.add(url)
        lng, lat = feature["geometry"]["coordinates"]
        rows.append(base(provider, ".".join(match.groups()), p["name"], lat, lng, "US", tcs_receipt,
            policies[provider]["source"], official_page=url, region=p.get("state"),
            source_generated_at=tcs.get("generated_at"), upstream_reported_status=p.get("live_status"),
            upstream_reported_check_at=p.get("last_live_at"), upstream_health_trusted=False,
            upstream_aggregate_id=p.get("id"), identity_basis="published_FAA_site_and_camera_identifiers"))

    geo, geo_receipt = receipted(extra, "geonet-cameras.json")
    policies["geonet_volcano"] = policy("geonet_volcano", "GeoNet volcano cameras, New Zealand",
        "https://www.geonet.org.nz/data/types/camera", geo_receipt["url"], "https://www.geonet.org.nz/policy",
        "CC-BY-3.0-NZ", "GeoNet data and images published under CC BY 3.0 NZ; preserve attribution and image timestamp.",
        "GeoNet / Earth Sciences New Zealand; sponsors NHC, LINZ, NEMA and MBIE. CC BY 3.0 NZ. Webcam data DOI: 10.21420/vq6s-w222. Metadata normalized by QGlobe.",
        ["NZ"], hosts=["images.geonet.org.nz"], formats=["snapshot"], role="station_location",
        license_url="https://creativecommons.org/licenses/by/3.0/nz/", minimum_refresh_seconds=600)
    rows.extend(geonet_rows(geo, geo_receipt, policies["geonet_volcano"]["source"]))

    av, av_receipt = receipted(extra, "aviationwx-webcams.json")
    for provider, partner in [("aviationwx", False), ("aviationwx_partner_links", True)]:
        policies[provider] = policy(provider, "AviationWX " + ("partner camera references" if partner else "airport weather cameras"),
            "https://api.aviationwx.org/", av_receipt["url"], "https://api.aviationwx.org/",
            "AviationWX public API terms; attribution required",
            "Partner camera media retained as external references only." if partner else "Public API explicitly provides weathercam images and bulk directory metadata; attribution and rate limits apply.",
            "Weather data from AviationWX.org. Metadata normalized by QGlobe.", ["US", "CA"],
            hosts=[] if partner else ["api.aviationwx.org"], formats=["official_page"] if partner else ["snapshot"],
            role="associated_feature", minimum_refresh_seconds=60,
            anonymous_limits={"requests_per_minute":50,"requests_per_hour":500,"requests_per_day":2000},
            coordinate_note="Published airport reference point, not an independently located camera.")
    for airport in av["airports"]:
        if airport.get("unlisted") or airport.get("maintenance"):
            skipped.append({"source":"aviationwx","airport_id":airport["id"],"reason":"unlisted_or_maintenance"})
            continue
        for cam in airport.get("webcams", []):
            own = cam.get("operator") == "aviationwx"
            provider = "aviationwx" if own else "aviationwx_partner_links"
            url = page_url(cam["image_url"])
            if not url or urlsplit(url).hostname != "api.aviationwx.org": raise ValueError("Unexpected AviationWX image origin")
            rows.append(base(provider, f"{airport['id']}.{cam['index']}", cam["name"], airport["lat"], airport["lon"],
                airport["country"], av_receipt, policies[provider]["source"],
                format="snapshot" if own else "official_page", rights_status="official_public_feed" if own else "official_page_only",
                snapshot_url=url if own else None, official_page=airport["url"], reference_url=None if own else url,
                coordinate_role="associated_feature", airport_id=airport["id"], airport_name=airport["name"],
                upstream_operator=cam.get("operator"), region=airport.get("region_name"),
                image_observed_at=cam.get("captured_at_iso"), minimum_refresh_seconds=max(60, cam.get("refresh_seconds", 60)),
                provider_in_service=None, direction=cam.get("approximate_heading")))

    # The documentation identifies these coordinates as intersection centres.
    # The public metadata endpoint is keyless; image access requires registration.
    ott, ott_receipt = receipted(extra, "ottawa-cameras.json")
    provider = "ottawa_traffic_links"
    policies[provider] = policy(provider, "City of Ottawa traffic camera metadata",
        "https://traffic.ottawa.ca/en/opendata", ott_receipt["url"], "https://traffic.ottawa.ca/en/opendata",
        "City of Ottawa open-data reuse terms; Open Government Licence",
        "Image API requires a registered certificate. Only the public map is linked; no image endpoint requested or embedded.",
        "Contains information licensed under the Open Government Licence — City of Ottawa. Camera owner retained per record. Metadata normalized by QGlobe.",
        ["CA"], page_hosts=["traffic.ottawa.ca"], role="associated_feature",
        coordinate_note="The provider documents map coordinates as intersection centres, not camera poles.")
    for cam in ott["cameras"]:
        rows.append(base(provider, str(cam["id"]), cam["name"], cam["latitude"], cam["longitude"], "CA", ott_receipt,
            policies[provider]["source"], official_page="https://traffic.ottawa.ca/en/traffic-map-data-lists-and-resources/traffic-map",
            coordinate_role="associated_feature", camera_number=cam["camera_number"], camera_owner=cam.get("cameraOwner"),
            name_french=cam.get("name_french"), link_scope="shared_public_map", camera_specific_url_available=False))

    used = {r["provider"] for r in rows}
    policies = {k:v for k,v in policies.items() if k in used}
    rows.sort(key=lambda r:r["id"])
    if len({r['id'] for r in rows}) != len(rows): raise ValueError("Duplicate normalized IDs")
    return {"schema_version":1,"sources":[p["source"] for p in policies.values()],"items":rows}, policies, skipped


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir",type=Path,required=True)
    ap.add_argument("--baseline-db",type=Path,required=True)
    ap.add_argument("--known-catalog",type=Path,action="append",default=[])
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    catalog,policies,skipped=normalize(args.source_dir,args.baseline_db,args.known_catalog)
    write(args.out,catalog)
    write(args.out.with_name("proposed_policies.json"),policies)
    write(args.out.with_name("exclusions.json"),skipped)
    summary={"records":len(catalog["items"]),"by_provider":dict(collections.Counter(r["provider"] for r in catalog["items"])),
             "by_format":dict(collections.Counter(r["format"] for r in catalog["items"])),
             "excluded":dict(collections.Counter(r["reason"] for r in skipped)),"media_requests":0,
             "upstream_health_promotions":0,"aggregate_positions":"approximate; excluded from precision matching"}
    write(args.out.with_name("summary.json"),summary)
    print(json.dumps(summary,indent=2))


if __name__ == "__main__": main()
