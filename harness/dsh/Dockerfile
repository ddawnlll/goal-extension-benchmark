FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS dsh-build
WORKDIR /opt/dsh
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM goalbench/base:1
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap && rm -rf /var/lib/apt/lists/*
COPY --chmod=755 bwrap /usr/local/bin/bwrap
COPY --from=dsh-build /usr/local/bin/node /opt/node24/bin/node
COPY --from=dsh-build /opt/dsh /opt/dsh
COPY adapter.mjs goal.patch.yml /opt/dsh/
