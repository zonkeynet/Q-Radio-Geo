"""Owners' live streams (scripts/webcam_live_streams.json): validation, the duplicate rule, the published views,
the re-check's verdicts, and the committed source file."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_webcams as M
import check_live_streams as C

LIVE = M.LIVE_STREAM_SOURCE["id"]
CHECK = {"checked_at": "2026-11-15T14:00:00Z", "result": "ok"}


def raw(**over):
    base = {"provider_id": "nl-harbour", "name": "Harbour live", "country": "NL", "region": "Rotterdam",
            "lat": 51.9, "lng": 4.1, "format": "youtube", "youtube": {"video": "_KVWehizoNU"},
            "official_page": "https://www.youtube.com/watch?v=_KVWehizoNU", "source_page": "https://www.port.example.nl/en",
            "owner": "Port Authority", "coordinate_role": "named_feature", "coordinate_source": "osm:node/1",
            "coordinate_source_licence": "ODbL 1.0", "coordinate_feature": "Harbour mouth", "coordinate_uncertainty_m": 300,
            "reason": "Live on the owner's channel.", "check": dict(CHECK)}
    base.update(over)
    return base


def embed(**over):
    return raw(**{"provider_id": "cl-park", "format": "embed", "youtube": None, "source_page": None,
                  "embed_url": "https://g3.ipcamlive.com/player/player.php?alias=abc", "official_page": "https://park.example.cl/", **over})


def other(provider, rid, lat, lng, fmt="official_page", **extra):
    row = {"id": f"{provider}:{rid}", "provider": provider, "name": rid, "lat": lat, "lng": lng, "format": fmt,
           "official_page": None, "stream_url": None, "snapshot_url": None,
           "rights_status": "official_page_only" if fmt == "official_page" else "official_public_feed"}
    row.update({f: None for f in M.REFERENCE_FIELDS})
    row.update(extra)
    return row


class NormalizeTest(unittest.TestCase):
    def test_a_youtube_record_becomes_an_official_embed_item_with_its_owner(self):
        item = M.normalize_live_stream(raw())
        self.assertEqual((item["id"], item["provider"], item["format"], item["rights_status"]),
                         (f"{LIVE}:nl-harbour", LIVE, "youtube", "official_embed"))
        self.assertEqual(item["youtube"], {"video": "_KVWehizoNU"})
        self.assertEqual(item["attribution"], "Port Authority (YouTube)")
        self.assertEqual(item["terms_url"], M.YOUTUBE_TERMS)
        self.assertEqual(item["official_page"], "https://www.youtube.com/watch?v=_KVWehizoNU")
        self.assertIs(item["identity_confirmed"], False)
        self.assertEqual(item["observed_at"], CHECK["checked_at"])
        self.assertNotIn("embed_url", item)

    def test_an_owner_player_keeps_its_page_and_terms(self):
        item = M.normalize_live_stream(embed())
        self.assertEqual(item["embed_url"], "https://g3.ipcamlive.com/player/player.php?alias=abc")
        self.assertEqual((item["attribution"], item["terms_url"], item["source_page"]),
                         ("Port Authority", "https://park.example.cl/", "https://park.example.cl/"))
        self.assertNotIn("youtube", item)

    def test_invalid_records_are_refused(self):
        bad = [raw(youtube={"video": "short"}), raw(youtube={"channel": "UCtooshort"}), raw(youtube={}),
               raw(youtube={"video": "_KVWehizoNU", "list": "x"}), raw(embed_url="https://g3.ipcamlive.com/p"),
               embed(embed_url="http://g3.ipcamlive.com/player/player.php?alias=abc"),
               embed(embed_url="https://evil.example.org/player"), embed(embed_url="https://g3.ipcamlive.com:8443/player"),
               embed(embed_url="https://g3.ipcamlive.com/player#x"), raw(owner=" "), raw(format="hls"),
               raw(check={"checked_at": "2026-11-15T14:00:00Z", "result": "fail"}), raw(check={"result": "ok"}),
               raw(coordinate_feature=None), raw(coordinate_role="official"), raw(country="Netherlands"),
               raw(lat=0, lng=0), raw(previous_videos=["nope"]), raw(official_page=None, source_page=None),
               raw(provider_id="Bad Id")]
        for record in bad:
            with self.subTest(record=record), self.assertRaises(ValueError):
                M.normalize_live_stream(record)

    def test_private_links_are_filtered_with_the_pipeline_rules(self):
        with self.assertRaises(M.PrivacyFiltered) as ctx:
            M.normalize_live_stream(raw(official_page="https://cam.example.org/live?user=admin&pwd=x"))
        self.assertEqual((ctx.exception.reason, ctx.exception.field), ("credential_query", "official_page"))
        with self.assertRaises(M.PrivacyFiltered):
            M.normalize_live_stream(raw(source_page="https://mycam.ddns.net/"))

    def test_a_source_file_loads_once_per_stream(self):
        tmp = ROOT / "tests" / "_live_streams_tmp.json"
        try:
            doc = {"schema_version": 1, "source": LIVE, "checked_at": "2026-11-15T14:00:00Z",
                   "items": [raw(), embed(), raw(provider_id="nl-bad", youtube={"video": "bad"})]}
            tmp.write_text(json.dumps(doc), encoding="utf-8")
            items, source, provenance, rejected = M.load_live_streams(tmp)
            self.assertEqual([x["provider_id"] for x in items], ["cl-park", "nl-harbour"])
            self.assertEqual((source["id"], provenance[0]["records"], len(rejected)), (LIVE, 3, 1))
            doc["items"].append(raw(provider_id="nl-again"))  # the same video twice
            tmp.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError):
                M.load_live_streams(tmp)
        finally:
            tmp.unlink(missing_ok=True)


class DuplicateTest(unittest.TestCase):
    def live(self, **over):
        return M.normalize_live_stream(raw(**over))

    def test_a_record_linking_the_same_stream_merges_into_the_live_one(self):
        osm = other("osm_webcams", "node-1", 51.90003, 4.1, official_page="https://youtu.be/_KVWehizoNU")  # ~3 m
        wiki = other("wikidata_webcams", "Q1", 51.9, 4.1025, official_page="https://www.youtube.com/watch?v=_KVWehizoNU")  # ~170 m
        kept, log = M.drop_live_duplicates([self.live(), osm, wiki])
        self.assertEqual([x["id"] for x in kept], [f"{LIVE}:nl-harbour"])
        self.assertEqual({e["rule"] for e in log}, {"live-stream-same-stream"})

    def test_a_previous_id_of_the_stream_still_counts(self):
        osm = other("osm_webcams", "node-1", 51.9, 4.1, official_page="https://www.youtube.com/watch?v=LAJiFSw2ICc")
        kept, log = M.drop_live_duplicates([self.live(previous_videos=["LAJiFSw2ICc"]), osm])
        self.assertEqual(len(kept), 1)

    def test_same_owner_site_merges_only_the_nearest_record_within_the_radius(self):
        live = M.normalize_live_stream(embed(lat=-33.4, lng=-70.6))
        near = other("osm_webcams", "node-2", -33.4, -70.6, official_page="https://park.example.cl/")
        second = other("osm_webcams", "node-3", -33.401, -70.6, official_page="https://park.example.cl/")    # ~110 m
        far = other("osm_webcams", "node-4", -33.405, -70.6, official_page="https://park.example.cl/")       # ~560 m
        stranger = other("osm_webcams", "node-5", -33.4, -70.6, official_page="https://www.windy.com/webcams/1")
        kept, log = M.drop_live_duplicates([live, near, second, far, stranger])
        self.assertEqual([e["id"] for e in log], ["osm_webcams:node-2"])
        self.assertEqual(log[0]["rule"], "live-stream-same-owner")
        self.assertEqual(len(kept), 4)

    def test_a_platform_page_says_nothing_about_the_owner(self):
        osm = other("osm_webcams", "node-1", 51.9, 4.1, official_page="https://www.youtube.com/watch?v=aaaaaaaaaaa")
        kept, log = M.drop_live_duplicates([self.live(source_page=None), osm])
        self.assertEqual((len(kept), log), (2, []))

    def test_an_admitted_feed_of_the_same_camera_stays_and_the_live_record_goes(self):
        live = M.normalize_live_stream(embed(lat=-33.4, lng=-70.6))
        feed = other("parks", "cam-1", -33.4, -70.6, "snapshot", official_page="https://park.example.cl/",
                     snapshot_url="https://park.example.cl/cam.jpg")
        kept, log = M.drop_live_duplicates([live, feed])
        self.assertEqual([x["id"] for x in kept], ["parks:cam-1"])
        self.assertEqual(log[0]["rule"], "live-stream-duplicate-of-feed")

    def test_the_merged_page_stays_as_a_reference(self):
        live = M.normalize_live_stream(embed(lat=-33.4, lng=-70.6, official_page="https://park.example.cl/live"))
        osm = other("osm_webcams", "node-2", -33.4, -70.6, official_page="https://park.example.cl/")
        kept, _ = M.drop_live_duplicates([live, osm])
        self.assertEqual(kept[0]["reference_url"], "https://park.example.cl/")


class ViewTest(unittest.TestCase):
    def test_live_streams_are_viewable_and_round_trip_through_the_first_file(self):
        items = [M.normalize_live_stream(raw()), M.normalize_live_stream(embed())]
        page = other("osm_webcams", "node-1", 1.0, 1.0, official_page="https://www.example.org/", attribution="OSM",
                     observed_at="2026-11-15T00:00:00Z", health={"status": "unverified"})
        catalog = {"schema_version": 2, "generated_at": "x", "sources": [dict(M.LIVE_STREAM_SOURCE), {"id": "osm_webcams"}],
                   "items": items + [page]}
        view = M.viewer_catalog(catalog)
        rows = {r["id"]: r for r in view["items"]}
        self.assertEqual(rows[f"{LIVE}:nl-harbour"]["youtube"], {"video": "_KVWehizoNU"})
        self.assertEqual(rows[f"{LIVE}:nl-harbour"]["attribution"], "Port Authority (YouTube)")
        self.assertEqual(rows[f"{LIVE}:cl-park"]["embed_url"], "https://g3.ipcamlive.com/player/player.php?alias=abc")
        self.assertNotIn("attribution", rows["osm_webcams:node-1"], "the source carries the attribution of other rows")
        self.assertNotIn("stream_check", rows[f"{LIVE}:nl-harbour"], "checks stay in the full records")
        live = M.live_view_catalog(view)
        self.assertEqual(M.expand_live_catalog(live)["items"], [r for r in view["items"] if r["provider"] == LIVE])

    def test_published_links_name_the_watch_page_and_the_player(self):
        yt = list(M.published_links(M.normalize_live_stream(raw())))
        self.assertEqual(yt[0], {"url": "https://www.youtube.com/watch?v=_KVWehizoNU", "purpose": "youtube_live", "is_primary": True})
        self.assertEqual(sum(link["is_primary"] for link in yt), 1)
        channel = M.normalize_live_stream(raw(youtube={"channel": "UCi4CSgJk3i_slWnWG9Y14qA"}))
        self.assertEqual(M.primary_url(channel), "https://www.youtube.com/channel/UCi4CSgJk3i_slWnWG9Y14qA/live")
        player = list(M.published_links(M.normalize_live_stream(embed())))
        self.assertIn({"url": "https://g3.ipcamlive.com/player/player.php?alias=abc", "purpose": "owner_player", "is_primary": True}, player)


class RecheckTest(unittest.TestCase):
    WATCH = '"playabilityStatus":{"status":"OK"} "playableInEmbed":true "liveBroadcastDetails":{"isLiveNow":true} "channelId":"UCi4CSgJk3i_slWnWG9Y14qA"'

    def test_verdicts(self):
        live = C.parse_watch(self.WATCH)
        self.assertEqual(C.verdict("x", 200, live, "UCi4CSgJk3i_slWnWG9Y14qA"), ("ok", None))
        self.assertEqual(C.verdict("x", 401, live)[0], "fail")
        self.assertEqual(C.verdict("x", 200, C.parse_watch(self.WATCH.replace("isLiveNow\":true", "isLiveNow\":false")))[0], "fail")
        self.assertEqual(C.verdict("x", 200, C.parse_watch(self.WATCH.replace("Embed\":true", "Embed\":false")))[0], "fail")
        self.assertEqual(C.verdict("x", 200, live, "UC" + "a" * 22)[0], "fail")
        self.assertEqual(C.live_video_of('<link rel="canonical" href="https://www.youtube.com/watch?v=_KVWehizoNU">'), "_KVWehizoNU")
        self.assertIsNone(C.live_video_of('<link rel="canonical" href="https://www.youtube.com/channel/UCi4CSgJk3i_slWnWG9Y14qA">'))

    def test_an_owner_player_is_checked_against_the_reviewed_hosts_without_a_request(self):
        self.assertEqual(C.check_record(embed(), "t")["result"], "ok")
        self.assertEqual(C.check_record(embed(embed_url="https://other.example.org/p"), "t")["result"], "fail")


class EmbedHostsTest(unittest.TestCase):
    def test_python_js_and_frame_src_list_the_same_owner_hosts(self):
        js = (ROOT / "js" / "webcams.mjs").read_text(encoding="utf-8")
        listed = re.search(r"export const EMBED_HOSTS = Object\.freeze\(\[([^\]]+)\]", js).group(1)
        self.assertEqual(set(re.findall(r"'([^']+)'", listed)), set(M.EMBED_HOSTS))
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', (ROOT / "index.html").read_text(encoding="utf-8")).group(1)
        frame = next(d for d in csp.split(";") if d.strip().startswith("frame-src")).split()[1:]
        self.assertEqual(set(frame), {f"https://{h}" for h in M.EMBED_HOSTS} | {"https://www.youtube-nocookie.com"})


class CommittedSourceTest(unittest.TestCase):
    def test_the_reviewed_file_is_clean_dated_and_admitted(self):
        doc = json.loads(M.LIVE_STREAMS_PATH.read_text(encoding="utf-8"))
        items, _, _, rejected = M.load_live_streams(M.LIVE_STREAMS_PATH, [])
        self.assertEqual(rejected, [], "every record's last check passed")
        self.assertEqual(len(items), len(doc["items"]))
        for record in doc["items"]:
            self.assertRegex(record["check"]["checked_at"], r"^\d{4}-\d\d-\d\dT[\d:]{8}Z$")
            self.assertTrue(record.get("reason") and record.get("owner"), record["provider_id"])
            self.assertEqual(list(M.private_strings(record, False)), [], record["provider_id"])
        for entry in doc["left_out"]:
            self.assertTrue(entry["reason"] and entry["research_id"], entry)
        self.assertFalse({e["research_id"] for e in doc["left_out"]} & {i["provider_id"] for i in doc["items"]})


if __name__ == "__main__":
    unittest.main()
