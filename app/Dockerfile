# The hister CLI fetches and stores pages for link rot (Hister's /api/add alone
# doesn't fetch). Keep this pinned to the Hister server's version. Hister is AGPL-3.0
# (https://github.com/asciimoo/hister, tag below); Konbini runs it as a separate program.
ARG HISTER_VERSION=v0.20.0
FROM ghcr.io/asciimoo/hister:${HISTER_VERSION}@sha256:5ffd0a702482c71010a67db8e6b567344189844ed42072d1b4cdae511b2aa7bb AS hister

FROM public.ecr.aws/docker/library/python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c

RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client sqlite3 openssl \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir markdown==3.11 pyyaml==6.0.3

# ssh refuses to run for a uid without a passwd entry (git pull/push).
RUN useradd --uid 1000 --home-dir /data --no-create-home --shell /usr/sbin/nologin kanban

COPY --from=hister /hister/hister /usr/local/bin/hister

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
