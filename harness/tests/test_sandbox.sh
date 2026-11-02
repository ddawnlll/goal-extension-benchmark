#!/bin/bash
# Check the DSH bwrap workspace policy under the actual worker seccomp profile.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VOL="gb-sandbox-probe-$$"
docker volume create "$VOL" >/dev/null
trap 'docker volume rm -f "$VOL" >/dev/null 2>&1 || true' EXIT
docker run --rm -v "$VOL:/home/agent" --entrypoint /bin/sh goalbench/dsh:1 -c \
  'mkdir -p /home/agent/work; chown -R 1000:1000 /home/agent'
docker run --rm --user 1000 --read-only --tmpfs /tmp:rw,exec \
  --security-opt no-new-privileges --security-opt "seccomp=$ROOT/harness/docker/worker-seccomp.json" \
  --cap-drop ALL -v "$VOL:/home/agent" --entrypoint /usr/local/bin/bwrap goalbench/dsh:1 \
  --ro-bind / / --dev /dev --unshare-pid --proc /proc --die-with-parent \
  --tmpfs /tmp --bind /home/agent/work /home/agent/work -- sh -c \
  'touch /home/agent/work/allowed; if touch /home/agent/denied 2>/dev/null; then exit 1; fi; echo workspace_write_allowed_and_home_denied'
