"""Synthetic WAV tests for timing metadata audit (T04/T05; no audio device required)."""

import json
import tempfile
import unittest
import wave
from pathlib import Path

from tools.check_sync import AuditError, audit_manifest, main


class SyncAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = Path(self.temp.name)
        self.manifest_path = self.session / "manifest.json"
        self.manifest = {
            "format_version": 1,
            "duration_requested_seconds": 60,
            "consent_acknowledged": True,
            "status": "completed",
            "tracks": {},
        }
        for name, rate, channels, frames, start_ns in (
            ("loopback", 100, 2, 6000, 2_000_000_000),
            ("microphone", 200, 1, 12000, 2_050_000_000),
        ):
            file_name = name + ".wav"
            with wave.open(str(self.session / file_name), "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(b"\x01\x00" * channels * frames)
            self.manifest["tracks"][name] = {
                "file": file_name,
                "sample_rate_hz": rate,
                "channels": channels,
                "sample_format": "pcm_s16le",
                "start_monotonic_ns": start_ns,
                "frames": frames,
                "status": "completed",
                "error_code": None,
            }
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_reports_consistent_timing_metadata_with_scope_statement(self):
        result = audit_manifest(self.manifest_path)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["start_offset_ms"], 50.0)
        self.assertEqual(result["duration_difference_ms"], 0.0)
        self.assertEqual(result["requested_duration_difference_ms"], 0.0)
        self.assertIn("no measured acoustic drift", result["statement"])

    def test_rejects_manifest_for_failed_capture(self):
        self.manifest["status"] = "failed"
        self.write_manifest()
        with self.assertRaisesRegex(AuditError, "E_CAPTURE_INCOMPLETE"):
            audit_manifest(self.manifest_path)

    def test_rejects_wav_metadata_that_disagrees_with_manifest(self):
        self.manifest["tracks"]["microphone"]["frames"] -= 1
        self.write_manifest()
        with self.assertRaisesRegex(AuditError, "E_TRACK_MISMATCH"):
            audit_manifest(self.manifest_path)

    def test_rejects_truncated_wav_even_when_header_claims_full_duration(self):
        wav_path = self.session / "loopback.wav"
        wav_path.write_bytes(wav_path.read_bytes()[:-100])
        with self.assertRaisesRegex(AuditError, "E_TRACK_MISMATCH"):
            audit_manifest(self.manifest_path)

    def test_rejects_path_escape(self):
        self.manifest["tracks"]["loopback"]["file"] = "../outside.wav"
        self.write_manifest()
        with self.assertRaisesRegex(AuditError, "E_TRACK_PATH"):
            audit_manifest(self.manifest_path)

    def test_rejects_start_offset_beyond_default_tolerance(self):
        self.manifest["tracks"]["microphone"]["start_monotonic_ns"] += 100_000_001
        self.write_manifest()
        with self.assertRaisesRegex(AuditError, "E_SYNC_TOLERANCE"):
            audit_manifest(self.manifest_path)

    def test_rejects_tracks_shorter_than_requested_capture_duration(self):
        self.manifest["duration_requested_seconds"] = 61
        self.write_manifest()
        with self.assertRaisesRegex(AuditError, "E_CAPTURE_DURATION_MISMATCH"):
            audit_manifest(self.manifest_path)

    def test_cli_failure_is_sanitized(self):
        private_path = str(self.session / "private session" / "missing.json")
        from unittest.mock import patch
        with patch("sys.stderr") as stderr:
            result = main([private_path])
        output = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertEqual(result, 1)
        self.assertNotIn(private_path, output)
        self.assertIn("E_MANIFEST_READ", output)


if __name__ == "__main__":
    unittest.main()
