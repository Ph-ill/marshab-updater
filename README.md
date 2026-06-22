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

Top-level index:

```text
firmware/manifest.json
```

Current release:

```text
firmware/releases/0.1.1/manifest.json
```
