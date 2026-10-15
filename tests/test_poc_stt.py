"""Stdlib contract tests for the local STT PoC (FR-07..09, NFR-05, T01, T11)."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.poc_stt import PocError, _make_model, main, transcribe_file


class FakeModel:
    def __init__(self, segments=None, duration=2.0):
        self.segments = segments if segments is not None else [
            SimpleNamespace(start=0.2, end=1.4, text="테스트 문장")
        ]
        self.duration = duration
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return iter(self.segments), SimpleNamespace(duration=self.duration)


class PocSttTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "sample audio.wav"
        self.source.write_bytes(b"placeholder audio")
        self.output = self.root / "result.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_transcribes_local_file_and_writes_complete_json(self):
        model = FakeModel()
        duration, elapsed = transcribe_file(
            self.source, self.output, model_factory=lambda *args: model
        )
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(duration, 2.0)
        self.assertGreaterEqual(elapsed, 0)
        self.assertEqual(result["language"], "ko")
        self.assertEqual(result["segments"][0]["text"], "테스트 문장")
        self.assertEqual(model.calls[0][1], {
            "language": "ko", "beam_size": 5, "temperature": 0,
        })
        self.assertFalse(list(self.root.glob(".poc-stt-*.tmp")))

    def test_existing_output_is_preserved_without_running_model(self):
        self.output.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(PocError, "E_OUTPUT_EXISTS"):
            transcribe_file(self.source, self.output, model_factory=lambda *args: self.fail())
        self.assertEqual(self.output.read_text(encoding="utf-8"), "keep")

    def test_empty_audio_and_invalid_segment_do_not_create_output(self):
        for model, expected in (
            (FakeModel(segments=[]), "E_AUDIO_EMPTY"),
            (FakeModel(segments=[SimpleNamespace(start=0.8, end=0.3, text="secret")]),
             "E_SEGMENT_INVALID"),
            (FakeModel(segments=[SimpleNamespace(start=0.1, end=0.8, text=" ")]),
             "E_AUDIO_EMPTY"),
            (FakeModel(segments=[SimpleNamespace(start=0.1, end=0.8, text=None)]),
             "E_SEGMENT_INVALID"),
            (FakeModel(segments=[SimpleNamespace(start=0.1, end=1.0, text="one"),
                                 SimpleNamespace(start=0.9, end=1.2, text="two")]),
             "E_SEGMENT_INVALID"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(PocError, expected):
                    transcribe_file(self.source, self.output, model_factory=lambda *args: model)
                self.assertFalse(self.output.exists())

    def test_cpu_uses_int8_and_default_mode_is_offline(self):
        calls = []

        class WhisperModel:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        with patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=WhisperModel)}):
            _make_model("large-v3", "cpu", False)
        self.assertEqual(calls[0][1]["compute_type"], "int8")
        self.assertIs(calls[0][1]["local_files_only"], True)

    def test_cuda_dll_error_is_not_misclassified_as_missing_model(self):
        def unavailable(*_args, **_kwargs):
            raise RuntimeError("cublas64_12.dll not found")

        with patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=unavailable)}):
            with self.assertRaisesRegex(PocError, "E_GPU_DLL"):
                _make_model("large-v3", "cuda", False)

    def test_cli_error_does_not_print_input_path(self):
        missing = str(self.root / "private name.wav")
        with patch("sys.stdout"), patch("sys.stderr") as stderr:
            result = main([missing, str(self.output)])
        self.assertEqual(result, 1)
        self.assertNotIn(missing, "".join(call.args[0] for call in stderr.write.call_args_list))


if __name__ == "__main__":
    unittest.main()
