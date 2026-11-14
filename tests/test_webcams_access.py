"""Snapshot access evidence is bounded, policy checked and separate from health."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from snapshot_access import apply_snapshot_access_checks


class SnapshotAccessTest(unittest.TestCase):
    def setUp(self):
        self.policies = {"sample": {"media_hosts": ["images.example.org", "cdn.example.org"]}}
        self.item = {"id": "sample:1", "provider": "sample", "format": "snapshot",
                     "rights_status": "official_public_feed", "snapshot_url": "https://images.example.org/1.jpg",
                     "health": {"status": "unverified", "checked_at": None}}
        self.event = {"record_id": "sample:1", "provider": "sample", "url": self.item["snapshot_url"],
                      "final_url": self.item["snapshot_url"], "checked_at": "2026-11-14T02:09:00Z",
                      "http_status": 206, "bytes_read": 65536, "signature": "JPEG", "jpeg_signature": True,
                      "png_signature": False, "content_type": "image/jpeg", "cors": {}, "redirects": []}

    def apply(self, event=None, item=None):
        return apply_snapshot_access_checks([self.item if item is None else item],
                                            [self.event if event is None else event], self.policies)

    def test_reachable_changes_only_media_access_and_preserves_raw_audit(self):
        before, event = deepcopy(self.item), deepcopy(self.event)
        result = self.apply()
        self.assertEqual({k: v for k, v in self.item.items() if k != "media_access"}, before)
        self.assertEqual(result["accepted_events"], [event])
        self.assertEqual(result["status_counts"], {"image_reachable": 1})
        self.assertIsNot(result["accepted_events"][0], self.event)
        self.assertFalse(self.item["media_access"]["live_checked"])
        self.assertFalse(self.item["media_access"]["freshness_checked"])

    def test_fourteen_sample_outcomes_without_network(self):
        # Same status/signature distribution as the 14-provider bounded probe.
        samples = [(206, "JPEG", 65536)] * 8 + [(200, "JPEG", 22172), (206, "PNG", 65536)]
        samples += [(403, None, 0), (403, None, 0), (404, None, 0), (None, None, 0)]
        items, events = [], []
        for n, (code, signature, size) in enumerate(samples):
            item = {**deepcopy(self.item), "id": f"sample:{n}", "snapshot_url": f"https://images.example.org/{n}.jpg"}
            event = {**self.event, "record_id": item["id"], "url": item["snapshot_url"], "final_url": item["snapshot_url"],
                     "http_status": code, "signature": signature, "bytes_read": size,
                     "jpeg_signature": signature == "JPEG", "png_signature": signature == "PNG",
                     "inconclusive_reason": "network_timeout_no_retry" if code is None else None}
            items.append(item); events.append(event)
        result = apply_snapshot_access_checks(items, events, self.policies)
        self.assertEqual(len(result["accepted_events"]), 14)
        self.assertEqual(result["rejected_events"], [])
        self.assertEqual(result["status_counts"], {"image_reachable": 10, "access_restricted": 2,
                                                  "not_found": 1, "network_inconclusive": 1})

    def test_http_and_payload_evidence_override_labels_and_mime(self):
        for code, signature, size, expected in [(403, "JPEG", 5, "access_restricted"),
                (410, "JPEG", 5, "not_found"), (429, None, 0, "inconclusive"),
                (200, "unrecognized", 5, "inconclusive"), (200, "JPEG", 0, "inconclusive"),
                (200, "PNG", 5, "image_reachable")]:
            with self.subTest(code=code, signature=signature, size=size):
                item = deepcopy(self.item)
                event = {**self.event, "http_status": code, "signature": signature, "bytes_read": size,
                         "jpeg_signature": signature == "JPEG", "png_signature": signature == "PNG",
                         "status": "live_confirmed", "live_checked": True, "freshness_checked": True}
                self.assertEqual(self.apply(event, item)["rejected_events"], [])
                self.assertEqual(item["media_access"]["status"], expected)
                self.assertFalse(item["media_access"]["live_checked"])

    def test_rejects_wrong_identity_url_hosts_and_contradictions(self):
        bad = [{"record_id": "sample:missing"}, {"provider": "other"},
               {"url": "https://images.example.org/2.jpg"},
               {"final_url": "https://evil.example.org/1.jpg", "approved_media_hosts": ["evil.example.org"]},
               {"final_url": "http://images.example.org/1.jpg"},
               {"final_url": "https://user:password@images.example.org/1.jpg"},
               {"checked_at": "2026-11-14T02:09:00"}, {"checked_at": "invalid"},
               {"bytes_read": 65537}, {"bytes_read": -1}, {"bytes_read": True},
               {"http_status": True}, {"signature": "PNG"}, {"png_signature": True}]
        for changes in bad:
            with self.subTest(changes=changes):
                item = deepcopy(self.item)
                result = self.apply({**self.event, **changes}, item)
                self.assertEqual(len(result["rejected_events"]), 1)
                self.assertNotIn("media_access", item)

    def test_reviewed_policy_cannot_be_replaced_by_event_claims(self):
        self.policies = {"sample": {"source": {"allowed_hosts": ["images.example.org"]}}}
        self.event["approved_media_hosts"] = ["images.example.org"]
        self.assertEqual(len(self.apply()["rejected_events"]), 1)

    def test_hls_and_page_records_are_untouched(self):
        for fmt in ("hls", "official_page"):
            item = {**deepcopy(self.item), "format": fmt, "health": {"status": "live_confirmed"}}
            before = deepcopy(item)
            self.assertEqual(len(self.apply(item=item)["rejected_events"]), 1)
            self.assertEqual(item, before)

    def test_latest_valid_check_wins_and_old_events_remain_in_audit(self):
        newer = {**self.event, "checked_at": "2026-11-14T04:10:00+02:00", "http_status": 404,
                 "bytes_read": 0, "signature": None, "jpeg_signature": False}
        result = apply_snapshot_access_checks([self.item], [newer, self.event], self.policies)
        self.assertEqual(len(result["accepted_events"]), 2)
        self.assertEqual(self.item["media_access"]["status"], "not_found")
        self.assertEqual(self.item["media_access"]["checked_at"], "2026-11-14T02:10:00Z")
        self.apply()
        self.assertEqual(self.item["media_access"]["status"], "not_found")

    def test_allowed_redirect_chain_and_rejected_intermediate_host(self):
        redirected = {**self.event, "final_url": "https://cdn.example.org/1.jpg", "redirects": [
            {"from_url": self.event["url"], "http_status": 302, "to_url": "https://cdn.example.org/1.jpg"}]}
        self.assertEqual(self.apply(redirected)["rejected_events"], [])
        redirected["redirects"][0]["from_url"] = "https://evil.example.org/1.jpg"
        self.assertEqual(len(self.apply(redirected)["rejected_events"]), 1)

    def test_duplicate_ids_fail_closed(self):
        result = apply_snapshot_access_checks([self.item, deepcopy(self.item)], [self.event], self.policies)
        self.assertEqual(result["rejected_events"][0]["reason"], "ambiguous_duplicate_record_id")


if __name__ == "__main__":
    unittest.main()
