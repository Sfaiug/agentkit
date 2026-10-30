#!/bin/bash
# What a machine is, a `name value` line each, for agentkit/machines.py, which runs it here or
# over ssh as `bash -c <this>`. It only reads. Linux and macOS, whose bash is 3.2: no GNU-only.
battery=0 power=1
if [ "$(uname -s)" = Darwin ]; then
  echo "system macOS"
  echo "cores $(sysctl -n hw.ncpu)"
  memory=$(( $(sysctl -n hw.memsize) / 1048576 ))
  echo "memory_mb $memory"
  echo "free_mb $(memory_pressure -Q | awk -F': *' -v total="$memory" \
    '/free percentage/ {print int(total * ($2 + 0) / 100)}')"
  echo "load $(sysctl -n vm.loadavg | awk '{print $2}')"
  supply=$(pmset -g batt)
  case $supply in *InternalBattery*) battery=1 ;; esac
  case $supply in *"'Battery Power'"*) power=0 ;; esac
else
  echo "system $(uname -s)"
  echo "cores $(getconf _NPROCESSORS_ONLN)"
  awk '$1 == "MemTotal:" {print "memory_mb", int($2 / 1024)}
       $1 == "MemAvailable:" {print "free_mb", int($2 / 1024)}' /proc/meminfo
  echo "load $(cut -d ' ' -f 1 /proc/loadavg)"
  # A mouse's battery is the mouse's (scope Device). On power: a charger says it is online;
  # where none says either way, the battery charges or is full.
  power= status=
  for supply in /sys/class/power_supply/*; do
    [ "$(cat "$supply/scope" 2>/dev/null)" != Device ] || continue
    case $(cat "$supply/type" 2>/dev/null) in
      Battery) battery=1 status=$(cat "$supply/status" 2>/dev/null) ;;
      *) [ ! -r "$supply/online" ] || [ "$power" = 1 ] || power=$(cat "$supply/online") ;;
    esac
  done
  case $power$status in [01]*) ;; Charging|Full|"Not charging"|"") power=1 ;; *) power=0 ;; esac
fi
echo "processor $(uname -m)"
echo "disk_free_mb $(df -Pk "$HOME" | awk 'NR == 2 {print int($4 / 1024)}')"
echo "battery $battery"
echo "power $power"
