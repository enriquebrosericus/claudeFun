# ── Music Notation Trainer — Dockerfile ──────────────────────────────────────
# Serves the static single-page app with nginx.
# Build: docker build -t notation-trainer .
# Run:   docker run -p 8080:80 notation-trainer

FROM nginx:1.27-alpine

# Remove default nginx content
RUN rm -rf /usr/share/nginx/html/*

# Copy app source
COPY index.html  /usr/share/nginx/html/
COPY style.css   /usr/share/nginx/html/
COPY theory.js   /usr/share/nginx/html/
COPY staff.js    /usr/share/nginx/html/
COPY keyboard.js /usr/share/nginx/html/
COPY app.js      /usr/share/nginx/html/
COPY Bravura.woff2 /usr/share/nginx/html/

# Custom nginx config: single-page app with proper MIME types and caching
COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN apk add --no-cache openssl

EXPOSE 443

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-check-certificate -qO- https://localhost/ || exit 1
