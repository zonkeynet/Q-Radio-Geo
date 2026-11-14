"""scripts/build_db.py reads data/stations.json in both formats: schema 2 (one list per field, value tables) gives
exactly the stations of the earlier one-object-per-station file."""
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_db", ROOT / "scripts" / "build_db.py")
build_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_db)


class StationsFormatTest(unittest.TestCase):
    def test_published_file_expands_to_complete_stations(self):
        data = json.loads((ROOT / "data" / "stations.json").read_text(encoding="utf-8"))
        stations = build_db.expand_stations(data)
        self.assertEqual(len(stations), data["count"])
        for s in stations[:500]:
            self.assertTrue({"id", "place_id", "title", "stream_url"} <= s.keys())
            self.assertNotIn(None, s.values())

    def test_same_records_as_the_earlier_file(self):
        try:
            earlier = json.loads(subprocess.run(["git", "-C", str(ROOT), "show", "e3a9838:data/stations.json"],
                                                capture_output=True, check=True).stdout)
        except (OSError, subprocess.CalledProcessError, ValueError):
            self.skipTest("git history unavailable")
        stations = build_db.expand_stations(json.loads((ROOT / "data" / "stations.json").read_text(encoding="utf-8")))
        if [s["id"] for s in stations] != [s["id"] for s in earlier]:
            self.skipTest("the catalogue has been rebuilt since the conversion")
        self.assertEqual(stations, earlier)
        self.assertTrue(all(list(a) == list(b) for a, b in zip(stations, earlier)), "field order")

    def test_small_cases(self):
        data = {"schema_version": 2, "payload_kind": "radio_stations",
                "fields": ["id", "place_id", "title", "stream_url", "homepage", "codec", "bitrate", "hls"],
                "values": {"place_id": [None, "nUS"], "codec": [None, "MP3"]},
                "columns": [["a", "b"], [1, 1], ["A", "B"], ["https://x/a", "https://x/b"], ["https://x/", None], [1, 0], [128, None], [1, None]]}
        self.assertEqual(build_db.expand_stations(data), [
            {"id": "a", "place_id": "nUS", "title": "A", "stream_url": "https://x/a", "homepage": "https://x/", "codec": "MP3", "bitrate": 128, "hls": 1},
            {"id": "b", "place_id": "nUS", "title": "B", "stream_url": "https://x/b"}])
        self.assertEqual(build_db.expand_stations([{"id": "x"}]), [{"id": "x"}])
        with self.assertRaises(ValueError):
            build_db.expand_stations({"schema_version": 9})


if __name__ == "__main__":
    unittest.main()
