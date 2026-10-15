"""Environment preflight tests (NFR-07; T01/T04/T05/T11 inventory only)."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock

from tools import check_environment


class EnvironmentCheckTests(unittest.TestCase):
    def test_missing_prerequisites_block_readiness(self) -> None:
        def package_version(_name: str) -> str:
            raise check_environment.importlib.metadata.PackageNotFoundError

        report = check_environment.collect_environment(
            python_version=(3, 11, 9), bits=64, package_version=package_version,
            which=lambda _name: None,
        )
        self.assertEqual(report["readiness"], "blocked")
        self.assertEqual(len([b for b in report["blockers"] if b.startswith("package_missing:")]), 3)
        self.assertEqual(len([b for b in report["blockers"] if b.startswith("tool_unavailable:")]), 3)

    def test_tool_timeout_is_reported_without_raw_exception_details(self) -> None:
        def package_version(_name: str) -> str:
            return "1.2.3"

        def timeout_runner(*_args: object, **_kwargs: object) -> None:
            raise subprocess.TimeoutExpired("private path/ffmpeg.exe", 5, "private output")

        report = check_environment.collect_environment(
            python_version=(3, 11, 0), bits=64, package_version=package_version,
            which=lambda name: name, runner=timeout_runner,
        )
        self.assertEqual(report["tools"]["ffmpeg"],
                         {"available": True, "version": None, "status": "failed"})
        self.assertNotIn("private", str(report))

    def test_nonzero_tool_exit_is_blocked_and_invocation_is_safe(self) -> None:
        def package_version(_name: str) -> str:
            return "1"

        runner = Mock(return_value=subprocess.CompletedProcess([], 2, "private path", "error"))
        report = check_environment.collect_environment(
            python_version=(3, 11, 0), bits=64, package_version=package_version,
            which=lambda name: name, runner=runner,
        )
        self.assertEqual(report["readiness"], "blocked")
        self.assertEqual(report["tools"]["ffprobe"]["status"], "failed")
        self.assertNotIn("private", str(report))
        self.assertTrue(runner.call_args.kwargs["shell"] is False)
        self.assertEqual(runner.call_args.kwargs["timeout"], 5)
        self.assertIsInstance(runner.call_args.args[0], list)

    def test_version_mismatch_blocks_and_never_claims_hardware_validation(self) -> None:
        report = check_environment.collect_environment(
            python_version=(3, 14, 0), bits=64,
            package_version=lambda _name: "1.0",
            which=lambda _name: None,
        )
        self.assertEqual(report["python"]["compatible"], False)
        self.assertIn("python_requires_3_11_x64", report["blockers"])
        self.assertEqual(report["scope"], "preflight_only_gpu_and_audio_not_tested")

    def test_non_windows_operating_system_blocks_readiness(self) -> None:
        report = check_environment.collect_environment(
            python_version=(3, 11, 0), bits=64, system="Linux",
            package_version=lambda _name: "1.0",
            which=lambda _name: None,
        )
        self.assertFalse(report["os"]["compatible"])
        self.assertIn("os_requires_windows_10_11", report["blockers"])

    def test_tool_version_is_extracted_without_echoing_command_output(self) -> None:
        result = subprocess.CompletedProcess([], 0, "ffmpeg version 7.0-full_build C:\\private\\path", "")
        item = check_environment._tool_version("ffmpeg", ("-version",), lambda *_a, **_k: result)
        self.assertEqual(item, {"available": True, "version": "7.0-full_build", "status": "available"})
        self.assertNotIn("private", str(item))

if __name__ == "__main__":
    unittest.main()
