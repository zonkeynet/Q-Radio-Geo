#!/usr/bin/env python3
"""
Builds the offline SQLite databases of the globe's layers, from the JSON files in data/
(run the scripts/build_*.mjs first). Two files, so each published .gz stays under GitHub's 50 MB
warning size and an app can skip the large one:

db/qp1ng.sqlite: sources (licence of each source), metadata, radio_places, radio_stations,
  sdr_receivers, repeaters, nav_radio_beacons (aviation + maritime radio aids), maritime_lights,
  airports, airport_frequencies, safe_havens (with refugee sites), security_sites (with border
  controls), migrant_incidents, thermal_anomalies, conflict_events, network_interference,
  tor_relays, wifi_hotspots.
db/qp1ng-surveillance.sqlite: sources, metadata, police_stations, surveillance_nodes (cameras).
Every table with positions has a (lat, lon) index.

Usage: python scripts/build_db.py [--data data] [--out db/qp1ng.sqlite]   (also writes the .gz copies, the published ones)
"""
import argparse
import gzip
import shutil
import datetime as dt
import json
import sqlite3
from pathlib import Path

MORSE = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", (
    ".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. "
    "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.").split()))


def morse(ident):
    letters = [MORSE.get(c) for c in (ident or "").upper()]
    return " ".join(letters) if letters and all(letters) else None


SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT, url TEXT, license TEXT, notes TEXT);
CREATE TABLE radio_places (id TEXT PRIMARY KEY, name TEXT, country TEXT, lat REAL, lon REAL,
    station_count INTEGER, precision TEXT);              -- precision: city | region | country
CREATE TABLE radio_stations (id TEXT PRIMARY KEY, place_id TEXT REFERENCES radio_places(id), title TEXT,
    stream_url TEXT, homepage TEXT, codec TEXT, bitrate INTEGER, hls INTEGER, source TEXT);
CREATE TABLE sdr_receivers (id TEXT PRIMARY KEY, name TEXT, type TEXT, url TEXT, lat REAL, lon REAL, place TEXT,
    bands TEXT, channels INTEGER, snr INTEGER, antenna TEXT, featured INTEGER, source TEXT);
CREATE TABLE repeaters (id TEXT PRIMARY KEY, callsign TEXT, frequency_mhz REAL, offset_mhz REAL, input_mhz REAL,
    modes TEXT, band TEXT, tone TEXT, squelch TEXT, network TEXT, node TEXT, city TEXT, lat REAL, lon REAL,
    power TEXT, range_km INTEGER, restricted TEXT, notes TEXT, website TEXT, source TEXT);
CREATE TABLE nav_radio_beacons (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,       -- 'MARITIME' or 'AVIATION'
    sub_type TEXT NOT NULL,     -- 'VOR', 'VOR-DME', 'VORTAC', 'TACAN', 'DME', 'NDB', 'NDB-DME', 'RACON', 'RADIOBEACON', 'DGPS'
    ident TEXT, name TEXT,
    frequency_khz REAL,         -- kHz (115200 for a VOR, 343 for an NDB)
    channel TEXT,               -- DME/TACAN channel ('42X')
    morse_code TEXT,
    lat REAL NOT NULL, lon REAL NOT NULL,
    elevation_m REAL, range_nm REAL, country TEXT, remarks TEXT,
    source TEXT);
CREATE TABLE maritime_lights (id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, characteristic TEXT,
    range_nm REAL, range_text TEXT, height_m REAL, structure TEXT, country TEXT, region TEXT, remarks TEXT,
    publication TEXT, source TEXT);
CREATE TABLE airports (id TEXT PRIMARY KEY, ident TEXT, iata TEXT, name TEXT, type TEXT, city TEXT, country TEXT,
    lat REAL, lon REAL, elevation_m REAL, source TEXT);
CREATE TABLE airport_frequencies (airport_id TEXT REFERENCES airports(id), type TEXT, description TEXT,
    frequency_mhz REAL);
CREATE TABLE safe_havens (id TEXT PRIMARY KEY, name TEXT, type TEXT,   -- embassy | consulate | mission | refugee site
    represents TEXT, host_country TEXT, city TEXT, lat REAL, lon REAL, phone TEXT, website TEXT, source TEXT);
CREATE TABLE security_sites (id TEXT PRIMARY KEY, name TEXT, type TEXT, -- prison | military base | naval base | military airfield | border control
    operator TEXT, detail TEXT, access TEXT, host_country TEXT, lat REAL, lon REAL, source TEXT);
CREATE TABLE migrant_incidents (id TEXT PRIMARY KEY, date TEXT, corridor TEXT, route TEXT, region TEXT,
    dead INTEGER, missing INTEGER, survivors INTEGER, females INTEGER, males INTEGER, children INTEGER, cause TEXT,
    country TEXT, location TEXT, origin TEXT, information_source TEXT, url TEXT, source_quality INTEGER, incident_type TEXT,
    lat REAL, lon REAL, source TEXT);
CREATE TABLE thermal_anomalies (timestamp TEXT, lat REAL, lon REAL, brightness REAL, frp_mw REAL,
    confidence TEXT, daynight TEXT, satellite TEXT, country TEXT, source TEXT);
CREATE TABLE conflict_events (id TEXT PRIMARY KEY, date TEXT, date_end TEXT, event_type TEXT, conflict TEXT,
    side_a TEXT, side_b TEXT, fatalities INTEGER, civilian_deaths INTEGER, location TEXT, region TEXT, country TEXT,
    lat REAL, lon REAL, location_precision INTEGER, source TEXT);
CREATE TABLE tor_relays (fingerprint TEXT PRIMARY KEY, nickname TEXT, role TEXT, flags TEXT, ip TEXT, exit_ip TEXT,
    country TEXT, as_number TEXT, as_name TEXT, advertised_bandwidth INTEGER, consensus_weight_fraction REAL,
    guard_probability REAL, middle_probability REAL, exit_probability REAL, first_seen TEXT, platform TEXT,
    lat REAL, lon REAL, source TEXT);                    -- lat/lon: the country's label point (Onionoo has no coordinates)
CREATE TABLE wifi_hotspots (id TEXT PRIMARY KEY, name TEXT, place_type TEXT, access_fee TEXT, -- fee: no | customers | donation
    ssid TEXT, operator TEXT, opening_hours TEXT, city TEXT, country TEXT, lat REAL, lon REAL, source TEXT);
CREATE TABLE network_interference (country TEXT, country_name TEXT, test TEXT, measurements INTEGER,
    anomalies INTEGER, confirmed INTEGER, failures INTEGER, period_start TEXT, period_end TEXT, level TEXT, source TEXT);
"""
INDEXES = """
CREATE INDEX idx_places_geo ON radio_places(lat, lon);
CREATE INDEX idx_stations_place ON radio_stations(place_id);
CREATE INDEX idx_sdr_geo ON sdr_receivers(lat, lon);
CREATE INDEX idx_repeaters_geo ON repeaters(lat, lon);
CREATE INDEX idx_repeaters_freq ON repeaters(frequency_mhz);
CREATE INDEX idx_nav_domain_geo ON nav_radio_beacons(domain, lat, lon);
CREATE INDEX idx_nav_type ON nav_radio_beacons(sub_type);
CREATE INDEX idx_lights_geo ON maritime_lights(lat, lon);
CREATE INDEX idx_airports_geo ON airports(lat, lon);
CREATE INDEX idx_airport_freq ON airport_frequencies(airport_id);
CREATE INDEX idx_havens_geo ON safe_havens(lat, lon);
CREATE INDEX idx_security_geo ON security_sites(lat, lon);
CREATE INDEX idx_migrant_geo ON migrant_incidents(lat, lon);
CREATE INDEX idx_migrant_date ON migrant_incidents(date);
CREATE INDEX idx_thermal_geo ON thermal_anomalies(lat, lon);
CREATE INDEX idx_conflict_geo ON conflict_events(lat, lon);
CREATE INDEX idx_conflict_date ON conflict_events(date);
CREATE INDEX idx_interference_country ON network_interference(country);
CREATE INDEX idx_tor_country ON tor_relays(country);
CREATE INDEX idx_tor_as ON tor_relays(as_number);
CREATE INDEX idx_wifi_geo ON wifi_hotspots(lat, lon);
"""
SURVEILLANCE_SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT, url TEXT, license TEXT, notes TEXT);
CREATE TABLE police_stations (id TEXT PRIMARY KEY, name TEXT, operator TEXT, phone TEXT, lat REAL, lon REAL, source TEXT);
CREATE TABLE surveillance_nodes (osm_node_id INTEGER PRIMARY KEY, lat REAL, lon REAL, -- the OSM node id is the rowid
    surveillance_type TEXT, camera_type TEXT, zone TEXT, surveillance TEXT, direction TEXT, operator TEXT, name TEXT, source TEXT);
"""
SURVEILLANCE_INDEXES = """
CREATE INDEX idx_police_geo ON police_stations(lat, lon);
CREATE INDEX idx_surveillance_geo ON surveillance_nodes(lat, lon);
"""
SOURCES = [
    ("radio-browser", "Radio Browser", "https://www.radio-browser.info", "community database, see site", "radio stations and direct stream links"),
    ("geonames", "GeoNames cities1000", "https://www.geonames.org", "CC BY 4.0", "city names and positions"),
    ("natural-earth", "Natural Earth admin-1", "https://www.naturalearthdata.com", "public domain", "regions"),
    ("positions-csv", "Radio Garden catalog export (radio_globe_dataset.csv)", "", "rights not cleared",
     "city positions matched by station name for some stations without coordinates"),
    ("receiverbook", "receiverbook.de", "https://www.receiverbook.de", "no licence stated", "OpenWebRX, KiwiSDR, WebSDR receivers"),
    ("kiwisdr-list", "KiwiSDR public list via rx.linkfanel.net", "http://rx.linkfanel.net/", "no licence stated", "KiwiSDR receivers"),
    ("hearham", "Hearham", "https://hearham.com/repeaters", "free to use in applications", "amateur repeaters"),
    ("openrepeater", "Open Repeater", "https://www.openrepeater.org", "CC0 1.0", "amateur repeaters"),
    ("ourairports", "OurAirports", "https://ourairports.com/data/", "public domain", "navaids, airports, airport frequencies"),
    ("nga", "NGA List of Lights, Pubs 110-116", "https://msi.nga.mil", "US Government work, public domain",
     "lights, RACONs, radiobeacons, DGPS; US waters excluded"),
    ("osm", "OpenStreetMap", "https://www.openstreetmap.org/copyright", "ODbL 1.0", "embassies, consulates, refugee sites, prisons, military sites, border controls, police stations, surveillance cameras, places with public Wi-Fi"),
    ("tor-metrics", "Tor Metrics, Onionoo", "https://metrics.torproject.org", "CC0 1.0", "running Tor relays (bridges excluded), positioned by country"),
    ("iom-mmp", "IOM Missing Migrants Project", "https://missingmigrants.iom.int", "CC BY 4.0",
     "deaths and disappearances of people on the move since 2014; locations often approximate"),
    ("firms", "NASA FIRMS VIIRS 375 m", "https://firms.modaps.eosdis.nasa.gov", "free and open, cite NASA FIRMS", "thermal anomalies, last 24 h at build time"),
    ("ucdp", "UCDP Georeferenced Event Dataset and candidate events", "https://ucdp.uu.se", "CC BY 4.0", "conflict events"),
    ("ooni", "OONI", "https://ooni.org", "CC BY 4.0", "network interference per country, 30 days"),
]


class Database:
    """A SQLite file written as <out>.tmp, renamed when complete, then gzipped to <out>.gz (the published copy)."""

    def __init__(self, out, schema, sources):
        self.out, self.tmp, self.counts = out, out.with_suffix(".tmp"), {}
        self.tmp.unlink(missing_ok=True)
        self.db = sqlite3.connect(self.tmp)
        self.db.executescript(schema)
        self.insert("sources", sources)

    def insert(self, table, rows):
        rows = list(rows)
        if rows:
            self.db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
        self.counts[table] = self.counts.get(table, 0) + len(rows)

    def finish(self, indexes):
        self.insert("metadata", [("generated_at", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
                                 ("schema_version", "3"), ("counts", json.dumps(self.counts))])
        self.db.executescript(indexes)
        self.db.commit()
        self.db.execute("VACUUM")
        self.db.close()
        self.tmp.replace(self.out)
        with open(self.out, "rb") as src, gzip.open(f"{self.out}.gz", "wb", compresslevel=9) as dst:
            shutil.copyfileobj(src, dst)
        return {"out": f"{self.out}.gz", "bytes": self.out.stat().st_size, "gzip_bytes": Path(f"{self.out}.gz").stat().st_size, "rows": self.counts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="db/qp1ng.sqlite")
    args = ap.parse_args()
    data, out = Path(args.data), Path(args.out)
    load = lambda name: json.loads((data / name).read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    main_db = Database(out, SCHEMA, SOURCES)
    insert = main_db.insert
    precision = {None: "city", "r": "region", "n": "country"}
    insert("radio_places", ((p["id"], p["city"], p["country"], p["lat"], p["lng"], p["count"], precision.get(p.get("loc"), "city"))
                            for p in load("places.json")))
    insert("radio_stations", ((s["id"], s["place_id"], s["title"], s["stream_url"], s.get("homepage"), s.get("codec"),
                               s.get("bitrate"), s.get("hls", 0), "radio-browser") for s in load("stations.json")))
    insert("sdr_receivers", ((r["id"], r["name"], r["type"], r["url"], r["lat"], r["lng"], r.get("place"), r.get("bands"),
                              r.get("channels"), r.get("snr"), r.get("antenna"), r.get("featured", 0),
                              "kiwisdr-list" if r["type"] == "KiwiSDR" else "receiverbook") for r in load("sdr.json")["receivers"]))
    insert("repeaters", ((r["id"], r["call"], r["freq"], r.get("off"), round(r["freq"] + r["off"], 5) if r.get("off") else None,
                          "/".join(r["modes"]), r["band"], r.get("tone"), r.get("tsq"), r.get("group"), r.get("node"), r.get("city"),
                          r["lat"], r["lng"], r.get("power"), r.get("range"), r.get("restricted"), r.get("desc"), r.get("site"),
                          "hearham" if r["src"] == "h" else "openrepeater") for r in load("repeaters.json")["repeaters"]))
    aviation = load("aviation.json")["items"]
    feet = lambda v: round(v * 0.3048, 1) if v is not None else None
    insert("nav_radio_beacons", ((n["id"], "AVIATION", n["kind"], n["ident"], n["name"], n.get("khz"), n.get("dme"), morse(n["ident"]),
                                  n["lat"], n["lng"], feet(n.get("elev")), None, n.get("cc"),
                                  " ".join(x for x in (n.get("usage"), n.get("power")) if x) or None, "ourairports")
                                 for n in aviation if n["kind"] != "AIRPORT"))
    airports = [a for a in aviation if a["kind"] == "AIRPORT"]
    insert("airports", ((a["id"], a["ident"], a.get("iata"), a["name"], a["atype"], a.get("city"), a.get("cc"), a["lat"], a["lng"],
                         feet(a.get("elev")), "ourairports") for a in airports))
    insert("airport_frequencies", ((a["id"], t, d, mhz) for a in airports for t, d, mhz in a["freqs"]))
    first_number = lambda text: max((float(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", text or "")), default=None)
    maritime = load("maritime.json")["items"]
    insert("nav_radio_beacons", ((m["id"], "MARITIME", m["kind"], m.get("ident"), m["name"], m.get("khz"), None,
                                  morse(m["ident"]) if m["kind"] == "RADIOBEACON" and m.get("ident") else m.get("char") if m["kind"] == "RACON" else None,
                                  m["lat"], m["lng"], None, first_number(m.get("range")), m["cc"], m.get("remarks"), "nga")
                                 for m in maritime if m["kind"] != "LIGHT"))
    insert("maritime_lights", ((m["id"], m["name"], m["lat"], m["lng"], m.get("char"), first_number(m.get("range")), m.get("range"),
                                m.get("height"), m.get("structure"), m["cc"], m.get("region"), m.get("remarks"), m["vol"], "nga")
                               for m in maritime if m["kind"] == "LIGHT"))
    for e in load("embassies.json")["items"]:
        insert("safe_havens", [(e["id"], e["name"], "refugee site" if e["kind"] == "REFUGE" else e["kind"].lower(), e.get("from"), e.get("host"), e.get("city"), e["lat"], e["lng"],
                                e.get("phone"), e.get("web"), "osm")])
    insert("security_sites", ((s["id"], s["name"], s["kind"].lower(), s.get("operator"), s.get("detail"), s.get("access"), s.get("host"),
                               s["lat"], s["lng"], "osm") for s in load("security.json")["items"]))
    insert("migrant_incidents", ((m["id"], m["d"], m["g"], m.get("route"), m.get("region"), m["dead"], m["miss"], m.get("surv"), m.get("f"), m.get("m"),
                                  m.get("ch"), m.get("cause"), m.get("cc"), m.get("place"), m.get("origin"), m.get("src"), m.get("url"), m.get("q"),
                                  m.get("type", "Incident"), m["lat"], m["lng"], "iom-mmp") for m in load("migration.json")["items"]))
    insert("thermal_anomalies", ((f["t"], f["lat"], f["lng"], f["bt"], f["frp"], "high" if f["c"] == "h" else "nominal",
                                  "day" if f["dn"] == "D" else "night", "NOAA-20" if f["s"] == "J" else "Suomi NPP", f.get("host"), "firms")
                                 for f in load("fires.json")["items"]))
    insert("conflict_events", ((c["id"], c["d"], c.get("d2"), c["kind"], c["conflict"], c["a"], c["b"], c["best"], c.get("civ"),
                                c.get("place"), c.get("adm"), c["cc"], c["lat"], c["lng"], c["prec"], "ucdp") for c in load("conflict.json")["items"]))
    net = load("internet.json")
    insert("network_interference", ((n["cc"], n["name"], test, t["m"], t["a"], t["c"], t["f"], net["since"], net["until"], n["level"], "ooni")
                                    for n in net["items"] for test, t in n["tests"].items()))
    tor = load("tor.json")
    ipv4 = lambda addrs: next((a.rsplit(":", 1)[0] for a in addrs or [] if a.count(".") == 3), None)
    role = lambda f: "exit" if "Exit" in f and "BadExit" not in f else "guard" if "Guard" in f else "middle"
    insert("tor_relays", ((r["fingerprint"], r.get("nickname"), role(r.get("flags", [])), ",".join(r.get("flags", [])), ipv4(r.get("or_addresses")),
                           next(iter(r.get("exit_addresses") or []), None), r["country"], r.get("as"), r.get("as_name"), r.get("advertised_bandwidth"),
                           r.get("consensus_weight_fraction"), r.get("guard_probability"), r.get("middle_probability"), r.get("exit_probability"),
                           r.get("first_seen"), r.get("platform"), *tor["points"][r["country"]], "tor-metrics") for r in tor["relays"]))
    insert("wifi_hotspots", ((w["id"], w["name"] or None, w.get("kind"), w["fee"], w.get("ssid"), w.get("op"), w.get("hours"), w.get("city"), w.get("cc"),
                              w["lat"], w["lng"], "osm") for w in load("wifi.json")["items"]))
    report = [main_db.finish(INDEXES)]

    # Police stations and cameras come as tiles (scripts/build_surveillance.mjs); rows are compact arrays.
    surveillance = Database(out.with_name(f"{out.stem}-surveillance{out.suffix}"), SURVEILLANCE_SCHEMA, [s for s in SOURCES if s[0] == "osm"])
    pad = lambda row, n: list(row) + [""] * (n - len(row))
    for tile in sorted((data / "surveillance").glob("*_*.json")):
        t = json.loads(tile.read_text(encoding="utf-8"))
        surveillance.insert("police_stations", ((i, name or None, op or None, phone or None, lat, lng, "osm")
                                                for i, lat, lng, name, op, phone in (pad(r, 6) for r in t.get("p", []))))
        surveillance.insert("surveillance_nodes", ((i, lat, lng, *(v or None for v in rest), "osm")
                                                   for i, lat, lng, *rest in (pad(r, 10) for r in t.get("c", []))))
    report.append(surveillance.finish(SURVEILLANCE_INDEXES))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
