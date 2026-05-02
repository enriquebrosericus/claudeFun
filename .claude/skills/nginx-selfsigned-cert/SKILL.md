---
name: nginx-selfsigned-cert
description: Use when working with TLS in any sub-project of this repo — generating, regenerating, or replacing a self-signed certificate served by NGINX in a container. Triggers include questions about why the cert is generated at container start, browser/curl warnings on https://localhost:..., swapping in a real cert, changing the Common Name (CN), or rebuilding after the cert expires.
---

# Self-signed TLS certs for NGINX containers

The claudeFun repo's convention is **generate the cert inside the container at startup**, not bake it into the image. Every existing project does this via the `command:` override in `docker-compose.yml`:

```yaml
command: ["/bin/sh", "-c", "mkdir -p /etc/nginx/ssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/nginx/ssl/key.pem -out /etc/nginx/ssl/cert.pem -subj '/CN=localhost' && nginx -g 'daemon off;'"]
```

The nginx config then references `/etc/nginx/ssl/cert.pem` and `/etc/nginx/ssl/key.pem`.

## Why generate at startup, not at build

- **Image stays portable and rebuildable.** No private key checked into the layer cache or pushed to a registry.
- **Cert lifetime resets every container restart.** No "expired in CI" failures.
- **Each developer/instance gets their own key.** Nothing to coordinate.
- **Trade-off:** every restart issues a new cert, so any browser TLS exception is invalidated. For a self-signed dev workflow that's fine; for a production deployment it isn't (see "Swapping in a real cert" below).

## The openssl flags, decoded

| Flag | What it does |
|------|--------------|
| `req -x509` | Output a self-signed cert directly (skip the CSR step) |
| `-nodes` | Don't encrypt the private key — nginx needs to read it without a passphrase |
| `-days 365` | Validity window. 365 is fine since the cert is regenerated on restart anyway |
| `-newkey rsa:2048` | Generate a fresh 2048-bit RSA keypair |
| `-keyout` / `-out` | Where to write the key and cert |
| `-subj '/CN=...'` | Skip the interactive prompts; set the Common Name inline |

## Choosing the CN

- **`CN=localhost`** — fine when you only access the app at `https://localhost:<port>`. Used by [bingo/](bingo/) and [music-notation-trainer/](music-notation-trainer/).
- **`CN=<your-hostname>`** — use when accessing via a real DNS name, even on the LAN. [mlb_stats_tracker/docker-compose.yml](mlb_stats_tracker/docker-compose.yml) uses `CN=whackbat.techbrose.com`.
- The CN does not affect TLS *security* in self-signed mode (the browser will warn either way), but a mismatch produces an extra warning on top of the unknown-issuer warning.

## How clients should connect

Self-signed certs aren't trusted by any CA, so clients need to skip verification or trust the cert manually:

- **curl:** `curl -k https://localhost:<port>/` (or `--insecure`)
- **wget:** `wget --no-check-certificate https://localhost:<port>/` — this is what the healthchecks in this repo use
- **browsers:** click through the warning page once per cert lifetime
- **httpie:** `http --verify=no https://localhost:<port>/`

## Common operations

### Force-regenerate the cert

Just restart the container — the `command:` runs `openssl req` again on every start.

```bash
docker compose restart <service-name>
```

### Inspect the cert that's currently serving

```bash
docker exec <container-name> openssl x509 -in /etc/nginx/ssl/cert.pem -noout -subject -dates
```

### Swap in a real cert (e.g. Let's Encrypt)

For a project that's actually deployed somewhere with a real hostname:

1. Drop the `command:` override from compose; let nginx start normally.
2. Mount real cert files in instead:
   ```yaml
   volumes:
     - /etc/letsencrypt/live/<hostname>/fullchain.pem:/etc/nginx/ssl/cert.pem:ro
     - /etc/letsencrypt/live/<hostname>/privkey.pem:/etc/nginx/ssl/key.pem:ro
   ```
3. Either run certbot on the host and reload nginx on renewal, or add a certbot sidecar service. Don't try to run certbot inside the same nginx container — keep them decoupled.

## Gotchas

- **Healthchecks must use `--no-check-certificate`** (or hit HTTP) — otherwise the container will be permanently `unhealthy`.
- **Don't set `ssl_protocols` or `ssl_ciphers` aggressively** in dev. The defaults in nginx 1.27 are fine; the cert is the weak link, not the cipher suite.
- **The `command:` override replaces the image's CMD entirely.** If you change the base image to something other than `nginx:*`, you'll need to update the final `nginx -g 'daemon off;'` part to whatever the new image expects.
- **`apk add openssl` is required** in Pattern A (single-container static apps using `nginx:1.27-alpine`). The `nginx:latest` (Debian-based) image used in Pattern B already has openssl.
