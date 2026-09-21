# This is a Linux ARM64 service test image, not RG34XX firmware or an emulator.
# Multi-arch Docker Official Python manifest, observed 2026-09-21 (3.12.14).
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/helix
COPY companion/__init__.py companion/lab_service.py ./companion/
COPY genetics/__init__.py genetics/lab_simulation.py ./genetics/
COPY platform/rg34xx/smoke.py ./platform/rg34xx/smoke.py
USER 65532:65532
CMD ["python", "platform/rg34xx/smoke.py"]
