#!/usr/bin/env python3
"""Read the 4G UFI modem status without printing SIM identifiers or credentials."""
import argparse
import getpass
import json
import os
from pathlib import Path
import urllib.request

URL = 'http://192.168.100.1/himiapi/json'
SESSION = Path(f'/run/user/{os.getuid()}/kisero-ufi-session.json')
PRIVATE = {'imei', 'imsi', 'iccid', 'password', 'passw', 'spassw', 'session', 'sessionid', 'username', 'ssid'}


def call(command, session='', **fields):
    body = {'cmdid': command, 'sessionId': session, **fields}
    request = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        'Content-Type': 'application/json;charset=UTF-8', 'Authorization': session})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def redact(value):
    if isinstance(value, dict):
        return {key: '[redacted]' if key.lower() in PRIVATE else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', action='store_true', help='Prompt for the modem web password')
    parser.add_argument('--select-sim', type=int, choices=(1, 2), help='Select a supported SIM slot (one-based); the modem may restart')
    args = parser.parse_args()
    session = json.loads(SESSION.read_text())['session'] if SESSION.exists() else ''
    if args.login:
        result = call('login', username='admin', password=getpass.getpass('Modem web password: '))
        if result.get('reply') != 'ok':
            raise SystemExit('Modem login failed.')
        session = result['session']
        SESSION.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(SESSION, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'session': session}, handle)
        os.chmod(SESSION, 0o600)
        print('Modem login succeeded; session stored privately for this boot.')
    if not session:
        raise SystemExit('Run with --login first.')
    if args.select_sim is not None:
        config = call('getconfig', session)
        if args.select_sim > int(config.get('simnum', 1)):
            raise SystemExit('Requested SIM slot is not supported by this modem.')
        current = call('getsimset', session)
        if current.get('reply') != 'ok':
            raise SystemExit('Could not read current SIM selection.')
        params = current['params']
        if params['simset'] == args.select_sim - 1:
            print('Requested SIM slot is already selected.')
            return
        if config.get('simhaspwd'):
            raise SystemExit('Modem requires a SIM-selection password; no change made.')
        result = call('setsimnum', session, params=args.select_sim - 1, params1=params.get('spassw', ''))
        if result.get('reply') != 'ok':
            raise SystemExit('Modem rejected SIM selection: ' + str(result.get('reply')))
        print(f'SIM slot {args.select_sim} selected. Allow the modem time to register.')
        return
    for command in ('getallstatus', 'getoverview', 'getapninfo', 'getsimset', 'getnetworkmode', 'gethimiusbtether', 'getcondetect'):
        result = call(command, session)
        if result.get('reply') == 'SessionOut':
            raise SystemExit('Modem session expired. Run with --login again.')
        if result.get('reply') != 'ok':
            raise SystemExit(f'Modem status request {command} failed: {result.get("reply")}')
        print(command, json.dumps(redact(result), ensure_ascii=False))


if __name__ == '__main__':
    main()
