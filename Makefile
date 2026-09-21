.DEFAULT_GOAL := help
.PHONY: help setup demo test smoke container-smoke

UV ?= uv
HELIX_SMOKE_IMAGE ?= helix-lab-public-smoke:local

help:
	@printf '%s\n' 'make setup            Prepare Python 3.12 from the dependency lock' 'make demo             Compare the two synthetic lab conditions' 'make test             Run the public host unit suite' 'make smoke            Test the real loopback service and durable replay' 'make container-smoke  Test the service in restricted Linux ARM64 Docker'

setup:
	$(UV) sync --locked --python 3.12

demo:
	$(UV) run --offline --frozen python -m companion.demo

test:
	$(UV) run --offline --frozen python -m unittest discover -s tests -v

smoke:
	$(UV) run --offline --frozen python platform/rg34xx/smoke.py

container-smoke:
	docker build --platform linux/arm64 -f platform/rg34xx/Dockerfile -t "$(HELIX_SMOKE_IMAGE)" .
	docker run --rm --platform linux/arm64 --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m --cpus 1 "$(HELIX_SMOKE_IMAGE)"
