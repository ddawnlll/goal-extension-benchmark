#!/bin/bash
# Test a worker's Docker internal network cannot reach the public internet.
set -euo pipefail
NET="gb-network-probe-$$"
docker network create --internal "$NET" >/dev/null
trap 'docker network rm "$NET" >/dev/null 2>&1 || true' EXIT
if docker run --rm --user 1000 --network "$NET" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint curl goalbench/base:1 \
  --silent --show-error --max-time 4 https://example.com/ >/dev/null 2>&1; then
  echo 'unexpected outbound access' >&2
  exit 1
fi
echo 'outbound HTTPS blocked'
