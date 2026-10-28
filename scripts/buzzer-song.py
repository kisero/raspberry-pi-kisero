#!/usr/bin/env python3
"""Play an original, short sailing rhythm on the active buzzer at BCM GPIO18."""
from time import sleep

from gpiozero import Buzzer
from gpiozero.pins.lgpio import LGPIOFactory

# Fixed-pitch active buzzer: durations vary, rather than musical pitches.
# Each tuple is (sound duration, silence duration), in seconds.
PHRASE_A = [(0.12, 0.12), (0.12, 0.12), (0.30, 0.22), (0.12, 0.12), (0.30, 0.45)]
PHRASE_B = [(0.12, 0.12), (0.24, 0.12), (0.12, 0.12), (0.24, 0.12), (0.42, 0.50)]
FINALE = [(0.12, 0.10), (0.12, 0.10), (0.12, 0.10), (0.50, 0.20)]


def main():
    factory = LGPIOFactory(chip=0)
    try:
        with Buzzer(18, active_high=True, initial_value=False, pin_factory=factory) as buzzer:
            try:
                for sound, silence in PHRASE_A + PHRASE_A + PHRASE_B + FINALE:
                    buzzer.on()
                    sleep(sound)
                    buzzer.off()
                    sleep(silence)
            finally:
                buzzer.off()
    finally:
        factory.close()
    print('Sailing rhythm finished; buzzer switched off and GPIO released.')


if __name__ == '__main__':
    main()
