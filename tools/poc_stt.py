"""Local faster-whisper proof of concept (FR-07..09, T01, T11)."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, Any


class PocError(Exception):
    """An error with a safe, stable code suitable for console reporting."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _make_model(model_name: str, device: str, allow_download: bool) -> Any:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise PocError("E_STT_UNAVAILABLE") from exc
    try:
        return WhisperModel(
            model_name,
            device=device,
            compute_type="float16" if device == "cuda" else "int8",
            local_files_only=not allow_download,
        )
    except Exception as exc:
        message = str(exc).lower()
        if any(word in message for word in ("out of memory", "cuda_error_out_of_memory")):
            code = "E_GPU_OOM"
        elif any(word in message for word in ("cuda", "cublas", "cudnn", "dll")):
            code = "E_GPU_DLL"
        elif any(word in message for word in ("download", "network", "404", "not found")):
            code = "E_MODEL_DOWNLOAD"
        else:
            code = "E_MODEL_LOAD"
        raise PocError(code) from exc


def _valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _atomic_write_json(destination: Path, payload: dict[str, Any]) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
            prefix=".poc-stt-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard-link creation is atomic and refuses an existing target.
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise PocError("E_OUTPUT_EXISTS") from exc
    except OSError as exc:
        raise PocError("E_OUTPUT_WRITE") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def transcribe_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    device: str = "cuda",
    model_name: str = "large-v3",
    allow_download: bool = False,
    model_factory: Callable[..., Any] | None = None,
) -> tuple[float, float]:
    """Transcribe a local file and atomically create JSON; return audio and elapsed seconds."""
    source = Path(input_path)
    destination = Path(output_path)
    if device not in ("cuda", "cpu"):
        raise PocError("E_DEVICE_UNSUPPORTED")
    if not source.is_file():
        raise PocError("E_INPUT_UNAVAILABLE")
    if destination.exists():
        raise PocError("E_OUTPUT_EXISTS")
    factory = model_factory or _make_model
    try:
        model = factory(model_name, device, allow_download)
    except PocError:
        raise
    except Exception as exc:
        raise PocError("E_MODEL_LOAD") from exc

    started = time.perf_counter()
    try:
        segments_iter, info = model.transcribe(
            str(source), language="ko", beam_size=5, temperature=0,
        )
        duration = info.duration
        if not _valid_number(duration) or duration <= 0:
            raise PocError("E_AUDIO_EMPTY")
        segments: list[dict[str, Any]] = []
        previous_end = -1.0
        for segment in segments_iter:
            start, end = segment.start, segment.end
            if (not _valid_number(start) or not _valid_number(end) or start < 0
                    or end <= start or start < previous_end or end > duration + 0.05):
                raise PocError("E_SEGMENT_INVALID")
            text = segment.text
            if not isinstance(text, str):
                raise PocError("E_SEGMENT_INVALID")
            if not text.strip():
                raise PocError("E_AUDIO_EMPTY")
            previous_end = end
            segments.append({"start": float(start), "end": float(end), "text": text})
        if not segments:
            raise PocError("E_AUDIO_EMPTY")
    except PocError:
        raise
    except Exception as exc:
        message = str(exc).lower()
        if "out of memory" in message:
            code = "E_GPU_OOM"
        elif any(word in message for word in ("cuda", "cublas", "cudnn", "dll")):
            code = "E_GPU_DLL"
        elif any(word in message for word in ("decode", "unsupported format", "audio")):
            code = "E_INPUT_UNSUPPORTED"
        else:
            code = "E_STT_FAILED"
        raise PocError(code) from exc

    elapsed = time.perf_counter() - started
    payload = {
        "model": model_name,
        "language": "ko",
        "device": device,
        "duration_seconds": float(duration),
        "elapsed_seconds": elapsed,
        "segments": segments,
    }
    _atomic_write_json(destination, payload)
    return float(duration), elapsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local faster-whisper STT PoC")
    parser.add_argument("input", help="local audio file")
    parser.add_argument("output", help="new JSON output file (must not already exist)")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--allow-download", action="store_true",
                        help="allow first-time model download; default requires a local model")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        duration, elapsed = transcribe_file(
            args.input, args.output, device=args.device, allow_download=args.allow_download,
        )
    except PocError as exc:
        print(f"STT failed: {exc.code}", file=sys.stderr)
        return 1
    except Exception:
        print("STT failed: E_INTERNAL", file=sys.stderr)
        return 1
    print(f"STT completed: duration={duration:.3f}s elapsed={elapsed:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
