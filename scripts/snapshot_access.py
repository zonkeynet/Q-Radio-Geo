"""Apply bounded snapshot access evidence offline, independently of HLS health.

The caller supplies the reviewed provider policy registry. Event-provided host
claims and status labels never grant permissions or establish a result. Accepted
raw events are returned unchanged (as copies) for the audit ledger.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlsplit


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("invalid_checked_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_checked_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("checked_at_requires_timezone")
    return parsed.astimezone(timezone.utc)


def _approved_url(value, hosts):
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value) or "\\" in value:
        raise ValueError("invalid_media_url")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname in hosts
                 and parsed.port in (None, 443) and not parsed.username
                 and not parsed.password and not parsed.fragment)
    except ValueError as exc:
        raise ValueError("invalid_media_url") from exc
    if not valid:
        raise ValueError("media_url_outside_reviewed_https_hosts")
    return value


def _validate(item, event, provider_policies):
    if item.get("format") != "snapshot" or item.get("rights_status") != "official_public_feed":
        raise ValueError("item_is_not_an_authorized_snapshot")
    provider = item.get("provider")
    if event.get("provider") != provider:
        raise ValueError("provider_mismatch")
    policy = provider_policies.get(provider)
    if not isinstance(policy, dict):
        raise ValueError("provider_policy_missing")
    hosts = policy.get("media_hosts")
    if not isinstance(hosts, (list, tuple, set)) or not hosts or not all(isinstance(h, str) for h in hosts):
        raise ValueError("reviewed_media_hosts_missing")
    hosts = {h.lower() for h in hosts}
    original = _approved_url(event.get("url"), hosts)
    if original != item.get("snapshot_url"):
        raise ValueError("snapshot_url_mismatch")
    checked_at = _timestamp(event.get("checked_at"))
    size = event.get("bytes_read")
    if type(size) is not int or not 0 <= size <= 65536:
        raise ValueError("invalid_or_unbounded_byte_count")
    code = event.get("http_status")
    if code is not None and (type(code) is not int or not 100 <= code <= 599):
        raise ValueError("invalid_http_status")
    final = _approved_url(event.get("final_url") or original, hosts)
    redirects = event.get("redirects", [])
    if not isinstance(redirects, list) or len(redirects) > 2:
        raise ValueError("invalid_redirect_evidence")
    previous = original
    for redirect in redirects:
        if not isinstance(redirect, dict):
            raise ValueError("invalid_redirect_evidence")
        from_url = _approved_url(redirect.get("from_url"), hosts)
        to_url = _approved_url(redirect.get("to_url"), hosts)
        if from_url != previous or redirect.get("http_status") not in (301, 302, 303, 307, 308):
            raise ValueError("invalid_redirect_chain")
        previous = to_url
    if previous != final:
        raise ValueError("unaccounted_final_url")
    signature = event.get("signature")
    if signature is not None and not isinstance(signature, str):
        raise ValueError("invalid_signature")
    for field, expected in (("jpeg_signature", signature == "JPEG"), ("png_signature", signature == "PNG")):
        if field in event and (type(event[field]) is not bool or event[field] != expected):
            raise ValueError("contradictory_signature_evidence")
    if code is not None and 200 <= code < 300 and signature in ("JPEG", "PNG") and size > 0:
        status = "image_reachable"
    elif code in (404, 410):
        status = "not_found"
    elif code in (401, 403):
        status = "access_restricted"
    elif code is None and "timeout" in str(event.get("inconclusive_reason", "")).lower():
        status = "network_inconclusive"
    else:
        status = "inconclusive"
    return checked_at, {
        "status": status, "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "url": original, "final_url": final, "http_status": code,
        "content_type": event.get("content_type"), "bytes_read": size,
        "signature": signature, "cors": deepcopy(event.get("cors", {})),
        "inconclusive_reason": event.get("inconclusive_reason"),
        "freshness_checked": False, "live_checked": False,
    }


def apply_snapshot_access_checks(items, events, provider_policies):
    """Mutate only ``media_access`` on matching authorized snapshot records.

    Return raw accepted event copies, rejected events with reasons, and counts
    of the final snapshot ``media_access.status`` values. Older valid events
    remain in the accepted audit but cannot replace a newer observation. Equal
    timestamps keep the first observation, making replay idempotent.
    """
    records = {}
    duplicates = set()
    for item in items:
        record_id = item.get("id")
        if record_id in records:
            duplicates.add(record_id)
        records[record_id] = item
    accepted, rejected = [], []
    for event in events:
        try:
            if not isinstance(event, dict):
                raise ValueError("event_must_be_an_object")
            record_id = event.get("record_id")
            if not isinstance(record_id, str) or record_id not in records:
                raise ValueError("record_id_not_found")
            if record_id in duplicates:
                raise ValueError("ambiguous_duplicate_record_id")
            item = records[record_id]
            checked_at, access = _validate(item, event, provider_policies)
        except (ValueError, TypeError) as exc:
            rejected.append({"reason": str(exc), "event": deepcopy(event)})
            continue
        accepted.append(deepcopy(event))
        previous = item.get("media_access")
        previous_at = None
        if isinstance(previous, dict) and previous.get("url") == access["url"]:
            try:
                previous_at = _timestamp(previous.get("checked_at"))
            except ValueError:
                pass
        if previous_at is None or checked_at > previous_at:
            item["media_access"] = access
    counts = Counter(item["media_access"].get("status", "inconclusive") for item in items
                     if item.get("format") == "snapshot" and isinstance(item.get("media_access"), dict))
    return {"accepted_events": accepted, "rejected_events": rejected, "status_counts": dict(sorted(counts.items()))}
