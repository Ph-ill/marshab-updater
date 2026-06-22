# MarsHab Field Updater

Static WebSerial updater for Raspberry Pi Pico W / MicroPython payloads.

Public UI target: `https://marshab.coolphill.com`

The interface is MarsHab-branded, but the firmware payload format is generic:
release manifests describe arbitrary MicroPython files, preserved paths, delete paths,
file sizes, hashes, and UTF-8/binary transfer mode.

## Portainer GitOps

Use this repository as a Portainer stack source.

Compose file: `docker-compose.yml`

Published host port:

```text
8141 -> container 80
```

Nginx Proxy Manager can forward:

```text
marshab.coolphill.com -> http://<homeserver-ip>:8141
```

or, if NPM shares the Docker network with this container:

```text
marshab.coolphill.com -> http://marshab-updater:80
```

Enable Let's Encrypt SSL and Force SSL in Nginx Proxy Manager. WebSerial requires HTTPS
except on localhost.

## Local test

```bash
python3 -m http.server 8140
# open http://localhost:8140 in Chrome/Edge/Brave
```

## Firmware releases

The updater UI pulls available firmware versions directly from GitHub Releases for this repository:

```text
https://api.github.com/repos/Ph-ill/marshab-updater/releases
```

Each GitHub Release should have one asset named:

```text
firmware-release.json
```

That asset is a generic firmware manifest with file bytes embedded as base64. The updater still keeps `firmware/manifest.json` as a bundled fallback, but normal operation uses GitHub Releases.

To pack the current bundled release into a GitHub Release asset:

```bash
python3 tools/make_release_asset.py \
  firmware/releases/0.1.1/manifest.json \
  firmware/releases/0.1.1/files \
  dist/firmware-release.json

gh release create v0.1.1 dist/firmware-release.json \
  --title "v0.1.1" \
  --notes "Firmware payload attached as firmware-release.json."
```
