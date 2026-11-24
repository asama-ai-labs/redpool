# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

# Redpool — build and distribution
# Docker: make docker-build [REDPOOL|REDFISH_SNAPSHOT|all]
# Pip:    make pip-build [sdist|wheel|all]

SHELL := /bin/bash
IMAGE_REGISTRY ?= ghcr.io
GITHUB_REPO ?= asama-ai-labs/redpool
GITHUB_OWNER := $(firstword $(subst /, ,$(GITHUB_REPO)))
IMAGE_PREFIX := $(IMAGE_REGISTRY)/$(GITHUB_REPO)
VERSION ?= $(shell git describe --tags --always 2>/dev/null || echo "dev")
DOCKER_BUILD_ARGS ?=

# Docker targets (share same deps layer when building all)
.PHONY: docker-build docker-build-redpool docker-build-redfish-snapshot
docker-build: docker-build-redpool docker-build-redfish-snapshot

docker-build-redpool:
	docker build $(DOCKER_BUILD_ARGS) --target redpool -t $(IMAGE_PREFIX):$(VERSION) -t $(IMAGE_PREFIX):latest -f Dockerfile .

docker-build-redfish-snapshot:
	docker build $(DOCKER_BUILD_ARGS) --target redfish-snapshot -t $(IMAGE_REGISTRY)/$(GITHUB_OWNER)/redfish-snapshot:$(VERSION) -t $(IMAGE_REGISTRY)/$(GITHUB_OWNER)/redfish-snapshot:latest -f Dockerfile .

# Pip / PyPI-style distributables (sdist and/or wheel) for workspace packages
.PHONY: pip-build pip-sdist pip-wheel pip-build-all clean-dist
DIST_DIR := dist

pip-sdist:
	uv build --all-packages --sdist

pip-wheel:
	uv build --all-packages --wheel

pip-build: pip-sdist pip-wheel

pip-build-all: pip-build
	@echo "Artifacts:"
	@find . -path '*/dist/*' \( -name '*.whl' -o -name '*.tar.gz' \) 2>/dev/null | sort

clean-dist:
	rm -rf dist redfish-snapshot/dist
	rm -rf build redfish-snapshot/build
	rm -rf *.egg-info redfish-snapshot/*.egg-info

# Run proxy/mock locally (for quick tests)
.PHONY: run-proxy run-mock
MOCKUP_SERVER := third_party/Redfish-Mockup-Server
MODEL ?= Dell/PowerEdge_R740
run-proxy:
	uv run redpool-proxy --listen-host 127.0.0.1 --listen-port 8080

# Serve one fixture model with DMTF Redfish-Mockup-Server on 127.0.0.1:8000.
run-mock:
	uv run --no-project --with-requirements $(MOCKUP_SERVER)/requirements.txt \
		python $(MOCKUP_SERVER)/redfishMockupServer.py --port 8000 --dir fixtures/$(MODEL)/original

# Help
.PHONY: help
help:
	@echo "Docker (default VERSION from git describe):"
	@echo "  make docker-build                    Build both images (redpool, redfish-snapshot)"
	@echo "  make docker-build-redpool            Build redpool image only"
	@echo "  make docker-build-redfish-snapshot   Build redfish-snapshot image only"
	@echo "  VERSION=v1.2.3 make docker-build-redpool   Tag with specific version"
	@echo ""
	@echo "Pip / distributables:"
	@echo "  make pip-build             Build sdist + wheel for root and redfish-snapshot"
	@echo "  make pip-sdist            Build source distributions only"
	@echo "  make pip-wheel            Build wheels only"
	@echo "  make clean-dist           Remove dist/ and build artifacts"
	@echo ""
	@echo "Local run:"
	@echo "  make run-proxy            Start proxy on 127.0.0.1:8080"
	@echo "  make run-mock [MODEL=Vendor/Model]  Serve a fixture model on 127.0.0.1:8000 (DMTF Mockup-Server)"
