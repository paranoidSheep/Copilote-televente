# syntax=docker/dockerfile:1
# Image du copilote télévente : compilation du frontend, puis image Python légère.
#
# Derrière un proxy d'entreprise qui inspecte le TLS, fournir son certificat d'autorité :
#   docker build --secret id=ca_entreprise,src=/chemin/ca.crt .
# Sans ce secret (cas normal), la construction est standard.

# --- 1. Frontend TypeScript -------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json ./
RUN --mount=type=secret,id=ca_entreprise,required=false \
    if [ -f /run/secrets/ca_entreprise ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_entreprise; fi; \
    npm install --no-audit --no-fund
COPY frontend/tsconfig.json ./
COPY frontend/src ./src
RUN npx tsc -p tsconfig.json --outDir /frontend/dist

# --- 2. Application Python ----------------------------------------------------------
FROM python:3.12-slim AS application
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DOSSIER_DONNEES=/data \
    HOTE=0.0.0.0 \
    PORT=8000 \
    FORMAT_JOURNAUX=json

RUN groupadd --system --gid 1000 copilote \
 && useradd --system --uid 1000 --gid copilote --home-dir /app --shell /usr/sbin/nologin copilote \
 && mkdir -p /data && chown copilote:copilote /data

WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=ca_entreprise,required=false \
    if [ -f /run/secrets/ca_entreprise ]; then export PIP_CERT=/run/secrets/ca_entreprise; fi; \
    pip install -r requirements.txt

COPY copilote ./copilote
COPY scripts ./scripts
# JavaScript compilé à l'étape 1 (remplace celui du dépôt, garanti à jour)
COPY --from=frontend /frontend/dist ./copilote/api/static/js

USER copilote
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante', timeout=4)"
CMD ["python", "-m", "copilote"]
