# Docker slimming notes

## What this image is

A slim, multi-stage `python:3.12-slim` image that runs the demo in
this repository. The application is standard-library only, so the
image contains Python, the app source, and nothing else it does not
need.

## What was removed vs a "fat" image

| Fat-image habit | What this repo does instead |
|---|---|
| `python:3.12` (full) base with compilers, docs, and extra packages | `python:3.12-slim` base in both stages |
| One stage that keeps build tools and caches in the final image | Multi-stage build: the builder stage holds source only, and the runtime stage copies just that source |
| `pip install` layers leaving a pip cache behind | No pip installs at all (stdlib only); if a dependency were ever added it would use `--no-cache-dir` |
| Copying the whole repository (tests, `.git`, caches) into the image | `.dockerignore` excludes `.git`, `tests/`, `__pycache__`, `.venv`, and healer state/audit files |
| Running as root by default | A dedicated non-root `appuser` runs the app |

## How to measure

Build, then measure with the script in this repo:

```bash
docker build -t code-evaluation-platform .
python3 scripts/measure_image.py code-evaluation-platform
```

To compare against a fat base, build a second image from
`python:3.12` with the same source and pass both tags to the script;
it prints each image's reported size.

## Honest measurement caveat

**No Docker image size was measured in the environment where this
repository was built, because Docker is not installed there.**
`scripts/measure_image.py` says so explicitly and exits cleanly
instead of inventing a number. Any size comparison must be run on a
machine with Docker, using the commands above. This repository
therefore claims slimming *techniques*, not a measured saving.
