# Kisero Pi wiring

Recorded 2026-10-28 from the user's wiring session. All Pi pin numbers below are
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
breadboard arrangement preserves the same electrical connections, but has not
yet been retested after the user rearranged the wires.

- `python3 scripts/test-buzzer.py` sends three short beeps.
- `python3 scripts/buzzer-song.py` plays a short fixed-pitch sailing rhythm.

Run these manually from a checkout on the Pi with gpiozero and lgpio installed.
Both scripts use GPIO18, switch the buzzer off, and release the GPIO afterward.
They do not install a background alarm or connect motion detection to the buzzer.
A fixed-pitch active buzzer produces rhythms rather than pitched melodies.

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

These are female-to-female connections. The user reports following the wiring
instructions; motion detection and the final fitted connections have not yet
been checked. Allow about a minute for the PIR to settle after powering it on.
No motion-monitoring service has been deployed yet.

## Temperature/humidity: SHT3x breakout

The latest photo shows bare VIN, GND, SCL, SDA holes and an unattached pin strip.
A four-pin header must be soldered by someone equipped to do so, or the module
must be replaced with a version with a fitted connector. Until then, treat the
sensor as awaiting reliable reconnection, even though earlier temporary wiring
successfully produced readings.

The planned breadboard wiring after fitting a header is:

| Wire | SHT3x label | Destination |
| --- | --- | --- |
| Red | VIN / VCC | Breadboard b5 (3.3V) |
| Black | GND | Breadboard b10 (ground) |
| Blue | SDA | Pi physical pin 3 (BCM GPIO2) |
| Green | SCL | Pi physical pin 5 (BCM GPIO3) |

If the sensor stays outside the breadboard, use female-to-male power wires to
b5/b10 and female-to-female signal wires to the Pi. If its soldered header is
instead inserted into the breadboard, place its four pins in **different numbered
rows** and adapt the jumper connections to those rows. Do not put all four pins
in one connected a–e row.

Before this breadboard rearrangement, the sensor responded at I²C address `0x44`.
On 2026-10-28, a scheduled upload at 20:13 Europe/Madrid reported 23.42°C and 66.9%
humidity and reached the website API. The five-minute sensor service is already
installed, but this earlier success does not verify the later loose connections.

## GPS

Not connected. The last photograph showed the rear of a module and a loose
header. Confirm the model, required supply voltage, labels, and a secure fitted
connector before choosing its final wiring. No GPS wiring is recorded as complete.

## Pins currently allocated by this layout

| Pi physical pin | Role |
| --- | --- |
| 3 | SHT3x SDA (planned reconnection) |
| 4 | PIR 5V power |
| 5 | SHT3x SCL (planned reconnection) |
| 12 | Buzzer signal (GPIO18) |
| 14 | Breadboard ground feed |
| 17 | Breadboard 3.3V feed |
| 37 | PIR output (GPIO26) |
| 39 | PIR ground |

The previous direct temperature-sensor supply pins 1 and 6 are superseded by the
breadboard supply in this plan. Do not retain duplicate loose supply wires.
