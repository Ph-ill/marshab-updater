# HTTPS on the ship (voyage.coolphill.com): feasibility and decision

Branch `https-probe` (from `ota-hwfix` 3ad5e7c). The test kit is in `tools/https-probe/`.
Measurements were taken on the box on 2026-10-26/27 (CDT). No hardware was touched.

## 0. Verdict

**It works on the firmware we already have, but I don't recommend it for this game.**

- **Can the ship do it?** Yes. The lv-core 0.2.0 firmware (MicroPython v1.29.0, mbedTLS
  3.6.6) already has a TLS 1.2 server with ECDSA P-256. No reflash is needed.
- **The cost.** About 10–14 KB of RAM stays reserved. Each connection that is setting up
  costs about 26 KB more, so the server can afford about 2 at a time. Each new connection
  also takes roughly 0.4–0.7 s of the RP2040's time. During that, the asyncio loop is
  stalled: DNS, BLE sync and the software-PWM breathing LED all pause. lvweb would also
  need rewriting to keep connections open and queue them.
- **The real problem is durability.** A ship's certificate dies 30–90 days after the last
  phone that relayed an update while online. That window shrinks to about 21–64 days after
  Feb 2027 and 15–45 days after Feb 2028. Ships sit offline with teammates for months, so
  certificates will lapse as a matter of course. The people hit hardest are the ones who
  installed the icon, the very users HTTPS was meant to help. For them the icon opens
  https, and the browser refuses the expired certificate before the ship can redirect
  anything.
- **What HTTPS buys** comes down to two things: an offline "connect to your ship" page
  when the icon is opened away from the ship, and a real install with an install prompt on
  Android. Saved data already works over http, including in the iOS home-screen app.
- **Recommendation: stay on http://192.168.4.1.**
  - **iPhone:** keep the http home-screen app and finish the launch-image "connect to your
    ship" screen.
  - **Android:** add a "Full screen" button. The Fullscreen API works over http in Chrome.
    Add it alongside "Add to Home screen".
  - **If Phill still wants HTTPS later,** section 4 is the design that keeps it from
    breaking. Section 6 is the one-board test to run before any of it.

## 1. What HTTPS adds over http (only what's new)

| Feature | Over http today | With HTTPS |
| --- | --- | --- |
| Saved data (sign-in, progress) | Works, in Safari and in the iOS home-screen app | Same. But https://voyage.coolphill.com is a **different origin** from http://192.168.4.1, so players start fresh, and anything that falls back to http sees the other origin's data. |
| Offline page when the icon is opened away from the ship | iOS shows its own error, or at best the launch image (in progress) | **Service worker** serves a cached "connect to your ship" page and app shell (iOS 16.4+ and Android). This is the main gain. |
| Android install | "Add to Home screen" gives a shortcut that opens a Chrome tab with the URL bar | **WebAPK**: standalone, in the launcher, and the `beforeinstallprompt` one-tap install button for the funnel. Needs https and a service worker ([MDN](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable), [web.dev](https://web.dev/articles/install-criteria)). |
| Full screen on Android | `requestFullscreen()` on a tap works over http (one tap per launch) | Standalone without the tap |
| Storage durability | iOS home-screen apps are exempt from Safari's 7-day eviction. Android rarely evicts small sites. | `navigator.storage.persist()` (secure context). Marginal. |
| Other secure-context APIs | none | Screen Wake Lock (keeps the screen on while watching), Web Share, clipboard write, WebCrypto. Nice to have, not needed. |
| Browser warnings | None on a private IP. Chrome 154's Ask-before-HTTP exempts local IPs ([Chromium guide](https://chromium.googlesource.com/chromium/src/+/main/docs/security/ask-before-http/ask-before-http-adoption-guide.md)). | Padlock. **But http://voyage.coolphill.com, a public name, would get Chrome's Ask-before-HTTP warning, so any http fallback must use 192.168.4.1, never the domain.** |

## 2. Answers with evidence

### 2.1 Does our firmware's `ssl` do server-side TLS?

Yes. It's in the source of the pinned tree (`/workspace/fwbuild/mp`, v1.29.0 0fd6c573) and in
our built lv-core 0.2.0 ELF:
- `extmod/modtls_mbedtls.c` has `PROTOCOL_TLS_SERVER`, `load_cert_chain(cert, key)`, which
  takes bytes or paths through the frozen `ssl.py`, and `wrap_socket(server_side=True,
  do_handshake_on_connect=False)`. `asyncio.start_server(..., ssl=ctx)` wraps every
  accepted socket this way (`extmod/asyncio/stream.py`).
- The rp2 config is `ports/rp2/mbedtls/mbedtls_config_port.h` plus
  `extmod/mbedtls/mbedtls_config_common.h`. It has `MBEDTLS_SSL_SRV_C`,
  `KEY_EXCHANGE_ECDHE_ECDSA`, `ECDSA_C`, `ECP_DP_SECP256R1`, `ECP_NIST_OPTIM`, `GCM_C` and
  `SSL_SERVER_NAME_INDICATION`.
  - Buffers: `IN_CONTENT_LEN` 16384 and `OUT_CONTENT_LEN` 4096.
  - mbedTLS allocates on the MicroPython GC heap (`m_tracked_calloc`, bare-metal), so the
    cost shows up in `gc.mem_free()`.
- **TLS 1.2 only.** `MBEDTLS_SSL_PROTO_TLS1_3` is off. Phones are fine with TLS 1.2
  ECDHE-ECDSA-AES-GCM.
- **No session resumption.** Neither `MBEDTLS_SSL_SESSION_TICKETS` nor `MBEDTLS_SSL_CACHE_C`
  is on, and modtls has no server ticket or cache hook. **Every TCP connection is a full
  ECC handshake.**
- In `build-lv-0.2.0-RPI_PICO_W/firmware.elf`, `mbedtls_ssl_handshake_server_step` and
  `mbedtls_ssl_conf_own_cert` are present and `ssl.py` is frozen. `tools/build_firmware.sh`
  doesn't change any TLS option.
- **Firmware changes that would help.** All of them mean a USB reflash of every ship, so
  each Pico comes out of its case. That's why the design below doesn't depend on them.
  1. `MBEDTLS_SSL_IN_CONTENT_LEN 4096` saves about 12 KB per connection (measured, 2.2).
     The risk is a client record over 4 KB. Our requests are small, but it needs a phone
     test.
  2. `MBEDTLS_SSL_SESSION_TICKETS` plus `MBEDTLS_SSL_TICKET_C` (or `MBEDTLS_SSL_CACHE_C`),
     plus a small C patch in `modtls_mbedtls.c` to call `mbedtls_ssl_ticket_setup` /
     `mbedtls_ssl_conf_session_tickets_cb` on server contexts. Resumed connections would
     skip the ECC work entirely.
  3. Drop RSA, CBC and the unused curves to save flash. This doesn't help RAM.
- **Clock.** A TLS server doesn't check its own certificate's dates. The server context
  uses `MBEDTLS_SSL_VERIFY_NONE`, and dates are only checked when verifying a peer.
  Measured: the probe served a certificate that expired in 2020 without complaint. The
  client rejected it with `certificate has expired`, which is exactly what a phone would
  do (`tls_hammer.py --ca testcert/expired.pem`).

### 2.2 RAM (measured)

I measured on 32-bit unix MicroPython v1.29.0, built with the rp2 mbedTLS options and
mbedTLS allocating on the GC heap (`tools/https-probe/unix/`), with an allocation counter
for the true peak. Pointer sizes and mbedTLS structures match the Pico, so these numbers
should carry over to within a few hundred bytes. The hardware kit (section 6) confirms
them.

| | Bytes | Notes |
| --- | --- | --- |
| SSLContext with the cert loaded, persistent | 5.3 KB (leaf only), 7.8 KB (leaf+YE2), 10.4 KB (3 certs), **14.0 KB (the real 4-cert chain, 4.8 KB PEM)** | Real LE cert. The chain is leaf, YE2, Root YE cross-signed by X2, then X2 cross-signed by X1. |
| Per connection after `wrap_socket` | 22.9 KB | 16 KB receive buffer, 4 KB send buffer, SSL context. It needs one **contiguous** ~16.4 KB block, so fragmentation is a real risk. |
| Per connection, held after the handshake | 23.3 KB | until close |
| Per connection, mbedTLS peak during the handshake | **25.8 KB** (25,798 B, same for every chain) | ECC temporaries on top of the buffers |
| Same with the 4 KB receive buffer (firmware change) | 10.6 KB after wrap, **13.5 KB** peak | |
| asyncio server, 4 / 6 / 8 parallel, 193 KB heap | 136 KB / 169 KB used; 8 runs out of memory (ENOMEM) | Upper bound: includes Python stream objects and garbage between collections. A 160 KB heap fit 5. |
| Same with 4 KB receive buffer | 4: 87 KB, 8: 170 KB | |

**Against the budget.** About 160 KB is free, and the game's real peak is about 30 KB. The
bench doc caps the game at 80 KB with phones playing and a BLE sync running.
- Stock firmware: 14 KB + 2 × 26 KB ≈ **66 KB for two TLS connections**. Four would be
  118–136 KB, which only fits with the game idle.
- **Cap TLS at 2 concurrent on stock firmware, or 4 with the 4 KB-buffer firmware.**
- Today's http server holds about 1 KB per connection.

### 2.3 Handshake time on the RP2040

`tools/https-probe/ecbench/` counts Cortex-M0+ instructions for the server's P-256 work with
the same mbedTLS 3.6.6 sources and options, under qemu-arm.

| Step | Instructions |
| --- | --- |
| ECDHE keygen | 9.0 M |
| ECDSA sign (ServerKeyExchange) | 10.6 M |
| ECDH shared secret | 25.7 M |
| **Total** | **45.2 M** |

- At 125 MHz and 1.0–2.0 cycles per instruction (XIP flash cache misses), that's
  **0.36–0.72 s of CPU per new connection**, before Wi-Fi round trips.
- It runs as two blocking steps of about 0.16–0.31 s (keygen and sign) and 0.2–0.4 s
  (ECDH).
- Cross-checks:
  - wolfSSL's Pico W benchmark gives about 50–100 ms per P-256 operation at 125 MHz with a
    faster library ([wolfSSL](https://www.wolfssl.com/benchmarking-wolfcrypt-on-cortex-m0/)).
  - MQTT-on-Pico-W reports describe the handshake as "a second or more"
    ([ConnectMQ](https://connectmq.com/blog/pico-w-mqtt-tls/)).
  - The same handshake takes 46–51 ms on the box's x86.
- With no resumption, a phone opening 6 parallel connections waits roughly 2.5–5 s for the
  last one. While each step runs, nothing else on the ship does.

### 2.4 How many connections

- Memory allows 2 on stock firmware.
- CPU makes more pointless anyway, because handshakes run one at a time on one core.
- What matters is that a phone needs **one or two** connections, not six (section 4).

## 3. The durability problem (why I lean no-go)

### Certificate lifetimes

The current cert expires **2027-01-25 03:56 UTC (Jan 24, 9:56 PM CST)**.

| Issued | Max validity | Source |
| --- | --- | --- |
| Let's Encrypt classic profile | 90 days, then **64 days from 2027-02-10**, then **45 days from 2028-02-16** | [LE 64-day](https://letsencrypt.org/2026/10/07/64-day-certs), [LE 45-day](https://letsencrypt.org/2025/12/02/from-90-to-45) |
| Any public CA (CA/B Forum SC-081v3) | 200 days from 2026-03-15, 100 days from 2027-03-15, 47 days from 2029-03-15 | [CA/B BR 1.2.2](https://cabforum.org/working-groups/server/baseline-requirements/requirements/) |

A paid 199-day cert bought before 2027-03-15 is the longest you can get. It would last
until about Sep 2027. After that it's 99 days at most, and 46 days from 2029. There is no
long-lived option.

### How long a ship stays valid after its last online visit

A ship can only get a new cert when a phone with mobile data relays an update. A cert-only
update can go silently with no user tap, because it's data rather than code. The ship then
stays valid for whatever is left on the newest cert the box has:

| Period | certbot as now (renews 30 days before expiry) | Box re-issues weekly (LE allows 5 identical per week) |
| --- | --- | --- |
| now, 90-day certs | 30–90 days (average 60) | at least 83 days |
| from Feb 2027, 64-day | about 21–64 days | at least 57 days |
| from Feb 2028, 45-day | about 15–45 days | at least 38 days |

**So for every ship, an online teammate has to open the game at least every 1–3 months,
and that window keeps shrinking.** Ships "sit for months", so lapses are expected, not
rare.

### What a lapse looks like

- **In the browser:** a full-screen interstitial. Safari shows "This Connection Is Not
  Private". Chrome shows `NET::ERR_CERT_DATE_INVALID`.
  - Without HSTS you can click through, but that's a scary step for teammates.
  - Chrome's own guide: certificate errors on an explicit https URL never fall back to
    http.
- **From an installed icon:** the icon's URL is https. TLS fails before the ship sees a
  request, so the ship **cannot redirect anyone**. Only a service worker that serves the
  app shell from cache first can catch it. It would detect the failure and send the player
  to `http://192.168.4.1/`. On iOS that opens in an in-app Safari sheet with a URL bar,
  because a different origin is out of scope, and it uses separate storage. On Android it
  opens a Chrome tab. That http page can then relay the renewed cert, and the ship goes
  back to https.
- **The ship's clock.** It knows today's date only from phone headers (`x-phone-time`) and
  BLE sync. After a power-off it must assume "unknown" and serve http.

### The hybrid idea: start_url http://voyage.coolphill.com/, 302 to https while valid

This doesn't work.
- **Android:** Chrome mints a WebAPK only for an https document, and `start_url` must have
  the document's origin. An http start_url on an https manifest is dropped and the document
  URL is used instead ([Chromium webapps concepts](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/webapps/concepts.md)).
  Chrome 154 would also try to upgrade http://voyage.coolphill.com to https by itself, and
  ask before using http when that fails.
- **iOS:** the icon's http to https redirect changes origin. iOS opens out-of-scope
  navigations in an in-app browser with a URL bar (WWDC23, via
  [progressivewebapps.com](https://progressivewebapps.com/capabilities/protocol-and-links/)),
  and the two origins don't share storage.
- **Service worker:** it's only registered for the https origin, so an http launch never
  reaches it, and the offline page is lost too.

### Other routes to full screen on Android without https

- **`requestFullscreen()` button over http:** works now, but takes one tap per launch.
  Realistic.
- **Trusted Web Activity:** needs https plus Digital Asset Links. It has the same cert
  problem and needs an APK.
- **Sideloaded WebView APK** (cleartext to 192.168.4.1, native "join the ship" screen,
  never expires): truly full screen. But every Android teammate has to allow unknown
  sources and accept Play Protect warnings, and Google has announced developer
  verification for sideloaded apps. Only realistic for one or two people.
- **Chrome flag `unsafely-treat-insecure-origin-as-secure`:** a per-phone setup, and not a
  dependable install path. Not realistic.

## 4. If HTTPS is done anyway: the design

1. **Captive portal stays on port 80.**
   - Probes (captive.apple.com and similar) get a 302 to `https://voyage.coolphill.com/`,
     but only while the cert is *known* valid: ship date known and at least 3 days before
     `not_after`.
   - Otherwise the 302 goes to `http://192.168.4.1/`, the IP, so there's no Chrome
     warning.
   - Never send HSTS, and keep `coolphill.com` free of `includeSubDomains` HSTS. It has
     none today; I checked the headers.
2. **DNS.** The ship already answers every A query with 192.168.4.1. Add an explicit
   answer for `voyage.coolphill.com`, which public DNS also has. Return an empty AAAA and
   HTTPS/SVCB, as it does now.
3. **Server.** Copying `lvweb` + `asyncio.start_server(ssl=)` as-is would allocate TLS
   buffers for every accept before the `MAX_CONN` check. Instead:
   - Run its own accept loop that only accepts (and wraps) while fewer than 2 TLS
     connections are live. The rest wait in the listen backlog (5), so phones see a delay,
     not a reset.
   - **HTTP/1.1 keep-alive** (today it's HTTP/1.0 close), idle timeout about 5 s.
   - **Bundle** the page, CSS, JS and text into the single `app.html.gz` (mostly done
     already), and serve icons and the manifest from the service-worker cache after the
     first visit.
   - Target: one or two handshakes per visit.
   - Send long `Cache-Control` headers on static files so the service worker revalidates
     rarely.
4. **Certificate slot** `/data/tls/`, which updates don't touch, like `/data/ship.json`:
   - `chain.pem` (public) and `meta.json` (`not_after`, serial), both delivered by the
     signed OTA.
   - `key.pem`, installed once per ship and never in the public repo.
   - Certbot should use `--reuse-key` so renewals change only the public chain. Renewals
     then carry nothing secret and can travel in the normal signed release.
   - The key gets to each ship once, either over USB or through an OTA piece encrypted to
     a per-ship secret already in `/data/ship.json`.
   - A key published in the repo would count as compromised, and the CA would have to
     revoke the cert.
5. **Renewal.** Box job: re-issue weekly and publish chain plus meta in a cert-only signed
   release. The relay page pushes it silently whenever an online phone opens the game.
6. **Expiry.** Expiry is checked against the ship's synced clock. Expired, about to expire
   or clock unknown means http mode. The page's service worker uses a cache-first shell
   and detects TLS or API failure, then bounces to `http://192.168.4.1/?renew=1`, which
   relays the cert.
7. **Memory and blocking.** Load the context only when there's a valid cert, about 14 KB
   with the full chain. Start serving TLS only when `gc.mem_free()` is above about 40 KB.
   Pause BLE sync while a handshake is in progress. Expect LED hitches of up to about
   0.4 s per new connection.
8. **Chain.** Ship the full 4-cert chain for compatibility; Root YE is too new to rely on.
   Trimming to leaf+YE2 saves about 6 KB of RAM once phones are checked.

## 5. Recommendation

- Stay on http. HTTPS's two real gains don't outweigh three costs:
  - Certificates that lapse on ships nobody has opened for a month or two, with
    full-screen warnings and a broken icon for exactly the users who installed it.
  - 66 KB of RAM and up to 0.7 s pauses per connection.
  - A separate origin that resets players.
- Instead, finish the iOS launch-image screen and add the Android Fullscreen button. If
  Android teammates turn out to matter a lot, revisit section 4. Run the hardware test
  first; it's 15 minutes on any loose Pico W.

## 6. Hardware test I need Phill to enable

- **Board:** any Pico W plugged into his laptop over USB, ideally a spare or the
  ship-2/LV-2 board, not a cased ship.
- **What it does:** it changes no game files. It copies two test-cert files, runs from RAM
  and starts an open `LV-TLSPROBE` AP. The laptop joins that AP and runs `tls_hammer.py`.
- **Commands:** `tools/https-probe/README.md` section 2.
- **What we get:** the real RP2040 handshake time (`hs_ms`) and the heap columns, to check
  sections 2.2 and 2.3.
- **Optional:** the same with Safari on his iPhone.
