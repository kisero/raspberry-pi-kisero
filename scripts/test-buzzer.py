#!/usr/bin/env python3
"""Sound three short beeps on the MH-FMG module wired to physical pin 12."""
from time import sleep

from gpiozero import Buzzer
from gpiozero.pins.lgpio import LGPIOFactory


def main():
    # BCM GPIO18 is physical pin 12. Module power: pin 17 (3.3V); GND: pin 14.
    factory = LGPIOFactory(chip=0)
    try:
        with Buzzer(18, active_high=True, initial_value=False, pin_factory=factory) as buzzer:
            try:
                for _ in range(3):
                    buzzer.on()
                    sleep(0.2)
                    buzzer.off()
                    sleep(0.3)
            finally:
                buzzer.off()
        print('Three beep signals sent on GPIO18 (physical pin 12); output released.')
        print('Confirm the sound by listening; GPIO control alone cannot confirm the buzzer is audible.')
    finally:
        factory.close()


if __name__ == '__main__':
    main()
