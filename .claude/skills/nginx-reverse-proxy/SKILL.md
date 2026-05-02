---
name: nginx-reverse-proxy
description: Use when adding, modifying, or debugging an NGINX reverse-proxy in a sub-project of this repo. Triggers include wiring a new backend service behind nginx, sub-path routing (e.g. /grafana/, /api/), websocket upgrades, X-Forwarded-* headers, gunicorn or Flask seeing the wrong scheme/host, redirect loops, 502s after a service rename, or migrating a project from the static-SPA pattern to the reverse-proxy pattern.
---

# NGINX as a reverse proxy in this repo

This is **Pattern B** in claudeFun: nginx runs as its own container, terminates TLS, and forwards requests to one or more backend services on a shared docker network. Reference implementation: [mlb_stats_tracker/](mlb_stats_tracker/).

## Required ingredients

1. **A user-defined bridge network** (e.g. `monitoring`) that nginx and every backend join. This is what makes `proxy_pass http://web:8080` resolve — docker's embedded DNS only works on user-defined networks, not the default bridge.
2. **`depends_on:`** on the nginx service for everything it proxies to. This doesn't wait for the backend to be *ready*, just *started*; combine with healthchecks if startup ordering matters.
3. **An nginx config mounted in via volume**, not baked into the image. The reverse-proxy variant uses stock `nginx:latest`:
   ```yaml
   volumes:
     - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
   ```
4. **TLS at nginx only.** Backends listen on plain HTTP inside the docker network. Don't try to make Flask/gunicorn serve TLS — let nginx own it.

## The minimal proxy block

```nginx
server {
    listen 443 ssl;

    ssl_certificate     /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    location / {
        proxy_pass         http://<service-name>:<container-port>;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

`<service-name>` is whatever you named the service in `docker-compose.yml` — that's its DNS name on the docker network. `<container-port>` is the port the backend listens on **inside the container** (8080 for the gunicorn convention used here, 3000 for grafana, 5432 for postgres, etc.), not the host-mapped port.

## The four headers, and why each one

| Header | What it tells the backend |
|--------|---------------------------|
| `Host` | The hostname the user typed in the browser. Without it, the backend sees nginx's internal hostname and any redirects break. |
| `X-Real-IP` | The client's IP (singular). Convenient for logging. |
| `X-Forwarded-For` | The full chain of proxies — `$proxy_add_x_forwarded_for` appends to any existing value. Use this if you have multiple proxies; otherwise `X-Real-IP` is enough. |
| `X-Forwarded-Proto` | `http` or `https`. **Critical for any framework that builds redirect URLs** — Flask/Django/Rails use this to decide whether `url_for(..., _external=True)` returns an `http://` or `https://` URL. |

## Sub-path routing (e.g. /grafana/)

```nginx
location /grafana/ {
    proxy_pass         http://grafana:3000/;     # ← trailing slash matters
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}
```

**The trailing slash on `proxy_pass` is the rule.** With it, nginx strips `/grafana/` from the URI before forwarding. Without it, the backend receives the full `/grafana/foo` path and almost certainly 404s.

The backend usually also needs to know it's being served from a sub-path. For grafana, set `GF_SERVER_ROOT_URL=https://<host>/grafana/`. For Flask, set `APPLICATION_ROOT='/grafana'` and ensure `ProxyFix` is wired up.

## Websockets

If the backend uses websockets (live reload, server-sent events, socket.io):

```nginx
location / {
    proxy_pass         http://web:8080;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade           $http_upgrade;
    proxy_set_header   Connection        "upgrade";
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;             # long-lived connections
}
```

`proxy_http_version 1.1` and the `Upgrade`/`Connection` headers are what flip nginx into websocket mode.

## Adding a second backend

1. Add the service to `docker-compose.yml` on the same network.
2. Add `depends_on: [<new-service>]` to the nginx service.
3. Add a `location` block to `nginx/nginx.conf` (sub-path or hostname-based).
4. `docker compose up -d --force-recreate nginx` to reload — nginx config is mounted, but the container needs a restart to re-read it. Alternatively `docker exec <nginx-container> nginx -s reload` for a hot reload.

## Migrating a project from Pattern A to Pattern B

This comes up when a static SPA grows a backend API.

1. Move `nginx.conf` from the project root into `nginx/nginx.conf`. Drop the `root` / `try_files` directives, replace with `proxy_pass` blocks.
2. Pull the static-file-serving Dockerfile into a backend Dockerfile (or split: `Dockerfile.api` for the API, drop nginx from it).
3. Replace the single-service compose with: app service(s) + an nginx service, all on a new bridge network.
4. The old SPA assets either (a) move into the API container if it can serve them, or (b) get served by nginx with `root` for `/` plus `proxy_pass` for `/api/`.

## Common failures and what they mean

| Symptom | Likely cause |
|---------|-------------|
| 502 Bad Gateway on every request | Backend not on the same docker network, or service name typo in `proxy_pass` |
| 502 only at first request, then works | `depends_on` not set; nginx started before the backend |
| Redirect loop, or app keeps redirecting `https://` → `http://` | Missing `X-Forwarded-Proto`, or backend not configured to trust it (Flask: wire up `werkzeug.middleware.proxy_fix.ProxyFix`; gunicorn: set `--forwarded-allow-ips='*'`) |
| Sub-path links 404 (`/grafana/login` works, `/grafana/dashboards` doesn't) | Backend doesn't know its root URL — see the "Sub-path routing" section |
| Websocket connects then disconnects after ~60s | Missing `proxy_read_timeout`, or the `Upgrade`/`Connection` headers |
| Browser shows wrong hostname in URL bar after a redirect | Missing `Host` header forwarding |
| Healthcheck fails but app works in browser | Healthcheck hitting HTTPS without `--no-check-certificate`, or hitting a path the proxy doesn't route |

## What you do NOT do

- Don't terminate TLS at the backend. nginx is the TLS boundary in this repo's pattern.
- Don't put backend services on `network_mode: host` to avoid DNS issues — fix the network instead.
- Don't hard-code the hostname in `proxy_pass`. Use the docker service name so it works the same on every machine.
