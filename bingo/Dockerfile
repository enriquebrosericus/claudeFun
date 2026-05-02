# ── Buzzword Bingo — Dockerfile ──────────────────────────────────
# Serves the static single-page app with nginx (HTTP + HTTPS).
# Build: docker build -t buzzword-bingo .
# Run:   docker compose up

FROM nginx:1.27-alpine

RUN rm -rf /usr/share/nginx/html/*

COPY index.html /usr/share/nginx/html/
COPY style.css  /usr/share/nginx/html/
COPY app.js     /usr/share/nginx/html/
COPY phrases.js /usr/share/nginx/html/

COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN apk add --no-cache openssl

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-check-certificate -qO- https://127.0.0.1/ || exit 1
