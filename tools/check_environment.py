"""Report local Phase 0 prerequisites without probing GPU or audio devices.

Requirements: Python 3.11 x64 (PRD, NFR-07); this preflight supports Phase 0
environment inventory and does not establish GPU/audio operation (T01/T04/T05/T11).
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import shutil
import struct
import subprocess
import sys
from typing import Any, Callable, Sequence

PACKAGES = ("faster-whisper", "ctranslate2", "PyAudioWPatch")
TOOLS: dict[str, tuple[str, ...]] = {
    "ffmpeg": ("-version",),
    "ffprobe": ("-version",),
    "nvidia-smi": ("--version",),
}
_VERSION_PATTERNS = (
    re.compile(r"\bversion\s+([A-Za-z0-9.+_-]+)", re.IGNORECASE),
    re.compile(r"\bNVIDIA-SMI\s+([A-Za-z0-9.+_-]+)", re.IGNORECASE),
)


def _tool_version(executable: str, args: Sequence[str], runner: Callable[..., Any]) -> dict[str, Any]:
    try:
        result = runner(
            [executable, *args], shell=False, capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": True, "version": None, "status": "failed"}
    if result.returncode != 0:
        return {"available": True, "version": None, "status": "failed"}
    output = f"{result.stdout}\n{result.stderr}"
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(output)
        if match:
            return {"available": True, "version": match.group(1), "status": "available"}
    return {"available": True, "version": None, "status": "version_unknown"}


def collect_environment(
    *,
    python_version: tuple[int, int, int] | None = None,
    bits: int | None = None,
    system: str | None = None,
    package_version: Callable[[str], str] = importlib.metadata.version,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Collect a privacy-safe prerequisite inventory and readiness decision."""
    version = python_version or sys.version_info[:3]
    bitness = bits if bits is not None else struct.calcsize("P") * 8
    operating_system = system or platform.system()
    os_ok = operating_system == "Windows"
    python_ok = version[:2] == (3, 11) and bitness == 64

    packages: dict[str, dict[str, Any]] = {}
    for name in PACKAGES:
        try:
            installed = package_version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = {"available": False, "version": None}
        except Exception:
            packages[name] = {"available": False, "version": None, "status": "check_failed"}
        else:
            packages[name] = {"available": True, "version": installed}

    tools: dict[str, dict[str, Any]] = {}
    for name, args in TOOLS.items():
        executable = which(name)
        if executable is None:
            tools[name] = {"available": False, "version": None, "status": "missing"}
        else:
            tools[name] = _tool_version(executable, args, runner)

    blockers: list[str] = []
    if not os_ok:
        blockers.append("os_requires_windows_10_11")
    if not python_ok:
        blockers.append("python_requires_3_11_x64")
    blockers.extend(f"package_missing:{name}" for name, item in packages.items()
                    if not item["available"])
    blockers.extend(f"tool_unavailable:{name}" for name, item in tools.items()
                    if not item["available"] or item["status"] != "available")

    return {
        "scope": "preflight_only_gpu_and_audio_not_tested",
        "os": {
            "system": operating_system,
            "required": "Windows 10/11 x64",
            "compatible": os_ok,
        },
        "python": {
            "version": ".".join(str(part) for part in version),
            "implementation": platform.python_implementation(),
            "bits": bitness,
            "required": "3.11 x64",
            "compatible": python_ok,
        },
        "packages": packages,
        "tools": tools,
        "readiness": "ready" if not blockers else "blocked",
        "blockers": blockers,
    }


def main() -> int:
    report = collect_environment()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["readiness"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
