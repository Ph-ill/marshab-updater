# The ship battery: wiring a UPS-Lite v1.3 to a Pico W

A ship can run off the shelf, away from a USB plug, on a **UPS-Lite v1.3**: a small
battery board made for the Raspberry Pi Zero (1000 mAh LiPo cell, charger, 5 V output and a
CW2015 fuel gauge). It was designed to press onto a Pi Zero's pins with spring-loaded "pogo"
pins; a Pico W has a different layout, so you solder **five wires, one diode and two
resistors** between the two boards. The firmware (`board/lvbatt.py`) finds the gauge by
itself, and the phones then show the charge at the top of the ship's page.

The battery is optional. A board without one plays exactly as before.

![Wiring: UPS-Lite v1.3 to Pico W](battery-wiring.svg)

Anything marked **[UNVERIFIED]** comes from the vendor's documents or photos and has not
been checked on a real board yet. Check those points with a multimeter before you trust
them (section 5).

## 1. What you need

| Item | Notes |
|---|---|
| UPS-Lite v1.3 | with its cell attached, as it comes |
| Pico W | running the game firmware (`docs/BENCH_TEST.md`) |
| 1 × 1N5817 Schottky diode | 1 A, 20 V. A 1N5819 also works. **Not** a 1N4001-type diode: it drops too much voltage |
| 2 × 4.7 kΩ resistors | 1/4 W or smaller. Bands: yellow, violet, red (then gold). Anything 2.2–10 kΩ works |
| Wire | stranded silicone wire is the easiest. See section 3 for gauges and colours |
| Optional: 1 × 100–220 µF electrolytic capacitor, 10 V or more | across VSYS and GND on the Pico. It helps if Wi-Fi makes the board reset (section 8) |
| Soldering iron (about 330 °C), thin rosin-core solder, flux pen | |
| Heat-shrink tube or electrical tape, wire stripper, flush cutters | |
| Multimeter | needed for the checks in section 5 |
| A 5 V 2 A micro-USB phone charger | for charging the battery (section 6) |

**Safety**

- The LiPo cell is the only dangerous part. Never put the iron near it, never bend or
  puncture it, and never short the board's 5 V or battery pads to GND.
- Turn the UPS-Lite's switch **off** while you solder.
- Unplug both USB cables while you solder.
- If the cell ever swells, gets hot or smells, stop using it.

## 2. The connections

The UPS-Lite's five pogo pins sit where the Pi Zero's header pins 3–7 would be. They keep
the Pi's pin numbers, so this guide calls them by those numbers. Pin 8 has no pogo pin.

| UPS-Lite pogo pin (Pi pin) | Wire colour | Goes to on the Pico W | Notes |
|---|---|---|---|
| 5V-OUT (Pi pin 4) | red | **VSYS, pin 39** | through the 1N5817 diode, band (stripe) toward VSYS |
| GND (Pi pin 6) | black | **GND, pin 38** | any Pico GND works: pins 3, 8, 13, 18, 23, 28, 33, 38 |
| SDA (Pi pin 3) | blue | **GP4, pin 6** | the fuel gauge's I2C data line |
| SCL (Pi pin 5) | yellow | **GP5, pin 7** | the fuel gauge's I2C clock line |
| GPIO4 "charger plugged in" (Pi pin 7) | green | **GP6, pin 9** | only works with PAD1 shorted (below) |
| (nothing) | resistor | **3V3(OUT), pin 36** → GP4 pin 6 | 4.7 kΩ pull-up for SDA |
| (nothing) | resistor | **3V3(OUT), pin 36** → GP5 pin 7 | 4.7 kΩ pull-up for SCL |

Pico W pin numbers count from pin 1 (GP0), at the top left with the USB socket at the top
and the parts facing you, down the left side to pin 20, then up the right side from pin 21
to pin 40 (VBUS, top right). Pin 39 VSYS, 38 GND and 36 3V3(OUT) are near the top of the
right side. Pins 6, 7 and 9 are on the left side. The pin numbers are also printed on the
back of the Pico.

### Finding the pogo pins

Hold the UPS-Lite with the **cell side down, micro-USB socket at the top**, as in the
picture. The pogo pins form two columns: **[UNVERIFIED: from the vendor photo]**

```
            left column   right column
  row 1     SDA (3)       5V-OUT (4)
  row 2     SCL (5)       GND (6)
  row 3     GPIO4 (7)     (no pin)
```

So: the pin on its own, at the bottom, is the charger line. The pin above it is SCL, and
the one above that is SDA. In the other column, the pin beside SCL is GND and the pin
beside SDA is 5V-OUT. **Always confirm 5V-OUT and GND with the multimeter
(section 5) before soldering anything to them.**

### PAD1: turning on the "charger plugged in" signal

On the back of the UPS-Lite are two small pads that the vendor's notes say must be
shorted for the "power plugged in" signal (this guide calls them PAD1). Join them with a
blob of solder (or a short scrap of wire). Without this, the vendor says the signal is
"unstable", so the bolt may flicker or never show. The battery percentage still works
either way. **[UNVERIFIED: the pads' exact position and silkscreen label; the vendor's
notes show them in a photo of the back.]**

### The diode, and why it is needed

The Pico W's VSYS input takes 1.8–5.5 V. The Pico's own USB socket also feeds VSYS
(through a diode on the Pico). The Raspberry Pi Pico W datasheet (section "Powering Pico
W") says a second supply on VSYS must go through a **Schottky diode** so the two supplies
can't fight. Then whichever is higher powers the board, and nothing back-feeds a laptop or
the UPS-Lite.

- Solder the diode **in the red wire**, close to the Pico: the end **without** the stripe
  toward the UPS-Lite, the end **with the stripe (band)** at VSYS pin 39.
- Wrong way round, nothing is damaged, but the Pico won't run from the battery.
- A Schottky diode drops about 0.2–0.4 V, so the Pico sees about 4.6–4.8 V. That's fine.

### The pull-up resistors

I2C needs both lines pulled up to 3.3 V. The Pico's own pull-ups are too weak to be
reliable, and the UPS-Lite's schematic shows none on its side. **[UNVERIFIED for v1.3:
the published schematic is for v1.2.]**

- Solder one 4.7 kΩ resistor from GP4 (pin 6) to 3V3(OUT) (pin 36).
- Solder the other from GP5 (pin 7) to 3V3(OUT) (pin 36).
- The easy way: bend the resistor legs so one leg of each sits on the pin 6 / pin 7 pad
  with the signal wire, twist their other two legs together, and run one short wire from
  that joint to pin 36. Cover the bare legs with heat-shrink.
- **Pull-ups go to 3V3(OUT) only. Never to VSYS or 5 V**: the Pico's pins take 3.3 V.

## 3. Wire

| Wire | Colour | Gauge |
|---|---|---|
| 5V-OUT → diode → VSYS | red | 24 AWG (thicker is fine) |
| GND → GND | black | 24 AWG |
| SDA → GP4 | blue | 26–28 AWG |
| SCL → GP5 | yellow | 26–28 AWG |
| GPIO4 → GP6 | green | 26–28 AWG |

- Keep every wire short: **10–15 cm at most**, just long enough to lay the boards side by
  side or back to back in the case.
- Twist SDA and SCL loosely with GND if they're longer than about 10 cm.
- Keep wires and the battery away from the Pico W's **antenna**: the end of the board
  opposite the USB socket. Metal there costs Bluetooth and Wi-Fi range.
- Colours are only a suggestion, but red/black for power avoids mistakes.

## 4. Soldering, step by step

1. **Check the UPS-Lite first (section 5, checks A–C)** with nothing soldered. Mark the
   5V-OUT and GND pogo pins with a marker.
2. **PAD1**: solder the two PAD1 pads together on the UPS-Lite's back.
3. **Pogo pins.** Tin each wire end (strip 3 mm, add a little solder). Solder each wire to
   the **side or base (the barrel) of its pogo pin, never to the moving tip (the
   plunger)**: solder on the plunger jams it. Be quick (2–3 s) so the barrel's spring
   doesn't lose temper. If a pin has a solder pad or via under it on the board, solder
   there instead. **[UNVERIFIED: whether the pins' barrels take solder well; the vendor
   doesn't say. If solder won't stick, use flux, or solder to the pad the pin sits in.]**
   Keep the iron well away from the cell.
4. **Pico side, signals.** Solder the blue wire to pin 6 (GP4), yellow to pin 7 (GP5),
   green to pin 9 (GP6). If the Pico has header pins, solder to them, or use
   female jumper housings.
5. **Pull-ups.** Fit the two resistors from pins 6 and 7 to pin 36 (section 2).
6. **Diode.** Solder the red wire to the diode's plain end, the striped end to pin 39
   (VSYS). Cover the diode and joints with heat-shrink.
7. **GND.** Black wire to pin 38.
8. Optional capacitor: + leg (the longer one; the stripe marks −) to VSYS pin 39, − leg to
   GND pin 38.
9. Look over every joint: shiny, no blobs bridging to the next pin, no stray strands.
10. Do checks D–F (section 5) **before** turning the switch on.

## 5. Multimeter checks

Set the meter to DC volts (20 V range) or continuity (the beep).

| Check | How | Expect |
|---|---|---|
| A. 5V-OUT pin | UPS-Lite switch **on**, nothing connected: black probe on the micro-USB socket's metal shell, red on the pogo pin you think is 5V-OUT | about **5.0 V** (4.8–5.2) |
| B. GND pin | continuity between the GND pogo pin and the micro-USB socket's metal shell | beep |
| C. Signal pins | switch on, black on GND: SDA, SCL and GPIO4 pins | 0 V or a few volts, **never 5 V** |
| D. No shorts | switch **off**, nothing plugged in: continuity VSYS (pin 39) to GND (pin 38), and 3V3(OUT) (pin 36) to GND | **no** beep (a short beep that stops is the capacitor charging, that's OK) |
| E. Diode | diode mode, red probe on the UPS-Lite's 5V-OUT pin, black on Pico pin 39 | about 0.2–0.4 (reversed: nothing) |
| F. Pull-ups | resistance from pin 6 to pin 36, and from pin 7 to pin 36 | about 4.7 kΩ each |
| G. Powered | switch **on**, no USB: black on pin 38, red on pin 39 / pin 36 / pin 6 / pin 7 | about 4.6–4.8 V / 3.3 V / 3.3 V / 3.3 V |
| H. Charger line | charger plugged into the UPS-Lite: pin 9 (GP6) to GND | about 2–3.3 V plugged in, about 0 V unplugged |

If check A shows 5 V on a different pin from the picture, trust the meter and rework the
table above before soldering.

## 6. Charging, and the power switch

- **Charge through the UPS-Lite's own micro-USB socket**, with a 5 V 2 A phone charger
  (the vendor recommends 2 A). The board keeps running while it charges.
- **The Pico W's USB socket does not charge the battery.** The diode stops current going
  back toward the UPS-Lite. Use the Pico's USB for updates and the bench, as before.
- The UPS-Lite's light: **red** while charging, **green** when full.
- The **switch** on the UPS-Lite turns its 5 V output on and off. Off, the Pico runs only
  if its own USB is plugged in. The gauge stays powered by the cell either way.
- Rough numbers, **[UNVERIFIED estimates, not measured]**: a full charge takes about 3
  hours (the charger gives up to 400 mA); a Pico W with Wi-Fi and Bluetooth on uses about
  60–100 mA, so a full battery should last very roughly 7–8 hours. Check the real number
  on your board and note it here.
- The cell's protection cuts the output at about 2.7 V. The gauge reads about 1% near 3.5
  V. Charge it when the phone says to (under 15%); storing it flat for weeks harms it.

## 7. First power-up test

You need `mpremote` on a computer (`pip install mpremote`) and the board on USB. Turn the
UPS-Lite switch on.

1. **Is the gauge there?** It should answer at address 0x62:

   ```sh
   mpremote exec "from machine import I2C, Pin; print([hex(a) for a in I2C(0, sda=Pin(4), scl=Pin(5), freq=100000).scan()])"
   ```

   Expect `['0x62']`. An empty list `[]` means: see section 8, "Not detected".

2. **A raw reading** (wakes the gauge if it's asleep, waits 2 s, then prints the cell
   voltage, the percent and the charger line):

   ```sh
   mpremote exec "
   from machine import I2C, Pin
   import time
   i = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)
   if i.readfrom_mem(0x62, 0x0A, 1)[0] & 0xC0: i.writeto_mem(0x62, 0x0A, b'\x30')
   time.sleep(2)
   v = i.readfrom_mem(0x62, 2, 2); s = i.readfrom_mem(0x62, 4, 2)
   print('mV', ((v[0] & 0x3F) << 8 | v[1]) * 305 // 1000, 'percent', s[0], 'plugged in', Pin(6, Pin.IN, Pin.PULL_DOWN).value())
   "
   ```

   Expect something like `mV 3950 percent 72 plugged in 1` (between 3500 and 4200 mV;
   `plugged in` is 1 with the charger in the UPS-Lite's socket, 0 without). Then
   `mpremote reset` to start the game again.

3. **The game's own check.** Run the bench (`docs/BENCH_TEST.md`, fast path). Its report
   gets a `battery` row, and the self-test prints:

   ```
   SELFTEST battery: detected, 72%, 3950 mV, charging yes
   ```

   It is always INFO: a missing battery never fails the bench.

4. **On a phone**, join the ship's hotspot and open the game: a battery mark with the
   percent at the top of the page, with a bolt while it charges.

5. **Unplug the Pico's USB.** The board should keep running on the battery (the hotspot
   stays up).

## 8. Troubleshooting

**The phone / self-test says 0%, or "reading unknown"**

- Just after the gauge wakes (first power-up, or after the cell was disconnected), it
  needs a few seconds to estimate. The firmware tries again after 5 s. Wait a minute.
- Check the raw reading (section 7, step 2). If `mV` is about 3500 or lower, the cell
  really is flat: charge it.
- `mV` near 0: the gauge has no power. The cell is disconnected, or the protection has
  tripped after a deep discharge. Plug the charger into the UPS-Lite for a while to wake
  the protection.
- The percent is the gauge's own estimate from its built-in cell profile, and can be off
  by a few percent on this cell **[UNVERIFIED]**. The voltage is the honest number.

**"none detected" / the scan prints `[]`**

- SDA and SCL swapped: swap the blue and yellow wires at the Pico end.
- Missing or wrong pull-ups: check F in section 5 (4.7 kΩ, to pin 36).
- No common ground: check the black wire (check B and continuity to Pico pin 38).
- A cold joint: re-flow any dull or lumpy joint, and wiggle each wire while scanning.
- The UPS-Lite's switch is off **and** the cell is flat.
- Wrong pins in software: the game expects GP4/GP5. Other pins: set `bat_sda` and
  `bat_scl` in `/data/ship.json` (section 9).
- Still nothing: put `"battery": true` in `ship.json`. The phone then shows the battery as
  unknown, which at least confirms the firmware side.

**The bolt never shows while charging**

- PAD1 isn't shorted (section 2).
- The green wire isn't on GP6 (pin 9), or check H fails.
- The vendor's notes use the pin as a floating input; this firmware adds a pull-down by
  default so an unconnected pin reads "not charging". If the line reads 1 all the time,
  set `"bat_chg_pull": "none"` in `ship.json` (section
  9). The default pull-down holds it at 0 when unplugged. **[UNVERIFIED: the signal level
  on v1.3 with the Pico's pull-down; about 2.2–2.5 V expected when plugged in, enough for
  a "1".]**

**The board resets or drops when Wi-Fi starts (on battery only)**

- Wi-Fi draws short current bursts, and thin or long wires drop the voltage. Use 24 AWG
  red and black, keep them short, and check the joints.
- Pogo pin contact: if you soldered to the barrel, check the joint isn't cracked.
- Add the 100–220 µF capacitor across VSYS and GND (section 1).
- Check the diode is a Schottky (1N5817/1N5819), not a 1N4001.
- The percent on the phone won't jump about during bursts: the firmware smooths the
  voltage and only reads while the radio is idle.

## 9. Settings (all optional, `/data/ship.json`)

| Key | Default | Meaning |
|---|---|---|
| `battery` | `"auto"` | `"auto"` looks once at boot; `true` always shows the battery (unknown if missing); `false` never looks |
| `bat_sda`, `bat_scl` | `4`, `5` | the I2C pins (GP numbers) |
| `bat_i2c` | `0` | the RP2040 I2C block for those pins |
| `bat_chg` | `6` | the charger-detect GP number; `-1` for none |
| `bat_chg_pull` | `"down"` | `"down"`, `"up"` or `"none"` on that pin |
| `bat_every_s` | `60` | seconds between readings (5 at least) |

## Sources

- UPS-Lite v1.3 user notes and photos (the vendor's instruction PDF and its example
  Python script): pogo pins on Pi pins 3–7, charge-detect on GPIO4
  with PAD1 shorted, CW2015 at address 0x62, the 5 V 2 A charger, the LED colours, the
  1000 mAh cell, 400 mA charging.
- Cellwise CW2015 datasheet: the registers the firmware reads (VERSION 0x00, VCELL
  0x02–03 at 305 µV per step, SOC 0x04–05, MODE 0x0A).
- Raspberry Pi Pico W datasheet, "Powering Pico W": VSYS 1.8–5.5 V, a Schottky diode for a
  second supply, and the pinout.
- MicroPython `machine.I2C` documentation (rp2 port): the I2C timeout and pins.

## What has not been checked yet

- The pogo pin order on a real v1.3 board (from the photo only).
- Whether the pogo pins' barrels take solder.
- Whether v1.3 has its own I2C pull-ups (the published schematic is v1.2, with a
  MAX17040G gauge).
- The PAD1 pads' exact position.
- The GP6 voltage with the pull-down fitted.
- Charge time, run time and how accurate the percent is on this cell.
- **None of this has been tried on hardware yet.** The firmware was tested against a
  simulated gauge only. Please note what you find here.
