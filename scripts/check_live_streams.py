#!/usr/bin/env python3
"""Re-check the owners' live streams in scripts/webcam_live_streams.json (docs/WEBCAM_LIVE_STREAMS.md).

YouTube: oEmbed must answer 200 (the owner allows embedding) and the watch page must say the video is live now. A
record with a channel also has its /live page read: when the channel now plays another video (the stream restarted),
the record takes the new id. Owner players: the host must be in EMBED_HOSTS; the player itself is not requested (several
hosts' robots.txt keep agents out). Each record's "check" is rewritten with the date and result; build_webcams.py
admits only "ok". A record that fails stays in the file with its reason, to be fixed or moved to "left_out" by hand.

Polite: at most one request every 0.6 s, a browser User-Agent, public pages only, no API key. Standard library only.
  python scripts/check_live_streams.py [--only PROVIDER_ID ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).parent))
import build_webcams as B  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
MIN_INTERVAL_S = 0.6
_last = [0.0]


def get(url, limit=4_000_000):
    """(status, body) of a public page; SOCS=CAI only answers YouTube's cookie-consent page (no account)."""
    wait = MIN_INTERVAL_S - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8", "Cookie": "SOCS=CAI"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read(limit).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError) as e:
        return None, str(e)


def first(pattern, text):
    m = re.search(pattern, text or "")
    return m.group(1) if m else None


def parse_watch(html):
    """What a YouTube watch page says about its video."""
    return {"playability": first(r'"playabilityStatus":\{"status":"(\w+)"', html),
            "playable_in_embed": first(r'"playableInEmbed":(true|false)', html) == "true",
            "live_now": first(r'"liveBroadcastDetails":\{"isLiveNow":(true|false)', html) == "true",
            "channel": first(r'"channelId":"(UC[\w-]{22})"', html)}


def live_video_of(channel_page):
    """The video a channel's /live page plays now (None when the channel is not live)."""
    return first(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', channel_page)


def verdict(video, oembed_status, watch, channel=None):
    """The check of one YouTube video: ok only when embedding is allowed and it is live now (and on the channel)."""
    if oembed_status != 200:
        return "fail", f"oEmbed answered {oembed_status}: embedding not allowed or video gone"
    if watch["playability"] != "OK" or not watch["playable_in_embed"]:
        return "fail", f"not playable ({watch['playability']})"
    if not watch["live_now"]:
        return "fail", "not live now (ended or replaced): look for the camera's new id on the owner's channel"
    if channel and watch["channel"] and watch["channel"] != channel:
        return "fail", "the video is on another channel"
    return "ok", None


def check_record(item, now):
    check = {"checked_at": now, "from": "check_live_streams.py, direct"}
    if item["format"] == "embed":
        host = urlsplit(item.get("embed_url") or "").hostname
        ok = host in B.EMBED_HOSTS and (item.get("embed_url") or "").startswith("https://")
        return {**check, "result": "ok" if ok else "fail", "method": "owner player: host reviewed in EMBED_HOSTS",
                **({} if ok else {"reason": "player host not in EMBED_HOSTS"})}
    ids = dict(item.get("youtube") or {})
    channel, video = ids.get("channel"), ids.get("video")
    if channel:
        status, page = get(f"https://www.youtube.com/channel/{channel}/live")
        now_playing = live_video_of(page) if status == 200 else None
        if not now_playing:
            return {**check, "result": "fail", "method": "YouTube channel live", "reason": "the channel is not live now"}
        if now_playing != video:  # the stream restarted: the thumbnail follows the new id
            item.setdefault("previous_videos", [])
            if video and video not in item["previous_videos"]:
                item["previous_videos"].append(video)
            item["youtube"] = {"channel": channel, "video": now_playing}
            video = now_playing
    status, _ = get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video}&format=json", 65536)
    _, html = get(f"https://www.youtube.com/watch?v={video}")
    watch = parse_watch(html)
    result, reason = verdict(video, status, watch, channel)
    return {**check, "result": result, "method": "YouTube oEmbed and watch page" + (", channel live" if channel else ""),
            "oembed": status, "live_now": watch["live_now"], "video": video, **({"reason": reason} if reason else {})}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=B.LIVE_STREAMS_PATH)
    ap.add_argument("--only", nargs="*", default=None, help="provider_id values to check (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="print the results without writing the file")
    args = ap.parse_args()
    doc = json.loads(args.file.read_text(encoding="utf-8"))
    counts = {"ok": 0, "fail": 0}
    for item in doc["items"]:
        if args.only is not None and item["provider_id"] not in args.only:
            continue
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        item["check"] = check_record(item, now)
        counts[item["check"]["result"]] = counts.get(item["check"]["result"], 0) + 1
        print(item["provider_id"], item["check"]["result"], item["check"].get("reason") or "", flush=True)
    doc["checked_at"] = max(i["check"]["checked_at"] for i in doc["items"])
    if not args.dry_run:
        args.file.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
