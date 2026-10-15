"""Offline tests for capture contracts: FR-02..06, T04/T05."""
import tempfile
import json
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from tools.poc_capture import CaptureError, TrackInfo, capture


class FakeStream:
    def __init__(self, payload: bytes, fail_read=False, start_delay=0):
        self.payload = payload
        self.fail_read = fail_read
        self.start_delay = start_delay
        self.closed = False

    def start_stream(self):
        time.sleep(self.start_delay)

    def read(self, frames, exception_on_overflow=False):
        time.sleep(0.001)
        if self.fail_read:
            raise OSError("private driver detail")
        return self.payload

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class FakeBackend:
    def __init__(self, silent=False, fail=False, fail_read=False, start_delay=0, short_read=False):
        self.silent = silent
        self.fail = fail
        self.fail_read = fail_read
        self.start_delay = start_delay
        self.short_read = short_read
        self.streams = []
        self.closed = False

    def open(self, info):
        if self.fail and info.label == "mic":
            raise RuntimeError("private device detail")
        payload = bytes(1024 * info.channels * 2) if self.silent else b"\x01\x00" * (1024 * info.channels)
        if self.short_read:
            payload = payload[:-1]
        stream = FakeStream(payload, self.fail_read, self.start_delay if info.label == "mic" else 0)
        self.streams.append(stream)
        return stream

    def close(self):
        self.closed = True


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.loop = TrackInfo(1, 48000, 2, "loop", True)
        self.mic = TrackInfo(2, 44100, 1, "mic")

    def test_streams_separate_tracks_and_atomic_manifest(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as root:
            session = capture(Path(root), self.loop, self.mic, .02, True, lambda: backend)
            self.assertTrue((session / "manifest.json").is_file())
            self.assertFalse((session / "manifest.json.tmp").exists())
            for name, rate, channels in (("loopback", 48000, 2), ("microphone", 44100, 1)):
                with wave.open(str(session / f"{name}.wav"), "rb") as wav:
                    self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (rate, channels, 2))
            self.assertTrue(backend.closed)
            self.assertTrue(all(stream.closed for stream in backend.streams))
            manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "completed")
            self.assertIsInstance(manifest["tracks"]["microphone"]["start_monotonic_ns"], int)
            self.assertGreater(manifest["tracks"]["microphone"]["peak_amplitude"], 0)

    def test_manifest_preserves_sequential_stream_start_offsets(self):
        backend = FakeBackend(start_delay=.02)
        with tempfile.TemporaryDirectory() as root:
            session = capture(Path(root), self.loop, self.mic, .04, True, lambda: backend)
            manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
            loop_ns = manifest["tracks"]["loopback"]["start_monotonic_ns"]
            mic_ns = manifest["tracks"]["microphone"]["start_monotonic_ns"]
            self.assertGreater(mic_ns - loop_ns, 10_000_000)

    def test_silence_fails_and_resources_close(self):
        backend = FakeBackend(silent=True)
        with tempfile.TemporaryDirectory() as root:
            session = None
            with self.assertRaisesRegex(CaptureError, "No input signal"):
                try:
                    capture(Path(root), self.loop, self.mic, .01, True, lambda: backend)
                except CaptureError:
                    session = next(Path(root).iterdir())
                    raise
            self.assertTrue(backend.closed)
            self.assertTrue(all(stream.closed for stream in backend.streams))
            manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["tracks"]["microphone"]["error_code"], "E_AUDIO_SILENT")

    def test_open_failure_is_sanitized_and_closes_backend(self):
        backend = FakeBackend(fail=True)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(CaptureError) as raised:
                capture(Path(root), self.loop, self.mic, .01, True, lambda: backend)
            self.assertNotIn("private", str(raised.exception))
            manifest = json.loads((next(Path(root).iterdir()) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "failed")
        self.assertTrue(backend.closed)
        self.assertTrue(all(stream.closed for stream in backend.streams))

    def test_stream_failure_has_safe_manifest_and_closes_streams(self):
        backend = FakeBackend(fail_read=True)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(CaptureError) as raised:
                capture(Path(root), self.loop, self.mic, .01, True, lambda: backend)
            self.assertNotIn("private", str(raised.exception))
            session = next(Path(root).iterdir())
            manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["tracks"]["loopback"]["error_code"], "E_AUDIO_DEVICE")
        self.assertTrue(backend.closed)
        self.assertTrue(all(stream.closed for stream in backend.streams))

    def test_short_pcm_block_fails_without_counting_incomplete_frames(self):
        backend = FakeBackend(short_read=True)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(CaptureError, "E_AUDIO_DEVICE"):
                capture(Path(root), self.loop, self.mic, .01, True, lambda: backend)
            manifest = json.loads((next(Path(root).iterdir()) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tracks"]["loopback"]["frames"], 0)
            self.assertEqual(manifest["tracks"]["loopback"]["error_code"], "E_AUDIO_DEVICE")

    def test_manifest_write_failure_is_not_reported_as_success(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as root:
            with patch("tools.poc_capture.Path.open", side_effect=OSError("private path")):
                with self.assertRaisesRegex(CaptureError, "E_DISK_WRITE"):
                    capture(Path(root), self.loop, self.mic, .01, True, lambda: backend)
            self.assertTrue(backend.closed)
            session = next(Path(root).iterdir())
            self.assertTrue((session / "loopback.wav").exists())
            self.assertFalse((session / "manifest.json").exists())

    def test_requires_consent_before_creating_session(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(CaptureError):
                capture(Path(root), self.loop, self.mic, .01, False, FakeBackend)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_rejects_wrong_device_kinds_and_nonfinite_duration(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(CaptureError):
                capture(Path(root), TrackInfo(1, 48000, 2, "not-loopback"), self.mic,
                        .01, True, FakeBackend)
            with self.assertRaises(CaptureError):
                capture(Path(root), self.loop, self.mic, float("nan"), True, FakeBackend)
            self.assertEqual(list(Path(root).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
