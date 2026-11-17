#!/usr/bin/env python3
"""Read GPS NMEA briefly without printing coordinates."""
import argparse
import os
import select
import termios
import time
from collections import Counter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--device', default='/dev/serial0')
parser.add_argument('--baud', type=int, choices=(9600, 38400, 115200), default=9600)
parser.add_argument('--seconds', type=int, choices=range(1, 121), metavar='1..120', default=20)
args = parser.parse_args()
fd = os.open(args.device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
original = termios.tcgetattr(fd)
counts = Counter()
fix = False
size = 0
pending = b''
try:
    speed = getattr(termios, f'B{args.baud}')
    settings = [0, 0, termios.CS8 | termios.CREAD | termios.CLOCAL, 0,
                speed, speed, original[6][:]]
    termios.tcsetattr(fd, termios.TCSANOW, settings)
    end = time.monotonic() + args.seconds
    while (remaining := end - time.monotonic()) > 0:
        if not select.select([fd], [], [], remaining)[0]:
            break
        data = os.read(fd, 4096)
        size += len(data)
        *lines, pending = (pending + data).split(b'\n')
        pending = pending[-4096:]
        for line in lines:
            body, sep, checksum = line.strip().rpartition(b'*')
            if not sep or not body.startswith(b'$') or len(checksum) != 2:
                continue
            value = 0
            for byte in body[1:]:
                value ^= byte
            if checksum.upper() != f'{value:02X}'.encode():
                continue
            fields = body.split(b',')
            name = fields[0][-3:].decode('ascii', errors='replace')
            counts[name] += 1
            if (name == 'RMC' and len(fields) > 2 and fields[2] == b'A') or (
                name == 'GGA' and len(fields) > 6 and fields[6] in (b'1', b'2', b'4', b'5')
            ):
                fix = True
finally:
    termios.tcsetattr(fd, termios.TCSANOW, original)
    os.close(fd)
print(f'GPS bytes received: {size}; valid NMEA: {dict(counts)}; position fix: {"yes" if fix else "not observed"}')
raise SystemExit(0 if counts else 1)
