#!/usr/bin/env python3
"""Report local prerequisites without changing the environment."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    disk = shutil.disk_usage(Path.cwd())
    docker_path = shutil.which("docker")
    docker_available = docker_path is not None
    docker_responding = False
    docker_error: str | None = None
    if docker_available:
        try:
            result = subprocess.run(
                [docker_path, "info", "--format", "{{json .ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            docker_responding = result.returncode == 0
            if not docker_responding:
                docker_error = (result.stderr or result.stdout).strip() or None
        except (OSError, subprocess.TimeoutExpired):
            docker_responding = False
            docker_error = "docker info failed or timed out"
    memory_bytes = _memory_bytes()
    architecture = platform.machine().lower()
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "architecture": architecture,
        "docker_installed": docker_available,
        "docker_daemon_responding": docker_responding,
        "docker_error": docker_error,
        "disk_free_gib": round(disk.free / (1024**3), 2),
        "memory_gib": (
            round(memory_bytes / (1024**3), 2) if memory_bytes is not None else None
        ),
    }
    report["swebench_local_prerequisites"] = {
        "x86_64": architecture in {"x86_64", "amd64"},
        "docker": docker_responding,
        "disk_at_least_120_gib": disk.free >= 120 * 1024**3,
        "memory_at_least_16_gib": (
            memory_bytes is not None and memory_bytes >= 16 * 1024**3
        ),
    }
    report["swebench_local_ready"] = all(
        report["swebench_local_prerequisites"].values()
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return None
    if not isinstance(pages, int) or not isinstance(page_size, int):
        return None
    return pages * page_size


if __name__ == "__main__":
    raise SystemExit(main())
