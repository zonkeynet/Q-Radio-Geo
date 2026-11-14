#!/usr/bin/env python3
"""Bounded, resumable checks of approved public Caltrans or Vegvesen HLS URLs.

Examples (these commands perform network requests)::
    python scripts/check_webcams.py --catalog data/webcams.json --out health.jsonl
    python scripts/check_webcams.py --mode live --limit 30 --budget-seconds 300

Only metadata and hashes are written. No video, snapshots, cookies, credentials,
or authentication headers are retained or supplied. A positive result means HLS
progression and media-byte access, not camera capture-time or Android decoding
certification. Unchanged playlists and segment errors remain inconclusive.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


ALLOWED_HOST = "wzmedia.dot.ca.gov"
PROVIDER_HOSTS = {"caltrans": ALLOWED_HOST, "vegvesen": "kamera.vegvesen.no"}
MAX_BYTES = 64 * 1024
TIMEOUT_SECONDS = 8.0
MAX_REDIRECTS = 3
MAX_INTERVAL_SECONDS = 60.0
MAX_TASKS = 6
RIGHTS_STATUS = "official_public_feed"


class CheckError(Exception):
    def __init__(self, message, code=None, kind="network_unverified", retry_after=None):
        super().__init__(message)
        self.code = code
        self.kind = kind
        self.retry_after = retry_after


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def allowed_url(value, host=ALLOWED_HOST):
    """Return a normalized URL or reject it before any connection is attempted."""
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise CheckError("Invalid URL characters", kind="url_rejected")
    try:
        u = urllib.parse.urlsplit(value)
        if (u.scheme.lower() != "https" or u.hostname != host or
                u.username is not None or u.password is not None or
                u.port not in (None, 443) or u.fragment):
            raise ValueError("URL outside the HTTPS origin allowlist")
    except ValueError as exc:
        raise CheckError("URL outside the HTTPS origin allowlist", kind="url_rejected") from exc
    return urllib.parse.urlunsplit(("https", host, u.path or "/", u.query, ""))


def attributes(value):
    return {m.group(1): m.group(2).strip('"') for m in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', value)}


def parse_playlist(body, base_url, host=ALLOWED_HOST):
    """Parse one bounded master/media playlist, including media byte ranges."""
    if len(body) >= MAX_BYTES:
        raise CheckError("Playlist reached the 64 KiB inspection limit", kind="invalid_manifest")
    try:
        lines = [line.strip() for line in body.decode("utf-8-sig").splitlines() if line.strip()]
    except UnicodeError as exc:
        raise CheckError("Playlist is not UTF-8", kind="invalid_manifest") from exc
    if not lines or lines[0] != "#EXTM3U":
        raise CheckError("Missing EXTM3U header", kind="invalid_manifest")
    result = {"valid": True, "variants": [], "segments": [], "sequence": 0,
              "target_duration": None, "endlist": False, "encrypted": False}
    pending_variant = None
    pending_segment = False
    pending_range = None
    previous_range_end = None
    previous_url = None
    for line in lines[1:]:
        try:
            if line.startswith("#EXT-X-STREAM-INF:"):
                a = attributes(line.split(":", 1)[1])
                pending_variant = int(a.get("BANDWIDTH", "0"))
            elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                result["sequence"] = int(line.split(":", 1)[1])
                if result["sequence"] < 0:
                    raise ValueError("negative sequence")
            elif line.startswith("#EXT-X-TARGETDURATION:"):
                duration = float(line.split(":", 1)[1])
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError("invalid target duration")
                result["target_duration"] = duration
            elif line.startswith("#EXTINF:"):
                pending_segment = True
            elif line.startswith("#EXT-X-BYTERANGE:"):
                match = re.fullmatch(r"(\d+)(?:@(\d+))?", line.split(":", 1)[1])
                if not match or int(match.group(1)) <= 0:
                    raise ValueError("invalid byte range")
                pending_range = (int(match.group(1)), int(match.group(2)) if match.group(2) else None)
            elif line.startswith("#EXT-X-KEY:"):
                result["encrypted"] |= attributes(line.split(":", 1)[1]).get("METHOD", "NONE") != "NONE"
            elif line == "#EXT-X-ENDLIST":
                result["endlist"] = True
            elif not line.startswith("#"):
                url = allowed_url(urllib.parse.urljoin(base_url, line), host)
                if pending_variant is not None:
                    result["variants"].append({"url": url, "bandwidth": pending_variant})
                    pending_variant = None
                elif pending_segment:
                    length, offset = pending_range or (None, None)
                    if length is not None and offset is None:
                        if previous_url != url or previous_range_end is None:
                            raise ValueError("implicit byte range without previous range on the same resource")
                        offset = previous_range_end
                    result["segments"].append({"url": url, "range_start": offset, "range_length": length})
                    previous_range_end = offset + length if offset is not None else None
                    previous_url = url
                    pending_segment, pending_range = False, None
        except (ValueError, OverflowError) as exc:
            raise CheckError("Malformed HLS numeric field or byte range", kind="invalid_manifest") from exc
    if pending_variant is not None or pending_segment or pending_range is not None:
        raise CheckError("Incomplete playlist entry", kind="invalid_manifest")
    if result["variants"] and result["segments"]:
        raise CheckError("Mixed master/media playlist", kind="invalid_manifest")
    return result


def segment_identity(segment):
    # Query-only token rotation must never count as media progression.
    u = urllib.parse.urlsplit(segment["url"])
    return (u.scheme, u.netloc, u.path, segment["range_start"], segment["range_length"])


def progression(first, second):
    old = {segment_identity(s) for s in first["segments"]}
    changed = bool(second["segments"] and segment_identity(second["segments"][-1]) not in old)
    increased = second["sequence"] > first["sequence"]
    return {"sequence_advanced": increased, "sequence_reset": second["sequence"] < first["sequence"],
            "segment_identity_changed": changed,
            "advancing": bool((increased or changed) and first["segments"] and second["segments"]
                              and not first["endlist"] and not second["endlist"])}


def media_signature(body):
    if len(body) >= 377 and body[0] == body[188] == body[376] == 0x47:
        return "mpeg_ts"
    # An ftyp/styp header alone can be an initialization file or a truncated
    # response. Require a complete movie fragment followed by actual media
    # payload in the bounded prefix. This is structural evidence, not decoding.
    offset, fragment = 0, False
    for _ in range(64):
        if offset + 8 > len(body):
            return None
        size, kind = int.from_bytes(body[offset:offset + 4], "big"), body[offset + 4:offset + 8]
        header = 8
        if size == 1:
            if offset + 16 > len(body):
                return None
            size, header = int.from_bytes(body[offset + 8:offset + 16], "big"), 16
        if size == 0:
            size = len(body) - offset
        if size < header:
            return None
        end = offset + size
        if kind == b"mdat":
            return "fragmented_mp4" if fragment and min(end, len(body)) - offset - header >= 16 else None
        if end > len(body):
            return None
        if kind == b"moof":
            child, mfhd, traf = offset + header, False, False
            while child + 8 <= end:
                child_size = int.from_bytes(body[child:child + 4], "big")
                child_kind = body[child + 4:child + 8]
                if child_size < 8 or child + child_size > end:
                    return None
                mfhd |= child_kind == b"mfhd" and child_size >= 16
                traf |= child_kind == b"traf" and child_size >= 24
                child += child_size
            fragment = child == end and mfhd and traf
        elif kind not in (b"ftyp", b"styp", b"sidx", b"emsg", b"prft", b"free", b"skip"):
            return None
        offset = end
    return None


class BoundedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, client, request_deadline):
        self.client, self.deadline, self.count = client, request_deadline, 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.client.ensure_running()
        self.count += 1
        if self.count > MAX_REDIRECTS:
            raise CheckError("Redirect limit reached", kind="redirect_rejected")
        allowed_url(newurl, self.client.allowed_host)
        self.client.throttle_start()
        remaining = self.deadline - self.client.clock()
        if remaining <= 0:
            raise CheckError("Request timed out during redirect", kind="timeout")
        req.timeout = min(TIMEOUT_SECONDS, remaining)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    """Two connections, one request start per 0.5 s, bounded I/O and cancellation."""
    def __init__(self, budget_seconds, provider="caltrans"):
        self.allowed_host = PROVIDER_HOSTS[provider]
        self.clock = time.monotonic
        self.deadline = self.clock() + budget_seconds
        self.stop = threading.Event()
        self.stop_reason = None
        self.slots = threading.BoundedSemaphore(2)
        self.rate_lock = threading.Lock()
        self.next_request = 0.0

    def ensure_running(self):
        if self.clock() >= self.deadline:
            self.stop_reason = self.stop_reason or "budget_exhausted"
            self.stop.set()
        if self.stop.is_set():
            raise CheckError(self.stop_reason or "Run stopped", kind=self.stop_reason or "stopped")

    def wait(self, seconds):
        until = self.clock() + seconds
        while self.clock() < until:
            self.ensure_running()
            self.stop.wait(min(0.2, max(0, until - self.clock()), max(0, self.deadline - self.clock())))
        self.ensure_running()

    def throttle_start(self):
        with self.rate_lock:
            self.wait(max(0, self.next_request - self.clock()))
            self.next_request = self.clock() + 0.5

    def get(self, url, segment=None):
        url = allowed_url(url, self.allowed_host)
        self.ensure_running()
        acquired = False
        try:
            while not acquired:
                self.ensure_running()
                acquired = self.slots.acquire(timeout=0.2)
            self.throttle_start()
            request_deadline = min(self.deadline, self.clock() + TIMEOUT_SECONDS)
            headers = {"User-Agent": "Q-Globe-public-stream-checker/1.0", "Accept-Encoding": "identity"}
            start, limit = 0, MAX_BYTES
            if segment is not None:
                start = segment["range_start"] or 0
                limit = min(MAX_BYTES, segment["range_length"] or MAX_BYTES)
                headers["Range"] = f"bytes={start}-{start + limit - 1}"
            opener = urllib.request.build_opener(BoundedRedirect(self, request_deadline))
            request = urllib.request.Request(url, headers=headers)
            with opener.open(request, timeout=max(0.001, request_deadline - self.clock())) as response:
                final_url = allowed_url(response.geturl(), self.allowed_host)
                code = response.status
                if code not in ((200, 206) if segment is not None else (200,)):
                    raise CheckError(f"Unexpected HTTP status {code}", code=code)
                if segment is not None and segment["range_start"] is not None:
                    content_range = re.match(r"bytes (\d+)-(\d+)/(?:\d+|\*)$", response.headers.get("Content-Range", ""))
                    if code != 206 or not content_range or int(content_range.group(1)) != start:
                        raise CheckError("Server did not honor the playlist byte range", code=code, kind="range_unverified")
                body = bytearray()
                while len(body) < limit:
                    self.ensure_running()
                    remaining = request_deadline - self.clock()
                    if remaining <= 0:
                        raise CheckError("Request body timed out", kind="timeout")
                    # HTTPResponse's socket timeout is tightened against the same
                    # total request deadline; read1 avoids an unbounded fill loop.
                    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    chunk = response.read1(min(8192, limit - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                return bytes(body), {"http_status": code, "content_type": response.headers.get("Content-Type", ""),
                                     "url": final_url}
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                self.stop_reason = "rate_limited" if exc.code == 429 else "auth_required"
                self.stop.set()
            kind = "rate_limited" if exc.code == 429 else "auth_required" if exc.code in (401, 403) else "http_error"
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            exc.close()
            raise CheckError(f"HTTP Error {exc.code}", code=exc.code, kind=kind,
                             retry_after=retry_after) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise CheckError("Request timed out", kind="timeout") from exc
        except urllib.error.URLError as exc:
            raise CheckError("Network request failed", kind="network_unverified") from exc
        finally:
            if acquired:
                self.slots.release()


def probe(url, mode, client):
    host = getattr(client, "allowed_host", ALLOWED_HOST)
    event = {"url": url, "mode": mode, "checked_at": None, "manifest_valid": False,
             "segment_ok": False, "advancing": False, "live_verified": False,
             "http_status": None, "status": "unverified", "stage": "manifest"}
    try:
        body, meta = client.get(url)
        event["http_status"] = meta["http_status"]
        first = parse_playlist(body, meta["url"], host)
        event["manifest_valid"] = True
        if mode == "manifests":
            event.update(status="manifest_reachable", stage="complete")
            return event
        media_url = meta["url"]
        if first["variants"]:
            event["stage"] = "variant"
            media_url = min(first["variants"], key=lambda v: v["bandwidth"])["url"]
            body, meta = client.get(media_url)
            media_url = meta["url"]
            first = parse_playlist(body, media_url, host)
        event.update(media_url=media_url, first_sequence=first["sequence"], endlist=first["endlist"])
        if first["variants"] or not first["segments"] or first["target_duration"] is None:
            raise CheckError("Expected one complete media playlist", kind="unsupported_playlist")
        if first["encrypted"]:
            raise CheckError("Encrypted media is outside this byte-signature check", kind="encrypted_media_unverified")
        if first["endlist"]:
            event.update(status="finite_playlist", stage="complete")
            return event
        interval = 2 * first["target_duration"] + 1
        event.update(stage="interval", target_duration_seconds=first["target_duration"])
        if interval > MAX_INTERVAL_SECONDS:
            raise CheckError("Required observation interval exceeds 60 seconds", kind="progression_unknown")
        started = client.clock()
        client.wait(interval)
        event["stage"] = "second_manifest"
        body, meta = client.get(media_url)
        second = parse_playlist(body, meta["url"], host)
        event.update(elapsed_seconds=client.clock() - started, same_media_url=media_url == meta["url"],
                     second_sequence=second["sequence"], endlist=second["endlist"])
        if second["variants"] or not second["segments"] or second["target_duration"] is None:
            raise CheckError("Second media playlist is incomplete", kind="progression_unknown")
        if second["encrypted"]:
            raise CheckError("Second playlist requests encrypted media", kind="encrypted_media_unverified")
        evidence = progression(first, second)
        event.update(evidence)
        enough_time = event["elapsed_seconds"] >= 2 * max(first["target_duration"], second["target_duration"]) + 1
        event["advancing"] = bool(evidence["advancing"] and event["same_media_url"] and enough_time)
        event["stage"] = "segment"
        body, meta = client.get(second["segments"][-1]["url"], segment=second["segments"][-1])
        signature = media_signature(body)
        event.update(segment_http_status=meta["http_status"], segment_content_type=meta["content_type"],
                     segment_bytes_sampled=len(body), segment_prefix_sha256=hashlib.sha256(body).hexdigest(),
                     segment_signature=signature, segment_ok=signature is not None)
        event["live_verified"] = bool(event["manifest_valid"] and event["segment_ok"] and event["advancing"] and not event["endlist"])
        event.update(status="live_progress_verified" if event["live_verified"] else "progression_unknown", stage="complete")
    except CheckError as exc:
        event.update(status=exc.kind, error=str(exc), live_verified=False)
        if event["stage"] == "manifest" and exc.code is not None:
            event["http_status"] = exc.code
        if exc.code is not None:
            event["failure_http_status"] = exc.code
        if exc.retry_after:
            event["retry_after"] = str(exc.retry_after)[:100]
    except (OSError, ValueError) as exc:
        event.update(status="network_unverified", error=type(exc).__name__, live_verified=False)
    finally:
        event["checked_at"] = utc_now()
    return event


def select_urls(catalog, provider="caltrans"):
    host = PROVIDER_HOSTS[provider]
    urls = []
    seen = set()
    skipped = {"rights": 0, "format": 0, "url": 0, "duplicate": 0, "provider": 0}
    for item in catalog.get("items", []):
        if not isinstance(item, dict):
            skipped["format"] += 1
            continue
        if item.get("provider") != provider:
            skipped["provider"] += 1
            continue
        if item.get("rights_status") != RIGHTS_STATUS:
            skipped["rights"] += 1
            continue
        if item.get("format") != "hls":
            skipped["format"] += 1
            continue
        try:
            url = allowed_url(item.get("stream_url"), host)
        except CheckError:
            skipped["url"] += 1
            continue
        if url in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(url)
        urls.append(url)
    return urls, skipped


def recent_checks(path, mode, refresh_hours, now=None, host=ALLOWED_HOST):
    now = now or dt.datetime.now(dt.timezone.utc)
    fresh = set()
    if not path.exists() or refresh_hours == 0:
        return fresh
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
                if event.get("status") in ("budget_exhausted", "stopped", "interrupted"):
                    continue
                stamp = dt.datetime.fromisoformat(event["checked_at"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    continue
                age = (now - stamp).total_seconds()
                level = event.get("mode", "live" if event.get("live_verified") is True else "manifests")
                if 0 <= age < refresh_hours * 3600 and (mode == "manifests" or level == "live"):
                    fresh.add(allowed_url(event["url"], host))
            except (ValueError, KeyError, TypeError, CheckError):
                continue
    return fresh


def run_checks(urls, mode, client, output):
    """Keep at most six tasks in flight; never queue the full catalog."""
    iterator = iter(urls)
    completed = 0
    pending = set()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_TASKS)
    try:
        for _ in range(min(MAX_TASKS, len(urls))):
            pending.add(pool.submit(probe, next(iterator), mode, client))
        while pending:
            if client.clock() >= client.deadline:
                client.stop_reason = client.stop_reason or "budget_exhausted"
                client.stop.set()
            done, pending = concurrent.futures.wait(pending, timeout=0.2, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                if future.cancelled():
                    continue
                event = future.result()
                if event["http_status"] is None and event["status"] in ("budget_exhausted", "stopped", "interrupted", "auth_required", "rate_limited"):
                    # No response/evidence: do not overwrite previous health or
                    # suppress a future check merely because this run stopped.
                    continue
                output.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                output.flush()
                completed += 1
                if not client.stop.is_set():
                    try:
                        pending.add(pool.submit(probe, next(iterator), mode, client))
                    except StopIteration:
                        pass
            if client.stop.is_set():
                for future in pending:
                    future.cancel()
    except KeyboardInterrupt:
        client.stop_reason = "interrupted"
        client.stop.set()
        for future in pending:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return completed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=pathlib.Path, default=pathlib.Path("data/webcams.json"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("health.jsonl"))
    parser.add_argument("--mode", choices=("manifests", "live"), default="manifests")
    parser.add_argument("--provider", choices=tuple(PROVIDER_HOSTS), default="caltrans", help="Fixed approved provider and HTTPS origin; run providers separately")
    parser.add_argument("--limit", type=int, default=30, help="Maximum new checks; 0 means all eligible URLs, still within time budget")
    parser.add_argument("--budget-seconds", type=float, default=300)
    parser.add_argument("--refresh-hours", type=float, default=6, help="Skip recent JSONL checks of sufficient depth; 0 forces refresh")
    args = parser.parse_args(argv)
    if args.limit < 0 or not math.isfinite(args.budget_seconds) or args.budget_seconds <= 0 or not math.isfinite(args.refresh_hours) or args.refresh_hours < 0:
        parser.error("limit and refresh-hours must be nonnegative; budget-seconds must be positive")
    if args.catalog.resolve() == args.out.resolve() or (args.out.exists() and args.catalog.samefile(args.out)):
        parser.error("The output must not overwrite the input catalog")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        parser.error("Expected a catalog object with an items array")
    urls, skipped = select_urls(catalog, args.provider)
    fresh = recent_checks(args.out, args.mode, args.refresh_hours, host=PROVIDER_HOSTS[args.provider])
    eligible = [url for url in urls if url not in fresh]
    selected = eligible[:args.limit] if args.limit else eligible
    args.out.parent.mkdir(parents=True, exist_ok=True)
    client = HttpClient(args.budget_seconds, args.provider)
    interrupted = False
    with args.out.open("a", encoding="utf-8") as output:
        # Recover appendability after an interrupted final line, without deleting history.
        if args.out.stat().st_size:
            with args.out.open("rb") as existing:
                existing.seek(-1, 2)
                if existing.read(1) != b"\n":
                    output.write("\n")
        try:
            completed = run_checks(selected, args.mode, client, output)
        except KeyboardInterrupt:
            completed, interrupted = None, True
    print(json.dumps({"selected": len(selected), "completed": completed, "recent_skipped": len(urls) - len(eligible),
                      "catalog_skipped": skipped, "stop_reason": client.stop_reason,
                      "output": str(args.out), "mode": args.mode, "provider": args.provider}))
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
