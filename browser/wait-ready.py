"""Bound startup ordering to actual display/CDP readiness."""
import subprocess
import sys
import time
import urllib.request

from runtime import endpoint

for attempt in range(100):
    try:
        if sys.argv[1] == 'x11':
            subprocess.run(['/usr/bin/xdotool', 'getdisplaygeometry'], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
        else:
            with urllib.request.urlopen(endpoint() + '/json/version', timeout=1) as response:
                if b'Browser' not in response.read():
                    raise ValueError('CDP not ready')
        sys.exit(0)
    except (OSError, ValueError, subprocess.SubprocessError):
        time.sleep(0.2)
raise SystemExit(f'{sys.argv[1]} did not become ready')
