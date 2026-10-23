# Stand-ins for the Pico W's `network` (the hotspot) and `machine` (the LED pin) so
# board/selftest.py runs on the unix port for tests/test_bench.py (tools/bench.py
# --fake-board). The hotspot "comes up" on 127.0.0.1; LED writes are counted and logged.
import sys

import fake_machine
import fake_network


def install():
    sys.modules["machine"] = fake_machine
    sys.modules["network"] = fake_network
