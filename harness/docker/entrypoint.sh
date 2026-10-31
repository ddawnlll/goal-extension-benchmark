#!/bin/bash
# Runs as root only long enough to make the benchmark's mounted directories
# writable by the unprivileged worker, then drops privileges. Nothing else
# runs as root inside the worker container. Bind mounts on some filesystems
# (e.g. macOS virtiofs) refuse chown; the named-volume layout used by the
# benchmark does not, and the failure is not fatal when it happens.
set -euo pipefail
for d in /home/agent /tmp/pi-work; do
  if [ -d "$d" ]; then chown -R agent:agent "$d" 2>/dev/null || true; fi
done
if setpriv --reuid=1000 --regid=1000 --init-groups /bin/true 2>/dev/null; then
  export HOME="${HOME:-/home/agent}"
[ "$HOME" = /root ] && export HOME=/home/agent
exec setpriv --reuid=1000 --regid=1000 --init-groups "$@"
fi
exec su -s /bin/bash agent -c "$(printf '%q ' "$@")"
