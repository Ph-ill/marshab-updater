# HTTPS probe for the Pico W

Feasibility kit for serving the game over TLS (see `/REPORT.md` at the repo root for the
verdict). Nothing here is part of the game or the firmware build.

| File | What it is |
| --- | --- |
| `tls_probe.py` | MicroPython TLS server probe. Runs on a USB-attached Pico W (`mpremote run`) or on the unix probe build. Logs `gc.mem_free()` before accept, after wrap, after handshake, after the response, plus handshake and total time per connection. |
| `tls_hammer.py` | Host-side client (CPython 3): N parallel HTTPS GETs, R rounds, full TLS 1.2 handshakes (no resumption, like a phone). |
| `make_test_cert.sh` | Makes a throwaway ECDSA P-256 chain in `testcert/` (gitignored). |
| `mbedtls_config_rp2like.h` | The rp2 port's mbedTLS options for the unix build (`_in4k`: the proposed 4 KB receive buffer). |
| `unix/build.sh`, `unix/probe_alloc.c` | 32-bit unix MicroPython v1.29.0 with that config, mbedTLS allocating on the GC heap like on the Pico, and a counter of mbedTLS bytes (SIGUSR1 prints `ALLOC cur= peak=`). |
| `ecbench/` | Counts Cortex-M0+ instructions for the P-256 work of one server handshake, using qemu-arm and the same mbedTLS 3.6.6 sources. |

The real certificate lives in `/home/box/.secrets/lv_tls/` on the box. Never copy
`privkey.pem` into the repo, never print it, and don't put it on a board until the design
in REPORT.md section 4 is agreed. The probe only needs the test cert.

## 1. On the box (no hardware)

```sh
cd tools/https-probe
./make_test_cert.sh
MP=~/.cache/lv-firmware/micropython-v1.29.0 sh unix/build.sh        # or MP=/workspace/fwbuild/mp
./unix/micropython-tls32 -X heapsize=193k tls_probe.py seq 8443 &
python3 tls_hammer.py --host 127.0.0.1 --port 8443 -n 1 -r 3 --ca testcert/ca.pem
kill -USR1 %1        # prints mbedTLS bytes now and peak since the last USR1
# Parallel connections the way lvweb would see them:
./unix/micropython-tls32 -X heapsize=160k tls_probe.py async 8444 &
python3 tls_hammer.py --host 127.0.0.1 --port 8444 -n 6 -r 2
# Instruction count for the P-256 handshake work on a Cortex-M0+:
MP=~/.cache/lv-firmware/micropython-v1.29.0 sh ecbench/run.sh
```

## 2. On a Pico W over USB (Phill's laptop)

Use a **bare Pico W or any board you can plug in without opening a ship**. The probe
doesn't change the board's game files. It copies two test files to flash, runs from RAM,
and starts its own open AP `LV-TLSPROBE` (192.168.4.1) until it finishes. Unplug or press
Ctrl-C to stop it, and the board's own `main.py` runs again on the next boot. You need
lv-core firmware or stock MicroPython v1.29.0, which have the same TLS.

```sh
cd marshab-updater/tools/https-probe      # after `git fetch && git checkout https-probe`
./make_test_cert.sh                            # or copy testcert/ from the box
PORT=$(mpremote connect list | awk '/2e8a/ {print $1; exit}')   # the Pico's /dev/ttyACM*
mpremote connect $PORT cp testcert/fullchain.pem :/probe_cert.pem + cp testcert/privkey.pem :/probe_key.pem

# a) Sequential: 20 connections, clean heap and handshake numbers.
mpremote connect $PORT exec "PROBE={'cert':'/probe_cert.pem','key':'/probe_key.pem','mode':'seq','conns':20}" run tls_probe.py | tee probe-seq.log
#    meanwhile, on the laptop: join Wi-Fi "LV-TLSPROBE" (open), then
python3 tls_hammer.py --host 192.168.4.1 --port 443 -n 1 -r 20 --ca testcert/ca.pem | tee hammer-seq.log

# b) Parallel: asyncio server, 2, 4, then 6 connections at once.
mpremote connect $PORT exec "PROBE={'cert':'/probe_cert.pem','key':'/probe_key.pem','mode':'async','idle_s':20}" run tls_probe.py | tee probe-async.log
python3 tls_hammer.py --host 192.168.4.1 -n 2 -r 3; python3 tls_hammer.py --host 192.168.4.1 -n 4 -r 3; python3 tls_hammer.py --host 192.168.4.1 -n 6 -r 2

# c) Optional, with a phone: join LV-TLSPROBE and open https://192.168.4.1/ in Safari.
#    The test cert shows a warning; tap through. probe-*.log then has Safari's real handshakes.

# Clean up the board.
mpremote connect $PORT rm :/probe_cert.pem + rm :/probe_key.pem
```

To measure the full real chain size without the real key, run
`./make_test_cert.sh` and append two extra certificates to `testcert/fullchain.pem`
(e.g. `cat testcert/ca.pem testcert/ca.pem >> testcert/fullchain.pem`). The heap cost
depends on the chain's size, not on who signed it.

Send back `probe-*.log` and `hammer-*.log`. The `PROBE conn` lines give `hs_ms` (the
handshake on the RP2040, the number this kit exists for) and the heap columns. A line
`SUMMARY async ... lowest_free=` shows the headroom with N connections in flight. An
`OSError: [Errno 12] ENOMEM` means that many connections don't fit.
