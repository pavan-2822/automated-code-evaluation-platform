#!/usr/bin/env python3
"""Measure Docker image sizes, skipping gracefully if Docker is absent.

Usage:
    python scripts/measure_image.py <image> [<image> ...]

Prints each image's size from ``docker images``. If the Docker CLI is
not available (as in this project's build VM), it prints a clear
skip message and exits 0 -- a missing Docker daemon must not look
like a measurement of zero bytes.
"""

import shutil
import subprocess
import sys


def image_size(image):
    """Return the size string for ``image``, or None if not found."""
    proc = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}} {{.Size}}", image],
        capture_output=True, text=True, timeout=30,
    )
    for line in proc.stdout.splitlines():
        if line.startswith(image + " ") or line.rsplit(" ", 1)[0] == image:
            return line.rsplit(" ", 1)[-1]
    return None


def main(argv=None):
    images = argv if argv is not None else sys.argv[1:]
    if not images:
        print("usage: measure_image.py <image> [<image> ...]", file=sys.stderr)
        return 2
    if shutil.which("docker") is None:
        print("Docker is not available in this environment; skipping measurement.")
        print("Run this script on a machine with Docker to get real sizes.")
        return 0
    for image in images:
        size = image_size(image)
        print(f"{image}: {size if size else 'not found locally'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
