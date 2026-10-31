#!/bin/bash
# Fetch the pinned inputs this benchmark depends on.
#
#   LOCAL_LLM_KEY=... bash harness/fetch_inputs.sh
#
# Clones Pi-Bolt at the pinned commit, the two extensions at their pinned
# commits, downloads and verifies the Pi-Bolt release binary, checks the shared
# task hash, and stores the model endpoint credential where the relay expects it
# (git-ignored). Nothing here is vendored into the repository.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PB_REPO="https://github.com/opensec-git/Pi-Bolt"
PB_BRANCH="pi-bolt"
PB_COMMIT="fd4530c9611f0cffc18aa226c985fcc2603d2577"
PB_RELEASE="bolt-v1.0.8"
PB_SHA256="f530486723c7ab9004aca51f6f9494b95861fba7287c05ae8804647d63077de1"

GLLA_REPO="https://github.com/DraconDev/pi-goal-list-loop-audit"
GLLA_COMMIT="b1c36dc7389077f8b3409183277d12588cc60dae"

GOALX_REPO="https://github.com/tmonk/pi-goal-x"
GOALX_COMMIT="b0fc15ebb658a1e9ea60ae65496717a780080f37"

TASK_SHA256="d911abf544abd173aa191ef2c8cf761034fed795cd32e12f7456dd7452a252e9"

case "$(uname -m)" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64)  ARCH="x64" ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

say() { printf '\n== %s\n' "$*"; }

say "Pi-Bolt source at $PB_COMMIT"
if [ ! -d baseline/pi-bolt/.git ]; then
  git clone --branch "$PB_BRANCH" "$PB_REPO" baseline/pi-bolt
fi
git -C baseline/pi-bolt fetch --all --tags --quiet
git -C baseline/pi-bolt checkout --quiet "$PB_COMMIT"
test "$(git -C baseline/pi-bolt rev-parse HEAD)" = "$PB_COMMIT"
echo "ok: $(git -C baseline/pi-bolt rev-parse --short HEAD)"

say "Extensions"
if [ ! -d competitors/_glla-src/.git ]; then
  git clone "$GLLA_REPO" competitors/_glla-src
else
  git -C competitors/_glla-src fetch --all --tags --quiet
fi
git -C competitors/_glla-src checkout --quiet "$GLLA_COMMIT"
if [ ! -d competitors/_goalx-src/.git ]; then
  git clone "$GOALX_REPO" competitors/_goalx-src
else
  git -C competitors/_goalx-src fetch --all --tags --quiet
fi
git -C competitors/_goalx-src checkout --quiet "$GOALX_COMMIT"
echo "ok: glla $(git -C competitors/_glla-src rev-parse --short HEAD), goal-x $(git -C competitors/_goalx-src rev-parse --short HEAD)"

say "Pi-Bolt runtime $PB_RELEASE ($ARCH)"
RUNTIME_DIR="harness/runtime/pi-bolt-linux-$ARCH"
if [ ! -x "$RUNTIME_DIR/pi" ]; then
  mkdir -p harness/runtime
  TARBALL="harness/runtime/pi-bolt-linux-$ARCH.tar.xz"
  URL="https://github.com/opensec-git/Pi-Bolt/releases/download/$PB_RELEASE/pi-bolt-linux-$ARCH.tar.xz"
  curl -fL --retry 3 -o "$TARBALL" "$URL"
  GOT="$(shasum -a 256 "$TARBALL" | awk '{print $1}')"
  if [ "$ARCH" = "arm64" ] && [ "$GOT" != "$PB_SHA256" ]; then
    echo "checksum mismatch: $GOT" >&2
    echo "(the pinned checksum is for linux-arm64; x64 has its own checksum in the release notes)" >&2
    exit 1
  fi
  tar -xJf "$TARBALL" -C harness/runtime
  rm -f "$TARBALL"
fi
ln -sfn "pi-bolt-linux-$ARCH" harness/runtime/current
"$RUNTIME_DIR/pi" --version || true

say "Shared task"
GOT_TASK="$(shasum -a 256 results/shared-task.md | awk '{print $1}')"
if [ "$GOT_TASK" != "$TASK_SHA256" ]; then
  echo "task hash mismatch: $GOT_TASK" >&2
  exit 1
fi
echo "ok: $GOT_TASK"

say "Model endpoint credential"
if [ -z "${LOCAL_LLM_KEY:-}" ]; then
  echo "LOCAL_LLM_KEY is not set." >&2
  echo "Export the key your OpenAI-compatible endpoint expects, then re-run:" >&2
  echo "  export LOCAL_LLM_KEY='...'" >&2
  exit 1
fi
mkdir -p harness/.secrets
printf '%s' "$LOCAL_LLM_KEY" > harness/.secrets/local_api_key
chmod 600 harness/.secrets/local_api_key
echo "ok: harness/.secrets/local_api_key (git-ignored)"

say "Done"
echo "Next: export DOCKER_HOST=unix://\$HOME/.colima/default/docker.sock"
echo "      python3 harness/preflight.py"
