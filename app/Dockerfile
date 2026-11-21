# The nogon CLI fetches and stores pages for link rot (Nogon's /api/add alone
# doesn't fetch). Keep this pinned to the Nogon server's version. Nogon (Hister until v0.21) is AGPL-3.0
# (https://github.com/asciimoo/nogon, tag below); Konbini runs it as a separate program.
# Since 0.30.0 the CLI is installed as `nogon` and takes the owner's token as NOGON__APP__ACCESS_TOKEN (v0.22 and later).
ARG NOGON_VERSION=v0.22.0
FROM ghcr.io/asciimoo/nogon:${NOGON_VERSION}@sha256:d1b427c7f876e64e6212e000df60d33c2e418b60372582b56cfee719eafd4107 AS nogon

FROM public.ecr.aws/docker/library/python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

# nats-py and nkeys: the workshop bus's presence for the Now page (bus.py, used only with KANBAN_BUS_URL), with nkeys'
# own dependencies pinned (PyNaCl bundles libsodium; about 7 MB in all)
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client sqlite3 openssl \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir markdown==3.11 pyyaml==6.0.3 \
    nats-py==2.17.0 nkeys==0.2.1 pynacl==1.6.2 cffi==2.1.1 pycparser==3.12

# ssh refuses to run for a uid without a passwd entry (git pull/push).
RUN useradd --uid 1000 --home-dir /data --no-create-home --shell /usr/sbin/nologin kanban

COPY --from=nogon /usr/local/bin/nogon /usr/local/bin/nogon

WORKDIR /app
COPY . /app
# The vendored vault core (app/vaultkit/, from machiya-kobo/machiya) must match its manifest: edits go upstream.
RUN python3 -m vaultkit.verify

# Not root, whatever runs the image (the reference compose says user 1000:1000 as well).
USER 1000:1000

EXPOSE 8081
# GET /healthz is open (no identity check, any KANBAN_AUTH) and answers "ok"; the first start indexes the vault.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD ["python3", "-c", "import os, urllib.request as u; b = os.environ.get('KANBAN_BIND', '').strip(); h = '127.0.0.1' if b in ('', '0.0.0.0') else b; u.urlopen('http://%s:%s/healthz' % (h, os.environ.get('KANBAN_TAILNET_PORT', '8081')), timeout=4).read()"]
CMD ["python3", "-u", "/app/app.py"]
