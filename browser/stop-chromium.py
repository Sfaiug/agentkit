"""Flush the browser profile before systemd tears down Chromium's processes."""
import os
import sys
import time

from playwright.sync_api import Error, sync_playwright
from runtime import endpoint

if len(sys.argv) != 2 or not sys.argv[1].isdigit():
    # systemd can omit MAINPID when Chromium has already exited or crashed.
    sys.exit(0)
pid = int(sys.argv[1])
if pid <= 0:
    sys.exit(0)
try:
    os.kill(pid, 0)
except ProcessLookupError:
    sys.exit(0)
try:
    with sync_playwright() as driver:
        browser = driver.chromium.connect_over_cdp(
            endpoint(), timeout=5000, no_defaults=True,
        )
        browser.new_browser_cdp_session().send('Browser.close')
except Error:
    # Browser.close can disconnect before its reply; a crashed browser also
    # has no CDP endpoint. Wait for the actual process, then allow systemd's
    # ordinary signal/timeout handling to finish a stuck shutdown.
    pass

deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        sys.exit(0)
    time.sleep(0.1)
print('Chromium did not exit after the CDP close request; systemd will finish shutdown.', file=sys.stderr)
