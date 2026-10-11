#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker compose -f ../../01-foundation-learning-api/code/docker-compose.yml build api
docker compose -f ../../02-opa-authorization/code/docker-compose.yml build api
docker compose up -d --build --wait api