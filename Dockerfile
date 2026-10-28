# Slim multi-stage image for the evaluation platform demo.
#
# Slimming techniques used here, each explained where it appears:
#  1. python:3.12-slim as the base instead of the full python image
#     (no compilers, docs, or extra system packages).
#  2. A builder stage that never installs anything: the app is
#     standard-library only, so there is no pip layer at all.
#  3. Only the application source is copied into the runtime stage --
#     no tests, examples, .git, or build artefacts (see .dockerignore).
#  4. No pip cache is created because nothing is pip-installed.
#     (If a dependency were ever added, it would be installed with
#     --no-cache-dir.)
#  5. A non-root user runs the app; the runtime image carries no
#     shell tooling beyond what the slim base provides.

# Builder stage: holds the source only. No RUN pip step exists on
# purpose -- stdlib-only means there is nothing to build.
FROM python:3.12-slim AS builder
WORKDIR /app
COPY evaluator/ ./evaluator/
COPY ci_healer/ ./ci_healer/
COPY examples/ ./examples/

# Runtime stage: copy only the built source from the builder.
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app/ ./

# Non-root user: the demo never needs root inside the container.
RUN useradd --create-home appuser
USER appuser

# Run the end-to-end demo (dispatcher + evaluator) by default.
CMD ["python3", "examples/run_demo.py"]
