#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash ../../02-opa-authorization/code/scripts/check.sh
docker compose --profile tools build checks
docker compose --profile tools run --rm checks