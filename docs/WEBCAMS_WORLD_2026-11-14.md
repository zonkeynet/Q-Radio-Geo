# Worldwide webcam catalog — 14 November 2026

Generated at **2026-11-14T02:13:27+00:00**. This report supersedes the dated two-provider catalog in
`WEBCAMS_2026-11-13.md`. The original surveillance database remains unchanged.
The companion SQLite database and WEBCAMS viewer data have been rebuilt locally;
the remote repository and hosted globe have not been updated by this work.

## Results and counting rules

| Metric | Integrated result |
| --- | ---: |
| Camera/view/place records | 33,991 |
| Previous records preserved | 4,523 |
| Additional records | 29,468 |
| Reviewed source policies | 35 |
| Country/territory codes, excluding unknown | 77 |
| Records with country not assigned | 323 |
| Distinct primary viewing URLs | 29,617 |
| Distinct published URLs, including supporting references | 38,666 |
| HLS records / distinct enabled HLS URLs | 2,453 / 2,446 |
| Snapshot records | 12,728 |
| External-page records | 18,810 |
| Additional HLS reference URLs, not enabled in the player | 472 |
| Distinct published HLS URLs across all rights states | 2,918 |
| Distinct MP4 clip references | 900 |

A record can be a view/preset, an independently published directory reference,
or a place associated with a camera. It is **not a count of distinct physical
cameras**. Every primary URL is deduplicated separately from camera identity.
416 groups share a primary URL across 4,790 records; some are statewide maps,
some are repeated links, and some represent several views. Query strings are
preserved, including provider tokens and image-version parameters. No URL
similarity or 100-metre proximity is used to merge physical camera identities.

The 38,666-URL count includes alternative images, viewing pages, HLS references
and short MP4 clips. The primary-link count is the more useful number when
comparing directory coverage. Neither count implies current availability.

## Sources actually incorporated

| Source group | Records |
| --- | ---: |
| Caltrans, all 12 districts | 3,612 |
| Norway, Statens vegvesen | 911 |
| OpenStreetMap explicit webcam tags | 10,218 |
| Wikidata P4238 webcam-page references | 686 |
| Other US sources: Oregon, Maryland, Delaware, Austin, Washington | 4,536 |
| Canadian sources: Québec, DriveBC, Vancouver, Toronto, Calgary, Surrey | 3,210 |
| New European sources: Finland, Iceland, Open Data Hub, London, Madrid, Vigo, Lyon | 5,358 |
| Asia/Oceania sources admitted after review | 5,460 |

The complete per-provider and per-country counts are in `import_report.json`
and `country_counts.csv`. APAC includes Taiwan (Highway Bureau and city
catalogs), Hong Kong, Singapore, Queensland, NSW, Shizuoka, Fukui, Hanle IAO,
Semarang and Bandung. Community-directory entries extend coverage into Africa,
Latin America, the Middle East and other territories.

Metadata licenses and media rights are separate fields. Approved snapshots load
only after an explicit user action. `official_page_only` records have no enabled
stream or image URL; their published media references remain in the database
for review. Public directory references for which no open media licence was
established are never promoted to an embedded feed.

### Sources held back or filtered

- 313 NZTA API records are retained as research only: the Traffic and Travel API
  terms require registration/acceptance for republication of the information.
  A metadata-only page label does not remove that condition. Independently
  acquired OSM/Wikidata references in New Zealand remain community metadata;
  they do not incorporate or enable the excluded NZTA API catalog.
- 96 DGAC Chile airport-camera links at 49 airports remain candidates because
  open metadata reuse was not established. Their coordinates describe airport
  reference points, not individual camera positions.
- Open Data Hub: 745 of 1,995 raw records were filtered for absent/closed licence
  metadata or missing/invalid/inconsistent coordinates. 1,250 were admitted.
- Americas: 186 Austin records not marked TURNED_ON were excluded. Surrey had
  20 records without a usable link/coordinate join and five exact URL aliases.
- Global directories: 251 unsuitable URL values were rejected; rejected values
  are represented by hashes in the distributed audit. No exposed-IP camera
  endpoints or credentials are included in the public viewing catalog.
- Sources requiring API credentials, agreements or unavailable downloads remain
  in the research register. No blocked API or disabled camera was bypassed.

Counts above have different units and must not be added as a total exclusion
count. No claim of exhaustive worldwide coverage is made.

## Verification and known availability

All 4,523 previous records remain present. Their **entire HLS health objects are
unchanged**. There are 81 distinct HLS URLs with dated positive observations
(54 Caltrans and 27 Norway), all from 13 November 2026. There are 159 retained
probe events. Other HLS URL states remain: 11 playlist-only checks, 25 network
inconclusive, nine unavailable at the last check and 2,320 not checked.

A new bounded sample on 14 November covered one snapshot from each of 14 new
providers, reading at most 64 KiB per request with two concurrent requests and
no image retention. Ten returned image signatures (nine JPEG, one PNG); two
returned 403, one returned 404, and one timed out. The results are stored in
`snapshot_access_checks` and the per-record `media_access` object, separately
from live-video health. They say nothing about image freshness or other
cameras belonging to that provider. Toronto returned PNG bytes despite a .jpg
URL and image/jpeg content type; the image viewer does not rely on the suffix.

Hong Kong's published service notice is visible on each card. Singapore's eight
URLs point to dated images; the timestamp and need to refresh the catalog are
visible. Taiwan's minimum image retrieval interval is enforced by an in-memory
per-URL cooldown. There is no automatic image refresh.

No full browser/device decoding certification or all-URL availability sweep has
been performed. No scheduled refresh job is activated by this change.

## Coordinates and comparison with the existing database

The original **585,541-row surveillance-node** database is opened read-only. Its
SHA256 remains:

`04efcf12bf90fb113038a36765d77ef7cb273923eea93c0283a080436fcb34d2`

The 100-metre comparison yields **22,846 candidate pairs** involving **11,255
webcam records**; 3,398 records have more than one candidate. There are 336 HLS
records with a candidate. These links remain `geographic_candidate_only` with
`identity_confirmed=false`. No original OSM rows were changed and no physical
camera identities were merged.

Associated places, feature centres and explicitly approximate coordinates do
not participate in precision matching. Country inference from Natural Earth
1:10m polygons is marked as approximate and never changes camera coordinates;
323 records remain country=ZZ where assignment was not established.

Queensland supplies 259 records in GDA2020/EPSG:7844. Their original datum is
retained and shown in the viewer; no silent WGS84 transformation is asserted.
They are excluded from proximity matching. The standards-compliant GeoJSON
export retains these records with `geometry: null` and exact native coordinates
under `properties.source_coordinates`. SQLite and CSV preserve all native
coordinates with an explicit CRS. The globe renders their supplied angular
coordinates with the datum note visible. The other 33,732 GeoJSON records have
point geometry.

## Database and viewer

SQLite schema version 2 contains `sources`, `public_webcams`, `published_urls`,
`webcam_url_links`, `webcam_streams`, `webcam_stream_links`,
`snapshot_access_checks`, `osm_candidate_links` and `metadata`.

`published_urls.url` is unique, while record-to-URL associations retain purpose:
HLS, snapshot, page, reference-only or clip-reference-only. Each camera record
retains the full normalized JSON, attribution, provenance, coordinate role,
original datum, provider status and dated observations. Source-wide license
information is also stored separately. Original Maryland license metadata is
preserved byte-for-byte in `data/webcam-source-metadata/`.

`data/webcams.json` is a smaller schema-2 viewer projection (about 18.6 MB);
full records remain in SQLite and GeoJSON. Licence and attribution strings are
inherited from sources instead of repeated in every viewer item. All 33,991
records pass frontend preparation with no requests to camera providers.

Country filters are generated from the imported records. Web references use a
WEB LINK label; pages are never assumed to be continuous video. In the current
Android app, HLS uses the existing native TV bridge, snapshots use an explicit
image action, and external pages display a selectable address. The WebView's
existing external-navigation restrictions remain material to those page links.

## Validation

- 62 Python tests and 15 Node tests pass.
- SQLite integrity_check: ok; foreign_key_check: no errors.
- 33,991 unique record IDs and 38,666 unique published URLs.
- Zero rejected rows in the final approved-catalog build.
- All prior health objects preserved; new catalog rows cannot import their own
  live claims or media-access evidence.
- 14 accepted image-access observations, zero rejected observations.
- Metadata-only page rows have null media fields in the complete database.
- Unsupported media hosts/HTTP are rejected by the new provider adapters.
- Source policy prevents promotion of approximate coordinates to exact-camera
  coordinates. The matcher handles the antimeridian and excludes native CRSs.
- No camera provider is contacted by catalog parsing, filters or card creation.

The browser runtime available to this task could not execute a real Chromium
playback test; the checks above are unit, import and database validations.

## Rebuild the dated snapshot

The evidence package contains all normalized inputs needed for an offline
rebuild, Caltrans originals, exact retained video checks and the snapshot sample.
After applying its cumulative code patch to baseline
`368aed28bc4f9e4aeb80b56af9256937774c7d5c`, run the builder from the extracted
package directory, replacing the two repository/database paths:

```bash
python /path/to/Q-Radio-Geo/scripts/build_webcams.py \
  --source-dir inputs/caltrans \
  --extra-catalog inputs/vegvesen.json \
  --extra-catalog inputs/emea.json \
  --extra-catalog inputs/global.json \
  --extra-catalog inputs/americas.json \
  --extra-catalog inputs/apac.json \
  --osm-db /path/to/original-surveillance.sqlite \
  --health inputs/prior_video_checks.json \
  --snapshot-checks inputs/snapshot_sample_checks.json \
  --url-repairs inputs/url_repairs.json \
  --generated-at '2026-11-14T02:13:27+00:00' \
  --baseline-commit 368aed28bc4f9e4aeb80b56af9256937774c7d5c \
  --compact-web --out regenerated/webcams.json \
  --db regenerated/qp1ng-webcams.sqlite --audit-dir regenerated/audit
```

Python 3.10+ standard library; Node.js 18+ for tests. Use separate work/output
paths when rebuilding. Do not replace input files with freshly fetched metadata
if reproducing these dated counts. Provider adapters and registry changes require
review before admitting a new source or media origin.

## Primary source references

- Caltrans: https://cwwp2.dot.ca.gov/documentation/cctv/cctv.htm
- Norway: https://dataut.vegvesen.no/dataset/webkamera
- OSM tags and licence: https://wiki.openstreetmap.org/wiki/Webcams and https://www.openstreetmap.org/copyright
- Wikidata: https://www.wikidata.org/wiki/Property:P4238 and https://www.wikidata.org/wiki/Wikidata:Licensing
- Finland: https://www.digitraffic.fi/en/terms-of-service/
- Iceland: https://www.vegagerdin.is/vegagerdin/gagnasafn/vefthjonustur/skilmalar-vefthjonustur
- Open Data Hub: https://docs.opendatahub.com/licensing/
- Oregon: https://tripcheck.com/Pages/Frequently-Asked-Questions
- Taiwan: https://thbapp.thb.gov.tw/opendata/
- NZTA restriction: https://nzta.govt.nz/about-us/our-data-and-official-information/use-our-data/terms-of-use
- Full provider URLs and attribution: `sources` in the SQLite database / reviewed registry.
