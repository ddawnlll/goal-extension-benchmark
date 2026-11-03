#!/bin/bash
# Prepare one isolated competitor instance.
#
#   setup_instance.sh <glla|goal-x> <extension-source-dir>
#
# Creates (or recreates) the instance's Docker volume and fills it with:
#   /home/agent/work        pinned Pi-Bolt checkout (git repo, no remotes)
#   /home/agent/extensions  the pinned extension package
#   /home/agent/.pi/agent   agent config: models.json, settings.json, sessions
#   /home/agent/logs        run artifacts
# Nothing from the host's own Pi installation is mounted or copied.
set -euo pipefail

NAME="$1"; SRC="$(cd "$2" && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BASELINE="$ROOT/baseline/pi-bolt"
export DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.colima/default/docker.sock}"
IMAGE="goalbench/base:1"
VOL="gb-${NAME}-home"
SUM7="$(git -C "$BASELINE" rev-parse --short=7 HEAD)"

[ -d "$BASELINE/.git" ] || { echo "missing baseline" >&2; exit 1; }
[ -d "$SRC" ] || { echo "missing extension source $SRC" >&2; exit 1; }

docker volume rm -f "$VOL" >/dev/null 2>&1 || true
docker volume create "$VOL" >/dev/null

# Seed the volume from read-only host mounts, without preserving host ownership.
docker run --rm -v "$VOL:/home/agent" \
  -v "$BASELINE:/src/pi-bolt:ro" \
  -v "$SRC:/src/extension:ro" \
  "$IMAGE" bash -lc '
    set -euo pipefail
    mkdir -p /home/agent/work /home/agent/extensions /home/agent/.pi/agent /home/agent/logs
    cp -a --no-preserve=ownership /src/pi-bolt/. /home/agent/work/
    ext_dir=/home/agent/extensions/'"$NAME"'
    mkdir -p "$ext_dir"
    cp -a --no-preserve=ownership /src/extension/. "$ext_dir"/
    # No remotes: the worker cannot push anywhere, and no host credential helper exists.
    git -C /home/agent/work remote | while read -r r; do git -C /home/agent/work remote remove "$r"; done
    git -C /home/agent/work config user.name "benchmark-worker"
    git -C /home/agent/work config user.email "worker@benchmark.invalid"
    git -C /home/agent/work config commit.gpgsign false
    git -C /home/agent/work config core.hooksPath /dev/null
    git -C /home/agent/work checkout -- . 2>/dev/null || true
  ' >/dev/null

# Agent configuration. Identical for both competitors except for the extension.
docker run --rm -v "$VOL:/home/agent" -v "$HERE/config:/src/config:ro" -e INSTANCE_NAME="$NAME" "$IMAGE" bash -lc '
  set -euo pipefail
  sed "s/__RELAY_HOST__/gb-relay-$INSTANCE_NAME/g" /src/config/models.tmpl.json > /home/agent/.pi/agent/models.json
  cat > /home/agent/.pi/agent/settings.json <<JSON
{
  "sessionDir": "/home/agent/.pi/agent/sessions",
  "quietStartup": true,
  "defaultProjectTrust": "never",
  "extensions": [],
  "skills": [],
  "promptTemplates": [],
  "themes": []
}
JSON
  chmod 600 /home/agent/.pi/agent/models.json
  rm -rf /home/agent/.pi/agent/skills /home/agent/.pi/agent/prompts /home/agent/.pi/agent/extensions
' >/dev/null

# DSH uses its own pinned runtime image and has no Pi extension to install.
if [ "$NAME" = dsh ]; then
  echo "instance $NAME ready: volume $VOL, baseline ${SUM7}"
  exit 0
fi

# Install the extension package (local folder; no registry access needed).
docker run --rm -v "$VOL:/home/agent" \
  -v "$HERE/runtime/pi-bolt-linux-arm64:/opt/pi-bolt:ro" \
  -e HOME=/home/agent -e PI_CODING_AGENT_DIR=/home/agent/.pi/agent \
  "$IMAGE" bash -lc "cd /home/agent/work && pi install /home/agent/extensions/$NAME" 2>&1 | tail -5

echo "instance $NAME ready: volume $VOL, baseline ${SUM7}"
