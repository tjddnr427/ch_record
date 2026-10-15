"""Small two-track, streaming capture PoC (FR-02..06, T04/T05)."""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CHUNK_FRAMES = 1024


class CaptureError(RuntimeError):
    """Safe, user-facing capture failure without device paths or raw exceptions."""


@dataclass(frozen=True)
class TrackInfo:
    device_id: int
    sample_rate: int
    channels: int
    label: str
    is_loopback: bool = False


def _pyaudio() -> Any:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError as exc:
        raise CaptureError("PyAudioWPatch is unavailable; install it before capture.") from exc
    return pyaudio


class PyAudioBackend:
    """Thin library boundary; streams use blocking reads in dedicated workers."""

    def __init__(self) -> None:
        self.module = _pyaudio()
        self.audio = self.module.PyAudio()

    def devices(self) -> list[dict[str, Any]]:
        result = []
        for index in range(self.audio.get_device_count()):
            item = self.audio.get_device_info_by_index(index)
            result.append({"id": index, "name": str(item.get("name", "")),
                           "inputs": int(item.get("maxInputChannels", 0)),
                           "outputs": int(item.get("maxOutputChannels", 0)),
                           "rate": int(item.get("defaultSampleRate", 0)),
                           "loopback": bool(item.get("isLoopbackDevice", False))})
        return result

    def open(self, info: TrackInfo) -> Any:
        fmt = self.module.paInt16
        return self.audio.open(format=fmt, channels=info.channels,
                               rate=info.sample_rate, input=True,
                               input_device_index=info.device_id,
                               frames_per_buffer=CHUNK_FRAMES, start=False)

    def close(self) -> None:
        self.audio.terminate()


def _is_silent(pcm: bytes) -> bool:
    return not pcm or not any(pcm)


def capture(output: Path, loopback: TrackInfo, microphone: TrackInfo,
            duration: float, acknowledge_consent: bool,
            backend_factory: Callable[[], Any] = PyAudioBackend) -> Path:
    if not acknowledge_consent:
        raise CaptureError("Capture requires explicit consent acknowledgement.")
    if not math.isfinite(duration) or duration <= 0:
        raise CaptureError("Duration must be positive.")
    if loopback.device_id == microphone.device_id:
        raise CaptureError("Select distinct loopback and microphone devices.")
    if not loopback.is_loopback or microphone.is_loopback:
        raise CaptureError("Select a WASAPI loopback device and a microphone input device.")

    session = output / (datetime.now(timezone.utc).strftime("capture-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    try:
        session.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise CaptureError("Could not create a new session directory.") from exc

    tracks = {"loopback": loopback, "microphone": microphone}
    backend = None
    streams: dict[str, Any] = {}
    errors: list[str] = []
    stats: dict[str, dict[str, Any]] = {
        name: {"file": f"{name}.wav", "sample_rate_hz": info.sample_rate,
               "channels": info.channels, "sample_format": "pcm_s16le",
               "start_monotonic_ns": None, "frames": 0, "peak_amplitude": 0,
               "status": "pending", "error_code": None}
        for name, info in tracks.items()
    }
    start_barrier = threading.Barrier(3)
    deadline = 0.0
    capture_start_ns: dict[str, int] = {}
    lock = threading.Lock()
    workers: list[threading.Thread] = []

    def worker(name: str, info: TrackInfo) -> None:
        pcm_path = session / f"{name}.wav"
        start_ns = 0
        frames = 0
        peak = 0
        status = "completed"
        error_code = None
        try:
            with wave.open(str(pcm_path), "wb") as wav:
                wav.setnchannels(info.channels)
                wav.setsampwidth(2)
                wav.setframerate(info.sample_rate)
                start_barrier.wait()
                start_ns = capture_start_ns[name]
                while time.monotonic() < deadline:
                    # PortAudio overflow raises by default; never silently drop captured frames.
                    block = streams[name].read(CHUNK_FRAMES)
                    expected_bytes = CHUNK_FRAMES * info.channels * 2
                    if len(block) != expected_bytes:
                        error_code = "E_AUDIO_DEVICE"
                        raise CaptureError("Audio device returned an incomplete PCM block.")
                    wav.writeframesraw(block)
                    frames += len(block) // (2 * info.channels)
                    if not _is_silent(block):
                        peak = max(peak, max(abs(int.from_bytes(block[i:i + 2], "little", signed=True))
                                             for i in range(0, len(block) - 1, 2)))
            if peak == 0:
                error_code = "E_AUDIO_SILENT"
                raise CaptureError("No input signal detected on a selected track.")
        except Exception as exc:
            status = "failed"
            if error_code is None:
                error_code = "E_AUDIO_DEVICE"
            with lock:
                errors.append(error_code)
            try:
                start_barrier.abort()
            except Exception:
                pass
        with lock:
            stats[name].update({"start_monotonic_ns": start_ns or None, "frames": frames,
                                "peak_amplitude": peak, "status": status,
                                "error_code": error_code})

    try:
        backend = backend_factory()
        for name, info in tracks.items():
            streams[name] = backend.open(info)
        for name, stream in streams.items():
            stream.start_stream()
            capture_start_ns[name] = time.monotonic_ns()
        deadline = time.monotonic() + duration
        workers = [threading.Thread(target=worker, args=(n, i), daemon=True)
                   for n, i in tracks.items()]
        for thread in workers:
            thread.start()
        start_barrier.wait(timeout=10)
        for thread in workers:
            thread.join(duration + 15)
        if any(thread.is_alive() for thread in workers):
            errors.append("worker")
        if errors:
            reason = ("No input signal detected on a selected track (E_AUDIO_SILENT)."
                      if "E_AUDIO_SILENT" in errors else "Audio capture failed (E_AUDIO_DEVICE); check device availability.")
            raise CaptureError(reason)
        return session
    except CaptureError:
        for item in stats.values():
            if item["status"] == "pending":
                item.update(status="failed", error_code="E_AUDIO_DEVICE")
        raise
    except Exception as exc:
        for item in stats.values():
            if item["status"] == "pending":
                item.update(status="failed", error_code="E_AUDIO_DEVICE")
        raise CaptureError("Audio capture could not start (E_AUDIO_DEVICE); check device selection.") from exc
    finally:
        # Unblock a stuck reader before finalizing files and metadata.
        for stream in streams.values():
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        for thread in workers:
            if thread.is_alive():
                thread.join(5)
        workers_stuck = any(thread.is_alive() for thread in workers)
        if workers_stuck:
            errors.append("E_AUDIO_DEVICE")
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass
        if workers_stuck:
            raise CaptureError("Audio workers did not stop cleanly (E_AUDIO_DEVICE); manifest was not finalized.")
        state = "failed" if errors or any(x["status"] == "failed" for x in stats.values()) else "completed"
        manifest = {"format_version": 1, "duration_requested_seconds": duration,
                    "consent_acknowledged": True, "status": state,
                    "timestamp_basis": "monotonic_ns sampled immediately after coordinated stream start; first-frame estimate",
                    "tracks": stats}
        try:
            temp = session / "manifest.json.tmp"
            with temp.open("w", encoding="utf-8", newline="\n") as output_file:
                output_file.write(json.dumps(manifest, indent=2))
                output_file.flush()
                os.fsync(output_file.fileno())
            temp.replace(session / "manifest.json")
        except OSError as exc:
            raise CaptureError("Could not persist capture manifest (E_DISK_WRITE).") from exc


def _print_devices(backend: Any) -> None:
    for item in backend.devices():
        kind = "loopback" if item["loopback"] else ("input" if item["inputs"] else "output")
        print(f'{item["id"]}: {kind}, {item["inputs"]} in/{item["outputs"]} out, {item["rate"]} Hz — {item["name"]}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--loopback-id", type=int)
    parser.add_argument("--mic-id", type=int)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--output", type=Path, default=Path("recordings"))
    parser.add_argument("--acknowledge-consent", action="store_true",
                        help="Confirm participants have been informed and consented.")
    args = parser.parse_args(argv)
    try:
        backend = PyAudioBackend()
        try:
            devices = backend.devices()
            if args.list_devices:
                _print_devices(backend)
                return 0
            if args.loopback_id is None or args.mic_id is None:
                parser.error("--loopback-id and --mic-id are required for capture")
            by_id = {d["id"]: d for d in devices}
            lb, mic = by_id[args.loopback_id], by_id[args.mic_id]
            if not lb["loopback"] or mic["loopback"] or mic["inputs"] < 1:
                raise CaptureError("Select a WASAPI loopback device and a microphone input device.")
            lb_info = TrackInfo(args.loopback_id, lb["rate"], max(1, lb["inputs"]), lb["name"], True)
            mic_info = TrackInfo(args.mic_id, mic["rate"], max(1, mic["inputs"]), mic["name"])
        finally:
            backend.close()
        result = capture(args.output, lb_info, mic_info, args.duration, args.acknowledge_consent)
        print(f"Capture completed in new session: {result.name}")
        return 0
    except CaptureError as exc:
        print(str(exc))
        return 2
    except Exception:
        print("Capture failed (E_AUDIO_DEVICE). Check PyAudioWPatch installation and selected device IDs.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
