"""Paths and ports shared by the installed browser helpers and bootstrap."""
import json
import os
from pathlib import Path

ROOT = Path.home() / '.local/share/browser-bridge'
SECRETS = Path.home() / '.agentkit/secrets'
DEFAULT_PORTS = {'cdp_port': 9222, 'vnc_port': 5900, 'novnc_port': 6080}


def settings():
    path = ROOT / 'runtime.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(saved, dict):
        raise ValueError(f'{path}: expected a JSON object of browser ports')
    ports = {}
    for key, default in DEFAULT_PORTS.items():
        name = 'BROWSER_BRIDGE_' + key.upper()
        value = str(os.environ.get(name, saved.get(key, default)))
        if not value.isascii() or not value.isdigit() or not 1024 <= int(value) <= 65535:
            raise ValueError(f'{name}: expected a port from 1024 to 65535, got {value!r}')
        ports[key] = int(value)
    if len(set(ports.values())) != len(ports):
        raise ValueError('CDP, VNC and noVNC ports must be different')
    return ports


def endpoint():
    return f"http://127.0.0.1:{settings()['cdp_port']}"
