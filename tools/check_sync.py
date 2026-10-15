"""Audit capture timing metadata and WAV consistency (FR-04, T04/T05; not acoustic drift)."""

from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from pathlib import Path
from typing import Any


class AuditError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _track_file(session: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise AuditError("E_MANIFEST_INVALID")
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise AuditError("E_TRACK_PATH")
    candidate = (session / rel).resolve()
    try:
        candidate.relative_to(session.resolve())
    except ValueError as exc:
        raise AuditError("E_TRACK_PATH") from exc
    if not candidate.is_file():
        raise AuditError("E_TRACK_MISSING")
    return candidate


def audit_manifest(
    manifest_path: str | Path,
    *,
    start_tolerance_ms: float = 100.0,
    duration_tolerance_ms: float = 100.0,
    minimum_duration_seconds: float = 60.0,
) -> dict[str, Any]:
    if (not _number(start_tolerance_ms) or start_tolerance_ms < 0
            or not _number(duration_tolerance_ms) or duration_tolerance_ms < 0
            or not _number(minimum_duration_seconds) or minimum_duration_seconds < 60):
        raise AuditError("E_TOLERANCE_INVALID")
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError("E_MANIFEST_READ") from exc
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        raise AuditError("E_MANIFEST_INVALID")
    if manifest.get("status") != "completed":
        raise AuditError("E_CAPTURE_INCOMPLETE")
    if manifest.get("consent_acknowledged") is not True:
        raise AuditError("E_CONSENT_MISSING")
    requested = manifest.get("duration_requested_seconds")
    if not _number(requested) or requested < minimum_duration_seconds:
        raise AuditError("E_CAPTURE_TOO_SHORT")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, dict) or set(tracks) != {"loopback", "microphone"}:
        raise AuditError("E_MANIFEST_INVALID")

    session = path.parent.resolve()
    metrics: dict[str, tuple[int, float]] = {}
    requested_deviations: dict[str, float] = {}
    for name in ("loopback", "microphone"):
        item = tracks[name]
        if not isinstance(item, dict) or item.get("status") != "completed":
            raise AuditError("E_CAPTURE_INCOMPLETE")
        if item.get("error_code") is not None:
            raise AuditError("E_CAPTURE_INCOMPLETE")
        sample_rate = item.get("sample_rate_hz")
        channels = item.get("channels")
        frames = item.get("frames")
        started = item.get("start_monotonic_ns")
        if (not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0
                or not isinstance(channels, int) or isinstance(channels, bool) or channels <= 0
                or not isinstance(frames, int) or isinstance(frames, bool) or frames <= 0
                or not isinstance(started, int) or isinstance(started, bool) or started <= 0
                or item.get("sample_format") != "pcm_s16le"):
            raise AuditError("E_TRACK_METADATA")
        wav_path = _track_file(session, item.get("file"))
        try:
            with wave.open(str(wav_path), "rb") as wav:
                actual = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes())
                payload_bytes = 0
                max_read_frames = max(1, 65_536 // (channels * 2))
                remaining = frames
                while remaining:
                    block = wav.readframes(min(remaining, max_read_frames))
                    if not block:
                        break
                    if len(block) % (channels * 2):
                        raise AuditError("E_WAV_INVALID")
                    payload_bytes += len(block)
                    remaining -= len(block) // (channels * 2)
        except (OSError, EOFError, wave.Error) as exc:
            raise AuditError("E_WAV_INVALID") from exc
        if actual != (sample_rate, channels, 2, frames) or payload_bytes != frames * channels * 2:
            raise AuditError("E_TRACK_MISMATCH")
        audio_seconds = frames / sample_rate
        if not math.isfinite(audio_seconds) or audio_seconds < minimum_duration_seconds:
            raise AuditError("E_CAPTURE_TOO_SHORT")
        metrics[name] = (started, audio_seconds)
        requested_deviations[name] = abs(audio_seconds - requested) * 1000

    start_offset_ms = abs(metrics["loopback"][0] - metrics["microphone"][0]) / 1_000_000
    duration_difference_ms = abs(metrics["loopback"][1] - metrics["microphone"][1]) * 1000
    if any(value > duration_tolerance_ms for value in requested_deviations.values()):
        raise AuditError("E_CAPTURE_DURATION_MISMATCH")
    if start_offset_ms > start_tolerance_ms or duration_difference_ms > duration_tolerance_ms:
        raise AuditError("E_SYNC_TOLERANCE")
    return {
        "status": "pass",
        "start_offset_ms": round(start_offset_ms, 3),
        "duration_difference_ms": round(duration_difference_ms, 3),
        "requested_duration_difference_ms": round(max(requested_deviations.values()), 3),
        "statement": "timing metadata consistency only, no measured acoustic drift",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="capture session manifest.json")
    parser.add_argument("--start-tolerance-ms", type=float, default=100.0,
                        help="maximum track start offset in milliseconds (default: 100)")
    parser.add_argument("--duration-tolerance-ms", type=float, default=100.0,
                        help="maximum track difference and requested-duration deviation in milliseconds (default: 100)")
    args = parser.parse_args(argv)
    try:
        result = audit_manifest(args.manifest,
                                start_tolerance_ms=args.start_tolerance_ms,
                                duration_tolerance_ms=args.duration_tolerance_ms)
    except AuditError as exc:
        print(json.dumps({"status": "fail", "error_code": exc.code}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"status": "fail", "error_code": "E_AUDIT_FAILED"}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
