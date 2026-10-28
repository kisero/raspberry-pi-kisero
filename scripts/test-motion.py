#!/usr/bin/env python3
"""Read the PIR at physical pin 37 / BCM GPIO26 for a bounded manual test."""
import argparse
from time import monotonic, sleep

from gpiozero import DigitalInputDevice
from gpiozero.pins.lgpio import LGPIOFactory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=60)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error('--seconds must be between 5 and 120')
    factory = LGPIOFactory(chip=0)
    started = monotonic()
    changes = 0
    try:
        with DigitalInputDevice(26, pull_up=False, pin_factory=factory) as sensor:
            previous = bool(sensor.value)
            print(f'PIR initial state: {"HIGH (motion/hold)" if previous else "LOW (idle)"}', flush=True)
            print(f'Watching GPIO26 for {args.seconds} seconds. Stand still, then move in front of the dome.', flush=True)
            while monotonic() - started < args.seconds:
                current = bool(sensor.value)
                if current != previous:
                    changes += 1
                    print(f'{monotonic() - started:.1f}s: {"HIGH (motion/hold)" if current else "LOW (idle)"}', flush=True)
                    previous = current
                sleep(0.05)
            print(f'Test ended: {changes} state changes; final state {"HIGH" if previous else "LOW"}.', flush=True)
            print('Match state changes to actual movement to confirm operation.', flush=True)
    finally:
        factory.close()


if __name__ == '__main__':
    main()
