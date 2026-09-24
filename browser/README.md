# Shared browser bootstrap

On a Linux server with systemd and Tailscale connected, run `bash install.sh --server`
from the repository root. `bash browser/install.sh` installs just the shared stack.
The installer derives the service account and home from the current Unix account and
binds noVNC to the IPv4 returned by `tailscale ip -4`, validated against `100.64.0.0/10`.
CDP and VNC always listen on `127.0.0.1`; Xvfb disables TCP.
Fresh installs require passwordless sudo and check it before writing files or downloading
dependencies. An existing healthy stack needs no sudo for its read-only checks.

The default CDP, VNC and noVNC ports are 9222, 5900 and 6080. Set
`BROWSER_BRIDGE_CDP_PORT`, `BROWSER_BRIDGE_VNC_PORT`, and `BROWSER_BRIDGE_NOVNC_PORT`
to choose distinct unprivileged ports on initial installation. These are saved in
`~/.local/share/browser-bridge/runtime.json` and used by the browser helpers.
The `ak browser` CLI and MCP registration currently use CDP 9222; keep that default
when using those clients, or configure the clients' endpoint separately.

Existing units and browser sessions are preserved during bootstrap, including partial
installs and units with drop-ins. A matching owner's rerun installs missing browser
packages, including ImageMagick for the desktop tool, and checks that the units are
running. Stopped units are reported without restarting the browser. A different owner
or host produces a warning and skips only the browser step. Value differences identify
the systemd key and its expected value. Review those values
before maintaining the installed units. If an installed stack has only the VNC rfbauth
file remaining, bootstrap preserves authentication and continues package repair and unit
checks; run `ak browser login` as its owner to generate a new password. When
no units are installed, the bootstrap generates new credentials and installs the
stack so that login can work. Existing plaintext passwords under either supported
name are preserved.

The normal installer continues with MCP registration, the removal of any doctrine link an
older install left, harness settings, secrets, cron, tmux options, and phone keys after a
skipped browser step.
