#!/usr/bin/env bash
# agentkit installer: one command from a fresh machine to ready, on macOS or Linux.  Idempotent:
# every step checks first, and a second run changes nothing.
#   ./install.sh                        client when the saved server is elsewhere; server otherwise
#   ./install.sh --server               this machine holds the sessions and runs the `ak watch` cron
#   ./install.sh --client [ALIAS]       this machine reaches the server over `ssh ALIAS` (default agentkit)
#   ./install.sh --phone-key KEY|FILE   append the phone's public key with the `ak attach` forced command
# A fresh Mac needs --client: without a saved server record, every host defaults to server.
# --link-doctrine and --vm are accepted for old callers and do nothing: the VM steps are
# part of every run, and the rulebook reaches a session at launch instead of being linked.
# Under a HOME that is not the account's own -- the smoke suite's throwaway HOME -- nothing
# outside that HOME is touched: no packages, no harness installs or logins, no crontab.
set -euo pipefail
# Existing harnesses stay frozen even when this installer is run without a shell rc.
export DISABLE_AUTOUPDATER=1 MUSE_NO_AUTO_UPDATE=1 MUSE_LAUNCHER_INSTALL=0
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
AK="$HOME/.agentkit"
BIN="$HOME/.local/bin"
NPM_PREFIX="$HOME/.npm-global"
SERVER_NAME=agentkit
ROLE="" ALIAS="" PHONE_KEY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --server) ROLE=server ;;
    --client) ROLE=client; if [ $# -gt 1 ] && [ "${2#-}" = "$2" ]; then ALIAS=$2; shift; fi ;;
    --phone-key) [ $# -gt 1 ] || { echo "install.sh: --phone-key needs a public key or a file" >&2; exit 2; }
                 PHONE_KEY=$2; shift ;;
    --link-doctrine|--vm) ;;
    *) echo "install.sh: unknown option $1 (expected --server, --client [ALIAS], --phone-key KEY|FILE)" >&2; exit 2 ;;
  esac
  shift
done
OS=$(uname -s)
TTY=0; if [ -t 0 ] && [ -t 1 ]; then TTY=1; fi
have() { command -v "$1" >/dev/null 2>&1; }
note() { echo "note: $*" >&2; }
# ak reads config.toml with tomllib, so the python3 on PATH has to be 3.11 or newer
py_ok() { have python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }
# When the python3 on PATH is older, point $BIN/python3 -- first on PATH -- at a newer one.
pick_python() {
  py_ok && return 0
  local cand
  for cand in python3.14 python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    cand=$(command -v "$cand" 2>/dev/null) || continue
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      ln -sfn -- "$cand" "$BIN/python3"
      hash -r      # bash remembered the old python3; everything below has to find this one
      echo "python3: $BIN/python3 -> $cand (the python3 that was on PATH is older than 3.11)"
      return 0
    fi
  done
  return 1
}

# A HOME that is not the account's own is a sandbox, and nothing outside it may change.
account_home() { eval printf '%s' "~$(id -un 2>/dev/null || printf '%s' "${USER:-}")"; }
SANDBOX=0
if [ -n "$(account_home 2>/dev/null)" ] &&
   [ "$(cd -- "$HOME" 2>/dev/null && pwd -P)" != "$(cd -- "$(account_home)" 2>/dev/null && pwd -P)" ]; then
  SANDBOX=1
fi

# Decide before installing anything: a saved server elsewhere makes this a client. A record
# naming this host still means server, and a fresh box with no record defaults to a full server.
# Explicit --server/--client flags override detection.
is_server_box() {
  local server=${1:-$SERVER_NAME}
  [ "$(hostname -s 2>/dev/null || hostname)" = "$server" ] && return 0
  # --peers=false: only this node's own entry, so a peer of that name never makes this box the server
  have tailscale && tailscale status --peers=false --json 2>/dev/null |
    grep -o '"HostName":[[:space:]]*"[^"]*"' | cut -d '"' -f 4 | grep -Fxq -- "$server"
}
if [ -z "$ROLE" ]; then
  [ ! -s "$AK/state/server" ] || ALIAS=$(head -n 1 -- "$AK/state/server")
  if [ -z "$ALIAS" ] || is_server_box "$ALIAS"; then
    ROLE=server
  else
    ROLE=client
  fi
fi
[ "$ROLE" = client ] && [ -z "$ALIAS" ] && ALIAS=$SERVER_NAME
MODE=server
[ "$ROLE" != client ] || MODE="client of $ALIAS"
echo "install mode: $MODE"
[ "$SANDBOX" = 1 ] && echo "sandbox HOME $HOME: packages, harness installs and logins, and the cron are skipped"

# --- (1) state dirs, ak on PATH ---------------------------------------------
umask 077
dirs=("$AK" "$AK/state" "$AK/secrets" "$AK/tmp" "$AK/env")
if [ "$ROLE" = server ]; then
  dirs+=("$AK/runs" "$AK/wt" "$AK/work")
else
  # These belong to the server's loop. Remove only these paths, without following symlinks;
  # the bridge, server pointer, credentials and other local state must survive a reinstall.
  # A mistaken --client or unavailable Tailscale must not erase the server's unfinished work.
  if is_server_box "$SERVER_NAME"; then
    CLIENT_PRUNE_PENDING="local loop state kept: this host identifies as $SERVER_NAME; inspect it on the server before removing it"
  elif [ -d "$AK/runs" ] && ! python3 - "$AK/runs" <<'PYPRUNE'
import json, pathlib, sys

try:
    for directory in pathlib.Path(sys.argv[1]).iterdir():
        if not directory.is_dir():
            continue
        state = json.loads((directory / "run.json").read_text())
        if (not isinstance(state, dict) or not state.get("finished_at")
                or state.get("state") in ("queued", "running", "interrupted")
                or state.get("recovery_pending")):
            sys.exit(f"client prune: unfinished run {directory.name}")
except (OSError, ValueError) as exc:
    sys.exit(f"client prune: cannot verify local runs: {exc}")
PYPRUNE
  then
    CLIENT_PRUNE_PENDING="local loop state kept: unfinished or unreadable runs; inspect them on the server before removing them"
  else
    rm -rf -- "$AK/runs" "$AK/wt" "$AK/work"
  fi
fi
for d in "${dirs[@]}"; do
  mkdir -p -- "$d"; chmod 700 "$d"
done
# The config lives here, never in the checkout: the shipped default is copied once, when there
# is no config yet, and no later install ever writes over what the owner has edited since.
if [ ! -e "$AK/config.toml" ]; then
  cp -- "$REPO/config.default.toml" "$AK/config.toml"
  chmod 600 "$AK/config.toml"
  echo "wrote $AK/config.toml from config.default.toml; it is yours to edit from here on"
fi
mkdir -p -- "$BIN"
[ "$ROLE" != server ] || mkdir -p -- "$HOME/code"  # where seats open and `ak watch` scans
ln -sfn -- "$REPO/bin/ak" "$BIN/ak"
# ak is the only command; drop the per-subcommand symlinks earlier versions installed here.
for stale in usage worker run notify orch __pycache__; do
  link="$BIN/$stale"
  [ -L "$link" ] || continue
  target=$(readlink -- "$link")
  # ours if it points here, or into a bin/ that still holds ak, or dangles at a dead */bin/<name>
  if [ "$target" = "$REPO/bin/$stale" ] || [ -e "${target%/*}/ak" ] ||
     { [ ! -e "$link" ] && [ "${target%"/bin/$stale"}" != "$target" ]; }; then
    rm -f -- "$link"
    echo "removed stale symlink $link -> $target"
  fi
done
echo "installed: $AK (0700) and $BIN/ak -> $REPO/bin/ak"
# PATH for login and non-login shells.  Debian's ~/.bashrc returns early when the shell is not
# interactive, so `ssh host ak` only sees a line placed above that return -- hence prepend.
path_line="export PATH=\"\$HOME/.local/bin:\$HOME/.npm-global/bin:\$PATH\""
case "$OS" in Darwin) rcs="$HOME/.zshrc $HOME/.zprofile" ;; *) rcs="$HOME/.bashrc $HOME/.profile" ;; esac
for rc in $rcs; do
  [ -e "$rc" ] || : >"$rc"
  grep -qF 'agentkit PATH' -- "$rc" && continue
  tmp=$(mktemp)
  { printf '# agentkit PATH (kept above bashrc non-interactive early return)\n%s\n\n' "$path_line"
    cat -- "$rc"; } >"$tmp"
  cat -- "$tmp" >"$rc" && rm -f -- "$tmp"
  echo "PATH line prepended to $rc"
done
# ~/.opencode/bin and ~/.grok/bin are where their installers put their binaries, off PATH
# by default; without them here a `have` below misses a working install.  They ride last,
# as a fallback: an explicit placement earlier on PATH keeps its precedence.  The adapters
# fall back to their own dirs themselves, so every verb finds the same binary either way.
export PATH="$BIN:$NPM_PREFIX/bin:$PATH:$HOME/.opencode/bin:${GROK_BIN_DIR:-$HOME/.grok/bin}"

# --- (2) packages -----------------------------------------------------------
if [ "$SANDBOX" = 0 ] && [ "$OS" = Darwin ]; then
  if ! have brew; then
    if [ "$TTY" = 1 ]; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null || true)"
    else
      note "no Homebrew and no terminal to install it from; packages skipped"
    fi
  fi
  if have brew; then
    missing=()
    packages=(tmux:tmux mosh:mosh git:git gh:gh jq:jq node:node)
    [ "$ROLE" != client ] || packages=(mosh:mosh git:git)
    for pair in "${packages[@]}"; do
      have "${pair%%:*}" || missing+=("${pair##*:}")
    done
    py_ok || missing+=(python3)     # Apple's python3 is too old for tomllib; brew's is current
    [ ${#missing[@]} -eq 0 ] || brew install "${missing[@]}" || note "brew could not install: ${missing[*]}"
    pick_python || note "python3 here is older than 3.11 and no newer one was found; ak cannot run"
    # the Tailscale app, not the formula: on a Mac the app is what holds the login and the tunnel
    have tailscale || [ -d /Applications/Tailscale.app ] || brew install --cask tailscale ||
      note "tailscale did not install; this machine reaches the server some other way"
  fi
elif [ "$SANDBOX" = 0 ]; then
  if have apt-get; then
    export DEBIAN_FRONTEND=noninteractive
    missing=()
    # python3-pytest is not used by ak itself; tests/smoke.sh, the acceptance gate, runs its
    # generated repo's done-when command with it.  cron is what runs `ak watch` on the server.
    packages=(tmux:tmux mosh:mosh git:git gh:gh jq:jq curl:curl rsync:rsync crontab:cron)
    [ "$ROLE" != client ] || packages=(mosh:mosh git:git ssh:openssh-client curl:curl)
    for pair in "${packages[@]}"; do
      have "${pair%%:*}" || missing+=("${pair##*:}")
    done
    py_ok || missing+=(python3)
    if [ "$ROLE" = server ]; then
      python3 -c 'import pytest' 2>/dev/null || missing+=(python3-pytest)
      dpkg -s unattended-upgrades >/dev/null 2>&1 || missing+=(unattended-upgrades)
    fi
    if [ ${#missing[@]} -gt 0 ]; then
      sudo -E apt-get update -y || note "apt-get update failed"
      for pkg in "${missing[@]}"; do
        sudo -E apt-get install -y "$pkg" || note "no $pkg package here; install it yourself"
      done
    fi
    # a distribution whose python3 is older than 3.11 usually ships a newer one under its own name
    if ! py_ok; then
      for newer in python3.13 python3.12 python3.11; do
        sudo -E apt-get install -y "$newer" && break
      done || true
    fi
    pick_python || note "python3 here is older than 3.11 and no newer one was found; ak cannot run"
    if [ "$ROLE" = server ]; then
      # chromium: how a reviewer looks at a UI change, headlessly
      have chromium || have chromium-browser ||
        sudo -E apt-get install -y chromium || sudo -E apt-get install -y chromium-browser ||
        note "no chromium package here; a reviewer cannot open a page"
      # Security updates apply themselves; nothing else does. A box that upgrades a harness or a
      # toolchain under a running job has changed the thing under test with nobody watching, and
      # a reboot in the middle of a run loses it -- hence Automatic-Reboot off.
      if dpkg -s unattended-upgrades >/dev/null 2>&1 && [ ! -e /etc/apt/apt.conf.d/51agentkit-security-only ]; then
        sudo -E tee /etc/apt/apt.conf.d/51agentkit-security-only >/dev/null <<'UNATTENDED'
// agentkit: security updates only, and never a reboot under a running job
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename},label=Debian-Security";
        "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
        "origin=Ubuntu,archive=${distro_codename}-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
UNATTENDED
        echo "unattended-upgrades: security origins only, no automatic reboot"
      fi
      # `x=$(node -v | sed ...)` would abort the whole script under `set -e` + pipefail on a box
      # with no node, so the version is read through a function that may fail.
      node_major() { have node && node -v | sed 's/^v\([0-9]*\).*/\1/'; }
      nm=$(node_major || true)
      if [ -z "$nm" ] || [ "$nm" -lt 20 ]; then
        # Debian 13 ships node 20 in apt, which is new enough; nodesource is only the fallback
        sudo -E apt-get install -y nodejs npm || true
        nm=$(node_major || true)
      fi
      if [ -z "$nm" ] || [ "$nm" -lt 20 ]; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo -E apt-get install -y nodejs ||
          note "node 20+ did not install; codex needs it"
      fi
    fi
    # Tailscale is how the Mac and the phone reach this box.
    have tailscale || curl -fsSL https://tailscale.com/install.sh | sh ||
      note "tailscale did not install; the Mac and the phone reach this box some other way"
  else
    if [ "$ROLE" = server ]; then
      note "no apt-get here; install tmux mosh git gh jq python3 node chromium yourself"
    else
      note "no apt-get here; install ssh mosh git python3 yourself"
    fi
  fi
  # npm's global prefix under $HOME: `npm i -g` needs no sudo and the bin dir is ours to export
  if [ "$ROLE" = server ] && have npm; then
    mkdir -p -- "$NPM_PREFIX"
    [ "$(npm config get prefix 2>/dev/null)" = "$NPM_PREFIX" ] || npm config set prefix "$NPM_PREFIX" >/dev/null
  fi
fi

# --- (3) the harnesses: each adapter installs and logs its own in ------------
# One provider is enough to finish: on a machine with none of the harnesses installed,
# a terminal run asks once which to install and log in, and only those go in.  With no
# terminal there is nobody to ask, so nothing is installed and each adapter only says
# whether it is logged in and the command that logs it in.  A run on a machine that has
# one keeps what it has: only the harnesses installed are checked and logged in, and none
# is added unasked.  The names offered are the adapters present: grokbuild's binary is
# grok and antigravity's is agy, so those are the names they are offered under, and an
# adapter file that is not there is not offered.
if [ "$ROLE" = server ] && [ "$SANDBOX" = 0 ]; then
  present="" installed=""
  for pair in claude:claude codex:codex muse:muse grok:grokbuild opencode:opencode agy:antigravity; do
    name=${pair%%:*} h=${pair##*:}
    [ -f "$REPO/adapters/$h.sh" ] || continue
    present="$present${present:+ }$name"
    if have "$name"; then installed="$installed${installed:+ }$name"; fi
  done
  chosen=${installed:-$present}
  if [ "$TTY" = 1 ] && [ -z "$installed" ] && [ -n "$present" ]; then
    list=${present// /, }
    read -r -p "Which harness to install and log in ($list, or all)? [all] " answer || answer=""
    answer=$(printf '%s' "$answer" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
    chosen=""
    case "$answer" in
      ""|all) chosen=$present ;;
      *) case " $present " in
           *" $answer "*) chosen=$answer ;;
           *) note "'$answer' is not one of: $list, or all; installing nothing -- run ./install.sh again to choose" ;;
         esac ;;
    esac
  fi
  for name in $chosen; do
    case $name in grok) h=grokbuild ;; agy) h=antigravity ;; *) h=$name ;; esac
    if [ "$TTY" = 1 ]; then
      "$REPO/adapters/$h.sh" install || note "$name did not install; see above"
      "$REPO/adapters/$h.sh" login || note "$name login did not finish; run ./install.sh again to retry"
    else
      "$REPO/adapters/$h.sh" login </dev/null || true    # says whether it is logged in, and how to
    fi
  done
  if have gh && ! gh auth status >/dev/null 2>&1; then
    if [ "$TTY" = 1 ]; then gh auth login || note "gh auth login did not finish"
    else note "gh is not logged in; run \`gh auth login\` so runs can push, open and merge PRs"; fi
  fi
  # What a logged-in gh still leaves for git to fail on later, both of them three model calls
  # into the first run: no credential helper, so the push cannot authenticate, and no author,
  # so `git commit` refuses with the address it guessed from the hostname.  `gh auth login`
  # offers the first as a question; nothing offers the second.
  if have gh && have git && gh auth status >/dev/null 2>&1; then
    if [ -z "$(git config --global --get credential.https://github.com.helper 2>/dev/null || true)" ]; then
      if gh auth setup-git >/dev/null 2>&1; then echo "git: gh is the credential helper for github.com"
      else note "gh auth setup-git failed; a run's \`git push\` may not authenticate"; fi
    fi
    if [ -z "$(git config --global --get user.email 2>/dev/null || true)" ]; then
      gh_login=$(gh api user --jq .login 2>/dev/null || true)
      gh_id=$(gh api user --jq .id 2>/dev/null || true)
      # every write guarded: a git that will not write its own global config -- an unreadable
      # working directory is enough -- must not take the rest of the install down with it
      if [ -n "$gh_login" ] && [ -n "$gh_id" ] &&
         git config --global user.email "$gh_id+$gh_login@users.noreply.github.com"; then
        if [ -z "$(git config --global --get user.name 2>/dev/null || true)" ]; then
          git config --global user.name "$gh_login" || true
        fi
        echo "git: author set to $(git config --global --get user.name 2>/dev/null || true)" \
             "<$(git config --global --get user.email 2>/dev/null || true)>"
      else
        note "no git author here and this run could not set one; a worker's \`git commit\` will refuse until \`git config --global user.email\` is set"
      fi
    fi
  fi
fi
if [ "$SANDBOX" = 0 ]; then
  if have tailscale && ! tailscale status >/dev/null 2>&1; then
    if [ "$TTY" = 1 ] && [ "$OS" != Darwin ]; then sudo tailscale up || note "tailscale up did not finish"
    else note "tailscale is not up; \`sudo tailscale up\` (or the app) joins the tailnet"; fi
  fi
fi

# --- (3b) the shared browser: the stack and MCP servers on the server only ----
# Two halves with two homes.  The stack is the machine's -- apt packages, systemd units, a
# Chromium holding real logins -- so it is stood up on the server only, never under a sandbox
# HOME. The bootstrap checks ownership before touching the machine's shared stack.
# Registration writes this HOME's harness configs, sandbox HOME included on a server.
if [ "$ROLE" = server ] && [ "$SANDBOX" = 0 ]; then
  bash "$REPO/browser/install.sh" || note "browser step did not finish; continuing install; \`ak browser status\` says what is missing"
fi
if [ "$ROLE" = server ] && { have claude || have codex; }; then
  ak browser mcp-register || note "ak browser mcp-register did not finish; the harnesses have no browser tool"
fi

# --- (4) the rulebook: agentkit's sessions only, never the user's own files ---
# The rules an agentkit session is opened with are `orchestrator.md` here, handed to that one
# session by its adapter at launch, so nothing is installed into ~/.claude or ~/.codex and
# every other Claude Code and Codex the user runs is their own again.  What an older install
# linked is undone: a symlink of ours goes, and the file it displaced -- the newest
# `<file>.bak-YYYYMMDD` beside it -- comes back.  A real file that is not our link is not ours
# to touch, whatever it says.
REPO_REAL=$(cd -- "$REPO" && pwd -P)
for target in "$HOME/.codex/AGENTS.md" "$HOME/.claude/CLAUDE.md"; do
  [ -L "$target" ] || continue
  # where the link really points: a relative destination names this checkout just as well as
  # an absolute one, so it is resolved against the link's own directory before it is judged.
  # A link we cannot resolve -- into a checkout that is gone -- is left alone rather than
  # guessed at; nothing here removes a link it has not proved is ours.
  link=$(readlink -- "$target")
  case $link in /*) dest=$link ;; *) dest="${target%/*}/$link" ;; esac
  dir=$(cd -- "${dest%/*}" 2>/dev/null && pwd -P) || dir=""
  [ -n "$dir" ] || continue
  case "$dir/" in "$REPO_REAL"/*) ;; *) continue ;; esac
  rm -f -- "$target" || continue
  echo "unlinked $target; agentkit's rules now reach its own sessions only"
  # The newest backup by name, not by mtime: `cp -p` gave it the mtime of the file it holds,
  # so the newest copy need not be the newest file.  A glob and no `ls`: with nothing to match,
  # `ls` fails, and under this installer's `set -e` that would end the install here -- with the
  # first link removed and the second one still standing.
  backup=""
  for candidate in "$target".bak-[0-9]*; do
    if [ -f "$candidate" ]; then backup=$candidate; fi
  done
  if [ -n "$backup" ]; then
    mv -- "$backup" "$target"
    echo "restored $target from $backup"
  fi
done

# --- yolo defaults: every harness on the server, no per-run flag ------------
# Runs on a plain install too, and last, because on a fresh --vm box python3 only exists once
# the block above has installed it. Idempotent: nothing here rewrites a file it already agrees
# with. The adapters keep passing their own bypass flags; this is for the interactive seat and
# for anything the user starts by hand.
ystamp=$(date +%Y%m%d)
PY3=$(command -v python3 || true)
[ "$ROLE" != server ] || [ -n "$PY3" ] || echo "note: no python3; skipping the ~/.claude and ~/.codex yolo defaults" >&2

# (a) Claude Code: merge into settings.json, never rewrite it wholesale
if [ "$ROLE" = server ] && [ -n "$PY3" ]; then
  mkdir -p -- "$HOME/.claude"
  if ! "$PY3" - "$HOME/.claude/settings.json" "$ystamp" <<'PY'
import json, os, pathlib, shutil, sys

path, stamp = pathlib.Path(sys.argv[1]), sys.argv[2]
try:
    raw = path.read_text()
except FileNotFoundError:
    raw, data = None, {}
except OSError as exc:
    sys.exit(f"cannot read {path}: {exc}")
else:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        # a malformed file is not a missing one: replacing it would drop the user's settings
        sys.exit(f"{path} is not valid JSON ({exc}); left alone")
    if not isinstance(data, dict):
        sys.exit(f"{path} is not a JSON object; left alone")
perms = data.get("permissions")
perms = dict(perms) if isinstance(perms, dict) else {}
env = data.get("env")
env = dict(env) if isinstance(env, dict) else {}
# The hooks themselves are the adapter's -- `adapters/<h>.sh hooks`, called for every harness
# below -- so nothing here writes hook JSON.
if (perms.get("defaultMode") == "bypassPermissions"
        and data.get("skipDangerousModePermissionPrompt") is True
        and env.get("DISABLE_AUTOUPDATER") == "1"):
    print(f"yolo: {path} already bypassPermissions, autoupdater pinned")
    raise SystemExit(0)
if raw is not None:                     # back up only when something actually changes
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    print(f"backed up {path} -> {backup}")
perms["defaultMode"] = "bypassPermissions"
data["permissions"] = perms
data["skipDangerousModePermissionPrompt"] = True
# `ak update` is the only way a harness moves: an autoupdate mid-run changes the thing under
# test between one round and the next, and nothing would say so
env["DISABLE_AUTOUPDATER"] = "1"
data["env"] = env
tmp = path.with_name(f"{path.name}.ak-tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
os.replace(tmp, path)
print(f"yolo: {path} permissions.defaultMode=bypassPermissions, "
      "skipDangerousModePermissionPrompt=true, env.DISABLE_AUTOUPDATER=1")
PY
  then
    echo "note: ~/.claude/settings.json left unchanged; set permissions.defaultMode yourself" >&2
  fi
fi

# (a2) and its lifecycle hooks, which are the adapter's own: every harness is asked to wire or
# refresh its own, idempotently, and one with none says so and writes nothing.  This is what
# makes a seat's row say whether it is working, asking or waiting for the user.
if [ "$ROLE" = server ]; then
  for h in claude codex muse grokbuild opencode antigravity; do
    "$REPO/adapters/$h.sh" hooks || note "$h hooks were not wired; that seat falls back to its screen rules"
  done
fi

# (b) Codex: approval_policy, sandbox_mode and no startup update prompt (versions are pinned), top level, other content untouched
if [ "$ROLE" = server ] && [ -n "$PY3" ]; then
  mkdir -p -- "$HOME/.codex"
  if ! "$PY3" - "$HOME/.codex/config.toml" <<'PY'
import os, pathlib, sys

path = pathlib.Path(sys.argv[1])
want = {"approval_policy": '"never"', "sandbox_mode": '"danger-full-access"', "check_for_update_on_startup": "false"}


def trailing_comment(value):
    """The `# ...` a TOML value line ends with, with the spacing before it, or ''.

    Rewriting a key must not throw away what the user wrote next to it, and a `#` inside the
    value is part of the value, not the start of a comment -- so quoting is tracked.
    """
    quote = None
    for i, ch in enumerate(value):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            head = value[:i]
            return (head[len(head.rstrip()):] or "  ") + value[i:].rstrip("\n")
    return ""


try:
    lines = path.read_text().splitlines(keepends=True)
except FileNotFoundError:
    lines = []
except OSError as exc:
    sys.exit(f"cannot read {path}: {exc}")

# Only the region above the first [table] header is top level, and that is the only region a
# bare key may live in; `anchor` is where a missing key goes -- after the key we replaced,
# else after model_reasoning_effort, else at the very top.
out, seen, anchor, changed, toplevel = [], set(), None, False, True
for line in lines:
    stripped = line.lstrip()
    if toplevel and stripped.startswith("["):
        toplevel = False
    key = stripped.split("=", 1)[0].strip().strip("\"'") if "=" in stripped else ""
    if toplevel and key in want:
        replacement = f"{key} = {want[key]}{trailing_comment(stripped.split('=', 1)[1])}\n"
        changed = changed or line != replacement
        out.append(replacement)
        seen.add(key)
        anchor = len(out)
        continue
    if toplevel and key == "model_reasoning_effort":
        anchor = len(out) + 1
    out.append(line)
missing = [f"{k} = {v}\n" for k, v in want.items() if k not in seen]
if missing:
    at = anchor if anchor is not None else 0
    # only a file's last line can lack its newline, and appending straight after one would
    # glue the new key onto it -- `model_reasoning_effort = "xhigh"approval_policy = "never"`
    if at > 0 and not out[at - 1].endswith("\n"):
        out[at - 1] += "\n"
    out[at:at] = missing
    changed = True
if not changed:
    print(f"yolo: {path} already approval_policy=never, sandbox_mode=danger-full-access")
    raise SystemExit(0)
tmp = path.with_name(f"{path.name}.ak-tmp")
tmp.write_text("".join(out))
os.replace(tmp, path)
print(f"yolo: {path} approval_policy=never, sandbox_mode=danger-full-access")
PY
  then
    echo "note: ~/.codex/config.toml left unchanged; set approval_policy yourself" >&2
  fi
fi

# (c) Muse Code has no config-level yolo, verified against muse 1.0.2: approval mode's only
# sources are the startup flags, a session replay and an in-session reconfigure;
# --trust-workspace says outright that it does not save trust; and the settings surface
# (~/.config/muse/settings.json) has no approval, sandbox or trust key. The adapter's own
# --yolo is the whole story -- see docs/guide.md.
[ "$ROLE" != server ] || echo "yolo: muse has no config-level yolo (muse 1.0.2); the adapter's --yolo covers it"
# Muse's launcher checks its channel hourly and replaces the binary in the background unless
# MUSE_NO_AUTO_UPDATE=1 is in the environment. The adapter sets it for headless runs and in
# the command it emits for interactive/detached seats; update.py sets it for version checks.
# The shell export below also covers manual commands. Codex is an npm package and never moves
# on its own.

# (d) Shell aliases, in one block this script owns
case "$(uname -s)" in
  Darwin) rc="$HOME/.zshrc" ;;
  *)      rc="$HOME/.bashrc" ;;
esac
[ -e "$rc" ] || : >"$rc"
tmp=$(mktemp)
# Drop our previous block wherever it sat, plus any older `alias orch=` the block would
# duplicate.  A block whose end marker someone deleted is not ours to swallow: everything after
# the stray start marker is buffered and put back, and only the marker itself is dropped, so the
# next run sees a file with no stray marker left in it.
awk '
  /^# agentkit aliases$/ && !skip     { skip = 1; buf = ""; next }
  skip && /^# end agentkit aliases$/  { skip = 0; buf = ""; next }
  skip                                { buf = buf $0 ORS; next }
  /^[[:space:]]*alias orch=/          { next }
                                      { print }
  END                                 { printf "%s", buf }
' "$rc" >"$tmp"     # no --: BSD awk has no end-of-options marker, and $rc is absolute
cat >>"$tmp" <<'ALIASES'
# agentkit aliases
export MUSE_NO_AUTO_UPDATE=1   # muse updates itself hourly otherwise; `ak update` owns that
alias orch='ak orch'
ALIASES
if [ "$OS" = Darwin ]; then
  printf '%s\n' '[[ -o interactive ]] && command -v ak >/dev/null 2>&1 && { ak macbridge --reader >/dev/null 2>&1 &! }' >>"$tmp"
fi
printf '%s\n' '# end agentkit aliases' >>"$tmp"
if cmp -s -- "$tmp" "$rc"; then
  rm -f -- "$tmp"
  echo "yolo: $rc aliases already current"
else
  cat -- "$tmp" >"$rc" && rm -f -- "$tmp"   # cat, not mv: keep the rc file's own mode and owner
  echo "yolo: alias orch and MUSE_NO_AUTO_UPDATE=1 written to $rc"
fi

# --- (e) the phone key lands in `ak attach` --------------------------------

# --- (f) secrets: asked for once, when there is someone to ask ----------------
# `claude setup-token` mints a long-lived token, and a worker given one never reads or refreshes
# the seat's own ~/.claude/.credentials.json: the refresh race that logged the whole box out at
# one in the morning cannot happen again.  Asked once, only where there is somebody to ask and
# only while the file is absent; the seat itself keeps its own interactive login, and a box
# without the file falls back to exactly today's behaviour.
claude_worker_token() {
  local file="$AK/secrets/claude_oauth_token" answer
  [ ! -s "$file" ] || return 0            # already minted: setup-token is never run again
  [ "$ROLE" = server ] && [ "$SANDBOX" = 0 ] && [ "$TTY" = 1 ] && have claude || return 0
  echo "claude: minting a worker token so headless turns never share the seat's OAuth pair"
  claude setup-token || note "claude setup-token did not finish"
  read -r -p "Paste the token it printed (Enter to skip): " answer || answer=""
  [ -n "$answer" ] || return 0
  (umask 077; printf '%s\n' "$answer" >"$file") || return 0
  chmod 600 "$file" || true       # umask already made it 0600; a refused chmod is not fatal
  echo "secrets: claude_oauth_token written"
}

claude_worker_token
if [ "$ROLE" = server ] && [ "$TTY" = 1 ]; then
  if [ ! -s "$AK/secrets/discord_webhook" ]; then
    read -r -p "Discord webhook URL for notifications (Enter to skip): " answer
    if [ -n "$answer" ]; then printf '%s\n' "$answer" >"$AK/secrets/discord_webhook"; chmod 600 "$AK/secrets/discord_webhook"; echo "secrets: discord_webhook written"; fi
  fi
  if [ ! -s "$AK/secrets/discord_user_id" ]; then
    read -r -p "Discord user id to @mention (Enter to skip): " answer
    if [ -n "$answer" ]; then printf '%s\n' "$answer" >"$AK/secrets/discord_user_id"; chmod 600 "$AK/secrets/discord_user_id"; echo "secrets: discord_user_id written"; fi
  fi
fi

# --- (g) server or client ---------------------------------------------------
# A client remembers the server's ssh alias, and a bare `ak` runs the menu over there.  The
# server has no alias file. The watcher retries recoverably and pins reviews to their SHA, and
# every tick also nudges the seats that have stalled on their harness's own error -- which is
# why it runs every three minutes and not every ten; install (or restore) its cron on each
# server install.
CRON_TAG="# agentkit watch"
# A reinstall owns the one live line: every crontab line carrying the tag goes first, whether
# it is the live one or a copy somebody commented out to pause the tick by hand. The match is
# the tag with its `#`s and spacing loose, so a retyped or re-commented pause is still ours.
CRON_MATCH='#+[[:space:]]*agentkit[[:space:]]+watch([[:space:]]|$)'
case "$ROLE" in
  client)
    printf '%s\n' "$ALIAS" >"$AK/state/server"
    echo "client: the server is \`ssh $ALIAS\`; \`ak\` runs the menu there" ;;
  server)
    rm -f -- "$AK/state/server"
    if [ "$SANDBOX" = 1 ]; then
      echo "server: sandbox HOME, so the ak watch cron is not installed"
    elif ! have crontab; then
      note "no crontab here; run \`ak watch\` every three minutes some other way"
    else
      cron_line="*/3 * * * * PATH=$BIN:$NPM_PREFIX/bin:/usr/local/bin:/usr/bin:/bin $REPO/bin/ak watch >>$AK/tmp/watch.log 2>&1 $CRON_TAG"
      current=$(crontab -l 2>/dev/null || true)
      wanted=$({ [ -z "$current" ] || printf '%s\n' "$current" | grep -vE -- "$CRON_MATCH" || true
                 printf '%s\n' "$cron_line"; })
      if [ "$current" = "$wanted" ]; then
        echo "server: the ak watch cron is already installed"
      else
        printf '%s\n' "$wanted" | crontab - && echo "server: ak watch runs every three minutes from cron"
      fi
    fi ;;
esac

if py_ok; then
  echo "ready: ak runs on $(python3 --version 2>&1)"
else
  note "ak needs python 3.11 or newer (tomllib); python3 here is $(python3 --version 2>&1 || echo missing)"
fi

# Existing Claude sessions retain the settings they started with. `ak orch list` shows which
# seats predate this install; stopping one remains an explicit, exact-name operation.
[ "$ROLE" != server ] || date +%s >"$AK/state/installed-at"

# --- (g2) the two tmux options the sessions already running want -------------
# `ak orch` writes them into agentkit's own tmux config, which a tmux server reads when it
# starts -- and a server that is already up never will, while the sessions in it are exactly
# the ones that have been open longest.  So they are set on the running servers here too:
# `mouse on`, so that a touch scroll on the phone scrolls the session's output instead of
# sending arrow keys into the harness, and 50000 lines of it to scroll.
#
# On agentkit's own server they are set globally: that server is the toolkit's, and every
# session on it is a seat.  On the default server nothing is set globally -- it is somebody
# else's tmux, and one legacy seat of ours is no reason to change how their own sessions behave
# -- so there the two options are set on the marked seats themselves, one session at a time.
# Both are session options, and both reach the windows a session opens from then on.
#
# Under a sandbox HOME only a server the caller named itself ($AGENTKIT_TMUX_SOCKET, which is how
# the suite gets one of its own) is touched: every other server belongs to the account, not to
# the throwaway home being installed into.
# tmux's own flags come before the subcommand -- `tmux -L agentkit set -g mouse on`, never
# `tmux set -L agentkit -g` -- so the server is named here and the rest is the set-option's.
# A tmux that rejects the command says so and stops the install: an option silently not set is
# what this section exists to fix, and swallowing the error is how it stayed unset.
ak_tmux() {   # ak_tmux <socket or ""> <tmux command...>: "" is the default server
  local socket=$1; shift
  if [ -n "$socket" ]; then env -u TMUX tmux -L "$socket" "$@"; else env -u TMUX tmux "$@"; fi
}
tmux_options() {   # tmux_options <what to call it> <socket or ""> <target...>: -g, or -t <session>
  local where=$1 socket=$2 out option; shift 2
  for option in "mouse on" "history-limit 50000" "remain-on-exit on"; do
    # unquoted on purpose: each option above is its name and its value, two words
    if ! out=$(ak_tmux "$socket" set "$@" $option 2>&1); then
      echo "install.sh: tmux rejected \`set $* $option\` on $where: $out" >&2
      return 1
    fi
  done
  echo "tmux: mouse on, 50000 lines of history, remain-on-exit on $where"
}
if have tmux; then
  AK_SOCKET=${AGENTKIT_TMUX_SOCKET:-agentkit}
  if [ "$ROLE" = server ] && { [ "$SANDBOX" = 0 ] || [ -n "${AGENTKIT_TMUX_SOCKET:-}" ]; } &&
     env -u TMUX tmux -L "$AK_SOCKET" list-sessions >/dev/null 2>&1; then
    tmux_options "the agentkit server ($AK_SOCKET)" "$AK_SOCKET" -g
  fi
  # `#{@ak_orch}` is the mark `ak orch` puts on its own sessions: on the default server it is
  # what tells a legacy seat from the user's own tmux work, which is none of this script's
  if [ "$ROLE" = server ] && [ "$SANDBOX" = 0 ]; then
    # the mark and the name, in that order and with a space between: a session without the mark
    # begins that line with the space, so no name of theirs can be read as a mark of ours
    while IFS= read -r legacy; do
      # a seat that ended between that listing and now is nobody's failure; anything else is
      ak_tmux "" has-session -t "=$legacy" >/dev/null 2>&1 || continue
      tmux_options "the legacy seat $legacy on the default server" "" -t "$legacy"
    done < <(env -u TMUX tmux list-sessions -F '#{@ak_orch} #{session_name}' 2>/dev/null \
               | sed -n 's/^1 //p')
  fi
fi

# --- (g3) the ceiling for everything the toolkit starts ---------------------
# `ak orch` starts its tmux servers inside `agentkit.slice`, and tmux leaves every pane in a
# scope under that slice, so one ceiling there holds every agent process on the machine --
# while the shells and editors the owner starts by hand stay outside it and keep the box
# usable when the herd is at its heaviest.  The ceiling is a drop-in in the user's own unit
# directory: no root, and nothing outside $HOME.  An existing file is the owner's own answer
# and is never rewritten; `systemctl --user set-property agentkit.slice TasksMax=...` changes
# it on a running system, and editing the file makes that survive a reboot.
user_manager() {   # is there a user systemd manager here, to hold a slice and its limits?
  have systemctl || return 1
  # An install run from cron, over ssh without a login shell or from a sudo -u has no session
  # environment, and `systemctl --user` then has no idea where to look: the runtime directory
  # is the uid's own and the bus is the socket inside it.  Exported, because the reload below
  # needs the same answer.
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
  case "$(systemctl --user is-system-running 2>/dev/null)" in
    initializing|starting|running|degraded|maintenance|stopping) return 0 ;;
  esac
  return 1
}
LIMITS="$HOME/.config/systemd/user/agentkit.slice.d/limits.conf"
if [ "$ROLE" != server ]; then
  :   # a client starts no agent here; the ceiling belongs where the seats are
elif [ "$SANDBOX" = 1 ]; then
  echo "slice: sandbox HOME, so the agentkit.slice ceiling is not written"
elif ! user_manager; then
  echo "slice: no user systemd manager here; seats start plainly, as they always did"
else
  WEIGHTS_CHANGED=0
  if [ -e "$LIMITS" ]; then
    echo "slice: $LIMITS is already there; left as it is"
  else
  # Three quarters of the user unit's own task ceiling, so the toolkit can never take the last
  # thread the owner's login needs; a user unit with no ceiling offers no share to take, and a
  # plain number stands in for it.  Memory is 60% and 70% of what this machine has, read off
  # MemTotal and written in mebibytes so the file says what it means; the CPU quota leaves one
  # core to everything else.
  user_tasks=$(systemctl show "user@$(id -u).service" -p TasksMax --value 2>/dev/null || true)
  case "$user_tasks" in ''|*[!0-9]*) slice_tasks=3072 ;; *) slice_tasks=$((user_tasks * 3 / 4)) ;; esac
  mem_kb=$(awk '/^MemTotal:/ { print $2; exit }' "${MEMINFO:-/proc/meminfo}" 2>/dev/null || true)
  # a machine that will not say how much memory it has still gets the same two shares: systemd
  # reads a percentage as a share of the memory it finds
  case "$mem_kb" in ''|*[!0-9]*) mem_high=60% mem_max=70% ;;
    *) mem_high=$((mem_kb * 60 / 100 / 1024))M mem_max=$((mem_kb * 70 / 100 / 1024))M ;; esac
  cpus=$(nproc 2>/dev/null || echo 1)
  case "$cpus" in ''|*[!0-9]*) cpus=1 ;; esac
  quota=$(( (cpus - 1) * 100 )); [ "$quota" -ge 100 ] || quota=100
  mkdir -p -- "${LIMITS%/*}"
  cat >"$LIMITS" <<EOF
# Written by agentkit's install.sh, once: the ceiling for every process the toolkit starts.
# Edit it here, or run \`systemctl --user set-property agentkit.slice TasksMax=...\` for a
# running system.  An installer that finds this file leaves it exactly as it is.
[Slice]
TasksMax=$slice_tasks
MemoryHigh=$mem_high
MemoryMax=$mem_max
CPUQuota=${quota}%
EOF
  systemctl --user daemon-reload 2>/dev/null ||
    note "run \`systemctl --user daemon-reload\` to pick up $LIMITS"
  echo "slice: $LIMITS caps agentkit at $slice_tasks tasks, $mem_max of memory and ${quota}% CPU"
  fi
  # Sessions keep the larger share of a busy host.  These are separate child slices so a
  # leaking detached run cannot consume the session slice's weight.
  for child in agentkit-seats.slice agentkit-runs.slice; do
    weight=100
    [ "$child" = agentkit-runs.slice ] && weight=40
    dropin="$HOME/.config/systemd/user/$child.d/weights.conf"
    if [ ! -e "$dropin" ]; then
      mkdir -p -- "${dropin%/*}"
      cat >"$dropin" <<EOF
# Written by agentkit's install.sh: interactive sessions have priority over detached runs.
[Slice]
CPUWeight=$weight
IOWeight=$weight
EOF
      WEIGHTS_CHANGED=1
    fi
  done
  if [ "$WEIGHTS_CHANGED" = 1 ]; then
    systemctl --user daemon-reload 2>/dev/null ||
      note "run \`systemctl --user daemon-reload\` to pick up the session and run weights"
  fi
fi

# --- (h) a new phone key, appended with the forced command -------------------
# The rest of the phone-key handling below points the existing `phone-termius` line at
# `ak attach`; this adds the line when the key is given and not there yet.
if [ -n "$PHONE_KEY" ]; then
  if [ -f "$PHONE_KEY" ]; then key=$(head -n 1 -- "$PHONE_KEY"); else key=$PHONE_KEY; fi
  set -- $key
  case "${1:-} ${2:-}" in
    ssh-*\ [A-Za-z0-9+/]*|ecdsa-*\ [A-Za-z0-9+/]*|sk-*\ [A-Za-z0-9+/]*) ;;
    *) echo "install.sh: --phone-key does not look like an OpenSSH public key: ${key:0:40}" >&2; exit 2 ;;
  esac
  mkdir -p -- "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
  AUTHKEYS="$HOME/.ssh/authorized_keys"
  [ -e "$AUTHKEYS" ] || : >"$AUTHKEYS"
  if grep -qF -- " $2" "$AUTHKEYS"; then
    echo "ssh: the phone key is already in $AUTHKEYS"
  else
    printf 'command="ak attach",no-agent-forwarding,no-port-forwarding %s %s phone-termius\n' "$1" "$2" >>"$AUTHKEYS"
    echo "ssh: appended the phone key to $AUTHKEYS with the \`ak attach\` forced command"
  fi
  chmod 600 "$AUTHKEYS"
fi

# --- (e) the phone key lands in `ak attach` --------------------------------
# One line in ~/.ssh/authorized_keys is the phone's, tagged `phone-termius`, and its forced
# command is the whole session that key can ever have.  It is pointed at `ak attach`: one seat
# and you are in it, several and you pick.  Only that line is touched -- every other key keeps
# its own options -- and only if it is there at all.
AUTHKEYS="$HOME/.ssh/authorized_keys"
if [ -n "$PY3" ] && [ -f "$AUTHKEYS" ]; then
  if ! "$PY3" - "$AUTHKEYS" "$ystamp" <<'PYKEYS'
import os, pathlib, shutil, sys

path, stamp, forced = pathlib.Path(sys.argv[1]), sys.argv[2], "ak attach"
try:
    lines = path.read_text().splitlines(keepends=True)
except OSError as exc:
    sys.exit(f"cannot read {path}: {exc}")


def rewritten(line):
    """The same key line with its forced command replaced, or None if it cannot be read.

    sshd allows an escaped quote inside `command="..."`, so the closing quote is the first one
    that is not escaped.  A line whose quote never closes is malformed and is left exactly as
    it is: an authorized_keys file this script guessed at is a locked door.
    """
    start = line.find('command="')
    if start < 0:
        return f'command="{forced}",' + line     # a phone key with no forced command yet
    i, end = start + len('command="'), None
    while i < len(line):
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == '"':
            end = i
            break
        i += 1
    if end is None:
        return None
    return line[:start] + f'command="{forced}"' + line[end + 1:]


out, found, changed = [], False, False
for line in lines:
    if "phone-termius" not in line or line.lstrip().startswith("#"):
        out.append(line)
        continue
    found = True
    new = rewritten(line)
    if new is None:
        print(f"note: the phone-termius line in {path} has an unterminated command=; left alone")
        out.append(line)
        continue
    changed = changed or new != line
    out.append(new)
if not found:
    print(f"ssh: no phone-termius key in {path}; nothing to point at `{forced}`")
    raise SystemExit(0)
if not changed:
    print(f"ssh: the phone-termius key already runs `{forced}`")
    raise SystemExit(0)
backup = path.with_name(f"{path.name}.bak-{stamp}")
shutil.copy2(path, backup)
tmp = path.with_name(f"{path.name}.ak-tmp")
tmp.write_text("".join(out))
os.chmod(tmp, 0o600)          # sshd refuses an authorized_keys anyone else can write
os.replace(tmp, path)
print(f"ssh: the phone-termius key now runs `{forced}` ({path} backed up to {backup.name})")
PYKEYS
  then
    echo "note: $AUTHKEYS left unchanged; point the phone key at 'ak attach' yourself" >&2
  fi
fi

# Mac files travel out through ssh to the recorded server; the Mac never needs Remote Login.
if [ "$OS" = Darwin ]; then
  python3 - "$REPO" "$SANDBOX" <<'PYMACBRIDGE'
import sys
sys.path.insert(0, sys.argv[1])
from agentkit.macbridge import install_launch_agent
install_launch_agent(load=sys.argv[2] == "0")
PYMACBRIDGE
fi

# --- (i) what this run could not do, in one place at the end -----------------
# A run with no terminal cannot finish a device-code login or ask for a secret, and a newcomer
# who is told "installed" and nothing else has no way to know that.  So the last thing every
# install prints is the list of what is still missing and the one command that fixes each.
pending=""
add_pending() { pending="$pending  $1"$'\n'; }
[ -z "${CLIENT_PRUNE_PENDING:-}" ] || add_pending "$CLIENT_PRUNE_PENDING"
if [ "$ROLE" = server ] && [ "$SANDBOX" = 0 ]; then
  for h in claude codex muse grokbuild opencode antigravity; do
    # the harness is grokbuild; the binary it installs is grok, and antigravity's is agy
    bin=$h; [ "$h" = grokbuild ] && bin=grok; [ "$h" = antigravity ] && bin=agy
    if ! have "$bin"; then
      add_pending "$bin is not installed -- re-run ./install.sh with a network connection"
    elif ! "$REPO/adapters/$h.sh" login </dev/null >/dev/null 2>&1; then
      # </dev/null on purpose: the adapter only reports when there is no terminal to log in from
      case $h in opencode) how="paste the provider key";; antigravity) how="(open the URL, paste the code)";; *) how="(device code)";; esac
      add_pending "$bin login -- run \`$REPO/adapters/$h.sh login\` in a terminal $how"
    fi
  done
  if have gh && ! gh auth status >/dev/null 2>&1; then
    add_pending "gh login -- \`gh auth login\`, so runs can push, open and merge PRs"
  fi
fi
if [ "$SANDBOX" = 0 ] && have tailscale && ! tailscale status >/dev/null 2>&1; then
  add_pending "tailscale -- \`sudo tailscale up\` (or the app), so the client can reach the server"
fi
if [ "$ROLE" = server ] && [ "$SANDBOX" = 0 ]; then
  if [ ! -s "$AK/secrets/claude_oauth_token" ]; then
    add_pending "claude worker token -- run \`claude setup-token\` in a terminal and write it to $AK/secrets/claude_oauth_token, so a worker never shares the seat's login"
  else
    # A `claude setup-token` token lives exactly one year from its file's date; once that day
    # is a fortnight away the pending list names it, so a reinstall says so without waiting
    # for the warning.
    tok_mtime=$(stat -c %Y "$AK/secrets/claude_oauth_token" 2>/dev/null || stat -f %m "$AK/secrets/claude_oauth_token" 2>/dev/null || echo "")
    case "$tok_mtime" in ''|*[!0-9]*) ;; *)
      tok_exp=$((tok_mtime + 365 * 24 * 3600)); tok_now=$(date +%s)
      tok_when=$(date -d "@$tok_exp" +%Y-%m-%d 2>/dev/null || date -r "$tok_exp" +%Y-%m-%d 2>/dev/null || echo "")
      tok_left=$(((tok_exp - tok_now) / 86400))
      if [ "$tok_now" -ge "$tok_exp" ]; then
        add_pending "claude worker token expired${tok_when:+ $tok_when} -- run \`claude setup-token\` in a terminal and replace $AK/secrets/claude_oauth_token"
      elif [ "$tok_left" -le 14 ]; then
        add_pending "claude worker token expires${tok_when:+ $tok_when} (in $tok_left days) -- run \`claude setup-token\` in a terminal and replace $AK/secrets/claude_oauth_token"
      fi ;;
    esac
  fi
fi
if [ "$ROLE" = server ] && [ ! -s "$AK/secrets/discord_webhook" ]; then
  add_pending "discord webhook -- re-run ./install.sh from a terminal, or write the URL to $AK/secrets/discord_webhook"
fi
if [ "$ROLE" = server ] && [ ! -s "$AK/secrets/discord_user_id" ]; then
  add_pending "discord user id -- re-run ./install.sh from a terminal, or write it to $AK/secrets/discord_user_id"
fi
# Derive the closing mode here too: this section can run after a resumed partial install.
MODE=server
[ "$ROLE" != client ] || MODE="client of $ALIAS"
if [ -n "$pending" ]; then
  printf 'summary: %s; %s thing(s) this install could not do:\n%s' \
    "$MODE" "$(printf '%s' "$pending" | grep -c .)" "$pending"
else
  echo "summary: $MODE; nothing left to do; \`ak\` is the whole interface"
fi
