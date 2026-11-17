# Kisero Pi wiring

Updated 2026-11-17 from the wiring sessions and onboard checks. All Pi pin numbers below are
**physical header positions (1–40)**. They are not GPIO numbers.

Shut down the Pi and unplug its power before moving wires. Each connection needs
a secure electrical contact. Bare plated holes on a sensor board need soldered
headers; loose jumper pins, glue, and tape are not substitutes.

## Shared 3.3V and ground on the breadboard

Use the breadboard's centre section, columns `a` to `e`. Holes `a5` through `e5`
are connected together; holes `a10` through `e10` are a separate connection.
The edge power rails are not used in this layout.

| Wire | Pi physical pin | Breadboard hole | Purpose |
| --- | --- | --- | --- |
| Red | 17 (3.3V) | a5 | Supply the shared 3.3V row |
| Black | 14 (ground) | a10 | Supply the shared ground row |

These two wires use a female socket on the Pi and a male pin in the breadboard.
Row 5 is **3.3V**, not 5V. Never connect the motion sensor's 5V supply to row 5.

## Buzzer: MH-FMG active, high-level trigger module

The user reports following this final breadboard layout:

| Wire | Buzzer label | Destination | Cable ends |
| --- | --- | --- | --- |
| Red | VCC | Breadboard c5 (3.3V) | Female on module, male in breadboard |
| Black | GND | Breadboard c10 (ground) | Female on module, male in breadboard |
| Yellow | I/O | Pi physical pin 12 (BCM GPIO18) | Female at both ends |

Use the module's printed labels. In the supplied connector-side photograph with
the round buzzer on the left and connector on the right, the labels read GND,
I/O, VCC from top to bottom.

The original direct-Pi wiring (VCC to 17, GND to 14, I/O to 12) produced three
beeps, confirmed by the user. An original short rhythm was also played. The final
breadboard arrangement was subsequently retested: the user confirmed hearing
all three short beeps on 2026-10-28.

- `python3 scripts/test-buzzer.py` sends three short beeps.
- `python3 scripts/buzzer-song.py` plays a short fixed-pitch sailing rhythm.

Run these manually from a checkout on the Pi with gpiozero and lgpio installed.
Both scripts use GPIO18, switch the buzzer off, and release the GPIO afterward.
These standalone diagnostics use the same GPIO as the running alarm service.
See [Continuous alarm service](#continuous-alarm-service) before using them.

## Motion sensor: HW-416 / HC-SR501 type PIR

The latest selected signal pin is **GPIO26 / physical pin 37**, replacing the
earlier GPIO17 / physical pin 11 suggestion. Physical pin 4 was later confirmed
free by the user and selected as the 5V supply.

| Wire | PIR label/function | Pi physical pin |
| --- | --- | --- |
| Red | VCC (5V input) | 4 (5V) |
| Yellow | OUT (signal) | 37 (BCM GPIO26) |
| Black | GND | 39 (ground) |

For the photographed HW-416 board only: with both orange adjusters at the top,
the yellow jumper on the right, and the three connection pins at the bottom,
the pins were identified as VCC (left), OUT (middle), GND (right). Do not transfer
that orientation to a different sensor board without checking its pinout.

These are female-to-female connections. On 2026-10-28, the bounded GPIO26 input
test observed HIGH, then LOW (idle) at 12.6 seconds, then HIGH again at 18.2 seconds
while the user was instructed to move in front of the sensor. Both idle and active
output levels were observed with an input pull-down. Allow about a minute for
the PIR to settle after powering it on. The continuous alarm service is installed.

Run `python3 scripts/test-motion.py --seconds 60` from a checkout on the Pi for
a manual test. It watches physical pin 37 / GPIO26, prints input transitions,
and releases the GPIO when finished. It does not activate the buzzer.

## Temperature and humidity

The current SHTC3 I²C sensor returned a reading at `0x70` aboard on
17 November 2026. The earlier SHT3x at `0x44` or `0x45` is also supported
by the collector and uses the same Pi signals.

| Wire | Sensor label | Destination |
| --- | --- | --- |
| Red | VIN / VCC | Shared 3.3V row, b5 in the breadboard layout |
| Black | GND | Shared ground row, b10 in the breadboard layout |
| Blue | SDA | Pi physical pin 3 (BCM GPIO2) |
| Green | SCL | Pi physical pin 5 (BCM GPIO3) |

For a breakout mounted outside the breadboard, use female-to-male jumpers
to b5/b10 and female-to-female jumpers to the Pi. If the breakout plugs into
the breadboard, place its header pins in separate connected rows. Follow the
labels on the actual board, since pin order can vary.

For a read-only sensor check, run
`python3 /opt/kisero/collector/sensor_collector.py --check` on the Pi.

## USB GPS

The onboard u-blox 7 GPS plugs into a USB port and enumerates under
`/dev/serial/by-id/usb-u-blox*`. The GPS tracker uses this receiver. The
USB setup requires no GPIO wiring.

### Earlier GPIO UART GPS experiment

ATGM336H-5N31 breakout; the user reported connecting it on 2026-11-14.
The receive-only wiring agreed for this board is:

| GPS label | Destination |
| --- | --- |
| VCC | Breadboard d5 (3.3 V) |
| GND | Breadboard d10 (ground) |
| TX | Pi physical pin 10 (BCM GPIO15 / UART RX) |
| RX, PPS | Leave disconnected |

The antenna cable snaps onto the small round socket; no solder is needed there.
The header joints and exact wire positions have not been independently verified.

The earlier [UART setup script](scripts/enable-gps-uart.sh) backs up the boot
files, enables the GPIO UART, and removes the serial login console. A reboot
applies it. [check-gps.py](scripts/check-gps.py) counts valid NMEA sentences
without printing coordinates. Only one reader should open a serial device at
a time.

On 14 November 2026 the Pi rebooted successfully and GPIO15 reported `RXD1`.
A 20-second read of `/dev/serial0` at 9600 baud received zero bytes. The current
setup uses the USB receiver.

## Pins currently allocated by this layout

| Pi physical pin | Role |
| --- | --- |
| 3 | Cabin sensor SDA (BCM GPIO2) |
| 4 | PIR 5V power |
| 5 | Cabin sensor SCL (BCM GPIO3) |
| 12 | Buzzer signal (GPIO18) |
| 14 | Breadboard ground feed |
| 17 | Breadboard 3.3V feed |
| 37 | PIR output (GPIO26) |
| 39 | PIR ground |

The previous direct temperature-sensor supply pins 1 and 6 are superseded by the
breadboard supply in this plan. Do not retain duplicate loose supply wires.

## Continuous alarm service

The alarm service uses the verified PIR BCM26 (physical37) and buzzer BCM18
(physical12) wiring above. Stop `kisero-alarm.service` before running standalone
GPIO buzzer/motion scripts, because the service owns these GPIO lines. Restart
it afterward; the PIR warm-up is 60 seconds. No wiring changes are required.
