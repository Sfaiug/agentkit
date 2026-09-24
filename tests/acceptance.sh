#!/usr/bin/env bash
# Shared accounting for the live gates; safe to source in offline fixtures.
# A gate is not a job: this marker outranks whatever webhook the environment names, so no
# check, and nothing a check starts, can post to the user's Discord.  A check that needs a
# delivered POST points it at a local recorder of its own.  Every notification the marker had
# to divert away from a configured webhook is written to the log below, and `finish` fails the
# gate on it: a test that aimed at the user is a failure, not a warning nobody reads.
: "${AK_NOTIFY_SINK:=dry-run}"
: "${AK_NOTIFY_SINK_LOG:=${WORK:-${TMPDIR:-/tmp}}/notify-diversions.log}"
export AK_NOTIFY_SINK AK_NOTIFY_SINK_LOG
NPASS=0 NFAIL=0 NSKIP=0 NMETER=0 NHOST=0
ok() { printf 'PASS  %s\n' "$*"; NPASS=$((NPASS + 1)); }
no() { printf 'FAIL  %s\n' "$*"; NFAIL=$((NFAIL + 1)); }
# A live provider meter that answers 429, 5xx or nothing at all is the provider
# throttling the host's probes, not the checkout under test: the check skips, and the
# gate counts that skip as a pass rather than as coverage that was not exercised.
# A harness, login, Discord secret or optional service (a user systemd manager, the shared
# browser) this host does not have is the same: the host's choice, not the checkout's.  A
# gate still needs one harness with its login and says so; the rest skip by name, "not on
# this host", and pass.
skip() {
  case "$*" in
    *"provider meter unavailable"*)
      printf 'SKIP  %s\n' "$*"; NPASS=$((NPASS + 1)); NMETER=$((NMETER + 1)) ;;
    *"not on this host"*)
      printf 'SKIP  %s\n' "$*"; NPASS=$((NPASS + 1)); NHOST=$((NHOST + 1)) ;;
    *)
      printf 'SKIP  %s\n' "$*"; NSKIP=$((NSKIP + 1)) ;;
  esac
}
skip_checks() {
  local labels=$1 label; shift
  for label in ${labels//\// }; do skip "$label: $*"; done
}
meter_unavailable() {   # meter_unavailable <usage.json> <provider...>: the first matching error, or 1
  # Only the named providers' errors count: a bystander's timed-out probe beside the
  # meters the calling check asserts on is not a licence to skip that check.
  local file=$1 provider errors
  shift
  for provider in "$@"; do
    errors=$(jq -r --arg p "$provider" '.providers[$p].error // empty' "$file" \
      2>/dev/null) || return 1
    grep -m1 -E 'HTTP (429|5[0-9][0-9]|000)|timed out' <<<"$errors" && return 0
  done
  return 1
}
diagnose() {   # diagnose <exit> <log> <command...>
  local rc=$1 log=$2; shift 2
  printf '      command='; printf '%q ' "$@"
  printf '\n      exit=%s log=%s\n' "$rc" "$log"
  if [ -f "$log" ]; then tail -20 -- "$log" | sed 's/^/      /'; fi
}
checked() {   # checked <log> <command...>; preserve the failing command's exit
  local log=$1 rc; shift
  "$@" >"$log" 2>&1; rc=$?
  [ "$rc" = 0 ] || diagnose "$rc" "$log" "$@"
  return "$rc"
}
finish() {
  echo "----"
  if [ -s "${AK_NOTIFY_SINK_LOG:-/nonexistent}" ]; then
    no "a notification was aimed at the configured webhook while the test sink was set"
    sed 's/^/      /' "$AK_NOTIFY_SINK_LOG"
  fi
  echo "$NPASS passed, $NFAIL failed, $NSKIP skipped"
  local meter=""
  if [ "$NMETER" = 1 ]; then
    meter="; 1 provider-meter skip counted as passed"
  elif [ "$NMETER" != 0 ]; then
    meter="; $NMETER provider-meter skips counted as passed"
  fi
  if [ "$NHOST" = 1 ]; then
    meter="$meter; 1 skip for what this host lacks counted as passed"
  elif [ "$NHOST" != 0 ]; then
    meter="$meter; $NHOST skips for what this host lacks counted as passed"
  fi
  if [ "$NFAIL" != 0 ]; then
    echo "acceptance: FAILED$meter (see $WORK)"
    return 1
  fi
  if [ "$NSKIP" != 0 ]; then
    echo "acceptance: INCOMPLETE; skipped coverage was not exercised$meter (see $WORK)"
    [ "${AGENTKIT_ACCEPTANCE_REQUIRED:-0}" != 1 ] || return 2
  else
    echo "acceptance: all checks exercised and passed$meter (see $WORK)"
  fi
}
