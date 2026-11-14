"""Offline fixtures for stream evidence, safe origins, and builder compatibility."""
import datetime as dt
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
import urllib.error
from unittest import mock


ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("check_webcams", ROOT / "scripts/check_webcams.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SPEC_BUILD = importlib.util.spec_from_file_location("build_webcams", ROOT / "scripts/build_webcams.py")
B = importlib.util.module_from_spec(SPEC_BUILD)
SPEC_BUILD.loader.exec_module(B)
BASE = "https://wzmedia.dot.ca.gov/D3/cam.stream/"
MASTER = BASE + "playlist.m3u8"
MEDIA = BASE + "chunklist_w123.m3u8"
MASTER_BYTES = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=420000,CODECS="avc1.66.40,mp4a.40.2"\nchunklist_w123.m3u8\n'


def media(sequence=10, segment="seg10.ts", endlist=False, extra=""):
    return (f"#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXT-X-MEDIA-SEQUENCE:{sequence}\n"
            + extra + f"#EXTINF:3.0,\n{segment}\n" + ("#EXT-X-ENDLIST\n" if endlist else "")).encode()


def ts_bytes():
    return (b"\x47" + b"\x00" * 187) * 4


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.elapsed = 0.0
        self.calls = []

    def clock(self):
        return self.elapsed

    def wait(self, seconds):
        self.elapsed += seconds

    def get(self, url, segment=None):
        self.calls.append((url, segment))
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result, {"url": url, "http_status": 200, "content_type": "video/MP2T" if segment else "application/vnd.apple.mpegurl"}


class WebcamCheckTest(unittest.TestCase):
    def test_live_requires_same_playlist_progress_and_fresh_segment(self):
        client = FakeClient([MASTER_BYTES, media(), media(11, "seg11.ts"), ts_bytes()])
        event = M.probe(MASTER, "live", client)
        self.assertTrue(event["live_verified"])
        self.assertEqual(event["elapsed_seconds"], 7)
        self.assertEqual(client.calls[1][0], client.calls[2][0])
        self.assertEqual(client.calls[3][0], BASE + "seg11.ts")
        self.assertEqual(B.event_health(event)["status"], "live_confirmed")

    def test_token_only_rotation_is_not_advancement(self):
        client = FakeClient([MASTER_BYTES, media(segment="seg.ts?token=one"), media(segment="seg.ts?token=two"), ts_bytes()])
        event = M.probe(MASTER, "live", client)
        self.assertTrue(event["segment_ok"])
        self.assertFalse(event["advancing"])
        self.assertFalse(event["live_verified"])
        self.assertEqual(B.event_health(event)["status"], "segment_ok")

    def test_counter_reset_with_new_segment_is_explicit(self):
        event = M.probe(MASTER, "live", FakeClient([MASTER_BYTES, media(1634, "old.ts"), media(30, "new.ts"), ts_bytes()]))
        self.assertTrue(event["sequence_reset"])
        self.assertFalse(event["sequence_advanced"])
        self.assertTrue(event["segment_identity_changed"])
        self.assertTrue(event["live_verified"])

    def test_segment404_is_inconclusive_and_preserves_master200(self):
        event = M.probe(MASTER, "live", FakeClient([MASTER_BYTES, media(), media(11, "new.ts"), M.CheckError("HTTP Error 404", code=404, kind="http_error")]))
        self.assertEqual(event["stage"], "segment")
        self.assertEqual(event["http_status"], 200)
        self.assertEqual(event["failure_http_status"], 404)
        self.assertTrue(event["manifest_valid"])
        self.assertFalse(event["live_verified"])
        self.assertEqual(B.event_health(event)["status"], "network_unverified")

    def test_master404_keeps_the_correct_failure_stage(self):
        event = M.probe(MASTER, "live", FakeClient([M.CheckError("HTTP Error 404", code=404, kind="http_error")]))
        self.assertEqual(event["stage"], "manifest")
        self.assertEqual(event["http_status"], 404)
        self.assertFalse(event["manifest_valid"])
        self.assertEqual(B.event_health(event)["status"], "unavailable")

    def test_manifest200_and_segment_html_do_not_prove_live(self):
        shallow = M.probe(MASTER, "manifests", FakeClient([MASTER_BYTES]))
        self.assertFalse(shallow["live_verified"])
        self.assertEqual(B.event_health(shallow)["status"], "playlist_ok")
        deep = M.probe(MASTER, "live", FakeClient([MASTER_BYTES, media(), media(11, "new.ts"), b"<html>offline</html>"]))
        self.assertFalse(deep["segment_ok"])
        self.assertFalse(deep["live_verified"])

    def test_fixed_playlist_is_not_marked_offline(self):
        event = M.probe(MASTER, "live", FakeClient([MASTER_BYTES, media(), media(), ts_bytes()]))
        self.assertEqual(event["status"], "progression_unknown")
        self.assertEqual(B.event_health(event)["status"], "segment_ok")

    def test_endlist_and_encryption_do_not_claim_live(self):
        for payload in (media(endlist=True), media(extra='#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n')):
            client = FakeClient([MASTER_BYTES, payload])
            event = M.probe(MASTER, "live", client)
            self.assertFalse(event["live_verified"])
            self.assertEqual(len(client.calls), 2)

    def test_hls_byte_ranges_are_part_of_media_identity(self):
        body = (b"#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXTINF:3,\n#EXT-X-BYTERANGE:1000@2000\nmedia.mp4\n"
                b"#EXTINF:3,\n#EXT-X-BYTERANGE:1000\nmedia.mp4\n")
        parsed = M.parse_playlist(body, MEDIA)
        self.assertEqual(parsed["segments"][1]["range_start"], 3000)
        invalid = body.replace(b"1000@2000", b"1000")
        with self.assertRaises(M.CheckError):
            M.parse_playlist(invalid, MEDIA)

    def test_fmp4_signature_and_ts_signature(self):
        def box(kind, data):
            return (len(data) + 8).to_bytes(4, "big") + kind + data
        fragment = box(b"moof", box(b"mfhd", b"\0" * 8) + box(b"traf", box(b"tfhd", b"\0" * 8)))
        media = fragment + box(b"mdat", b"\1" * 32)
        self.assertEqual(M.media_signature(media), "fragmented_mp4")
        self.assertEqual(M.media_signature(media[:-8]), "fragmented_mp4", "a bounded prefix may end inside a media payload")
        self.assertIsNone(M.media_signature(fragment), "a fragment without media is not a video segment")
        self.assertIsNone(M.media_signature(b"\x00\x00\x00\x18ftyp"), "truncated file headers must not pass")
        self.assertIsNone(M.media_signature(b"\x00\x00\x00\x18stypmsdh\x00\x00\x00\x00msdhmsix"))
        self.assertIsNone(M.media_signature(box(b"mdat", b"\1" * 32)), "media without fragment metadata is inconclusive")
        self.assertIsNone(M.media_signature(b"\x00\x00\x00\x02moof"))
        self.assertIsNone(M.media_signature(b"\x47not a transport stream"))
        self.assertEqual(M.media_signature(ts_bytes()), "mpeg_ts")

    def test_unsafe_and_unlicensed_catalog_urls_are_rejected(self):
        bad = ["http://wzmedia.dot.ca.gov/a.m3u8", "https://wzmedia.dot.ca.gov.evil.example/a.m3u8",
               "https://user:pass@wzmedia.dot.ca.gov/a.m3u8", "https://127.0.0.1/a.m3u8",
               "https://wzmedia.dot.ca.gov:8443/a.m3u8", "https://wzmedia.dot.ca.gov\\@evil.example/a.m3u8",
               "file:///tmp/a.m3u8", "https://wzmedia.dot.ca.gov/a.m3u8#x"]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(M.CheckError):
                M.allowed_url(url)
        rows = [{"provider": "caltrans", "format": "hls", "rights_status": M.RIGHTS_STATUS, "stream_url": MASTER},
                {"provider": "caltrans", "format": "hls", "rights_status": "unknown", "stream_url": BASE + "other.m3u8"},
                {"provider": "caltrans", "format": "hls", "rights_status": M.RIGHTS_STATUS, "stream_url": MASTER}]
        urls, skipped = M.select_urls({"items": rows})
        self.assertEqual(urls, [MASTER])
        self.assertEqual(skipped["rights"], 1)
        self.assertEqual(skipped["duplicate"], 1)
        with self.assertRaises(M.CheckError):
            M.parse_playlist(MASTER_BYTES.replace(b"chunklist_w123.m3u8", b"https://evil.example/video.m3u8"), MASTER)

    def test_vegvesen_checks_keep_provider_origins_separate(self):
        url = "https://kamera.vegvesen.no/public/123/manifest.m3u8"
        rows = [{"provider": "vegvesen", "format": "hls", "rights_status": M.RIGHTS_STATUS, "stream_url": url},
                {"provider": "vegvesen", "format": "hls", "rights_status": M.RIGHTS_STATUS, "stream_url": MASTER},
                {"provider": "unknown", "format": "hls", "rights_status": M.RIGHTS_STATUS, "stream_url": url}]
        self.assertEqual(M.select_urls({"items": rows})[0], [])
        selected, skipped = M.select_urls({"items": rows}, "vegvesen")
        self.assertEqual(selected, [url])
        self.assertEqual(skipped["url"], 1)
        self.assertEqual(skipped["provider"], 1)
        client = FakeClient([MASTER_BYTES, media(), media(11, "new.ts"), ts_bytes()])
        client.allowed_host = "kamera.vegvesen.no"
        self.assertTrue(M.probe(url, "live", client)["live_verified"])
        with self.assertRaises(M.CheckError):
            M.parse_playlist(MASTER_BYTES.replace(b"chunklist_w123.m3u8", MASTER.encode()), url, client.allowed_host)

    def test_429_stops_client_and_preserves_retry_after(self):
        client = M.HttpClient(300)
        failure = urllib.error.HTTPError(MASTER, 429, "Too Many Requests", {"Retry-After": "120"}, io.BytesIO())
        with mock.patch.object(M.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = failure
            with self.assertRaises(M.CheckError) as caught:
                client.get(MASTER)
            self.assertEqual(caught.exception.retry_after, "120")
            self.assertTrue(client.stop.is_set())
            with self.assertRaises(M.CheckError):
                client.get(MASTER)
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_resume_checks_depth_age_and_partial_lines(self):
        now = dt.datetime(2026, 11, 13, 4, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder) / "health.jsonl"
            out.write_text(json.dumps({"url": MASTER, "checked_at": "2026-11-13T03:00:00Z", "mode": "manifests"}) + '\n{"partial":')
            self.assertIn(MASTER, M.recent_checks(out, "manifests", 6, now))
            self.assertNotIn(MASTER, M.recent_checks(out, "live", 6, now))
            self.assertNotIn(MASTER, M.recent_checks(out, "manifests", 0, now))
            out.write_text(json.dumps({"url": MASTER, "checked_at": "2026-11-13T03:00:00Z", "mode": "live", "status": "budget_exhausted"}) + "\n")
            self.assertNotIn(MASTER, M.recent_checks(out, "live", 6, now))

    def test_redirects_are_origin_checked_bounded_and_throttled(self):
        client = M.HttpClient(300)
        handler = M.BoundedRedirect(client, client.clock() + 8)
        request = M.urllib.request.Request(MASTER)
        with mock.patch.object(client, "throttle_start") as throttle:
            for index in range(M.MAX_REDIRECTS):
                redirected = handler.redirect_request(request, None, 302, "", {}, BASE + f"p{index}.m3u8")
                self.assertEqual(redirected.full_url, BASE + f"p{index}.m3u8")
            with self.assertRaises(M.CheckError):
                handler.redirect_request(request, None, 302, "", {}, MEDIA)
            self.assertEqual(throttle.call_count, M.MAX_REDIRECTS)
        handler = M.BoundedRedirect(client, client.clock() + 8)
        with self.assertRaises(M.CheckError):
            handler.redirect_request(request, None, 302, "", {}, "https://127.0.0.1/private")

    def test_cli_cannot_append_health_over_input_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "catalog.json"
            original = '{"items":[]}'
            path.write_text(original)
            with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                M.main(["--catalog", str(path), "--out", str(path)])
            self.assertEqual(path.read_text(), original)

    def test_interval_over_60_seconds_is_not_waited(self):
        slow = media().replace(b"TARGETDURATION:3", b"TARGETDURATION:60")
        client = FakeClient([MASTER_BYTES, slow])
        event = M.probe(MASTER, "live", client)
        self.assertFalse(event["live_verified"])
        self.assertEqual(client.elapsed, 0)
        self.assertEqual(event["stage"], "interval")


if __name__ == "__main__":
    unittest.main()
