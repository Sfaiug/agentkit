package host

import (
	"context"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/tmux"
)

// Which seat goes first (Python's front.once): seats share their slice's CPU, so within it the
// seats a client is attached to, and the unit holding the tmux server, go ahead of the others.

const (
	cpuWeightMax = 10000 // the kernel's top cpu.weight
	behind       = 100   // what systemd gives a unit nobody set
)

// seatScope is a seat's scope, which keeps the name its seat launched under (orch.seat_command).
var seatScope = regexp.MustCompile(`^agentkit-seat-(.+)-[0-9a-f]{8}\.scope$`)

// Front sets each weight under the seats' slice that does not read what it should. systemd sets
// it, not the file: a value written straight into the cgroup is dropped by a later reload. Each is
// read just before it is decided, since the first set turns the controller on for the rest. No
// tmux server, no slice or a systemctl that cannot be asked is nothing to do: a weight left wrong
// is set by the next tick. One attach starts two passes at once, from two of its hooks, so a pass
// reads and sets under one lock: whoever sets last has read last (front.once).
func Front() {
	if config.EnsureDirs() != nil {
		return
	}
	held, err := lock.Wait(context.Background(), filepath.Join(config.Home(), "state", "front.lock"))
	if err != nil {
		return
	}
	defer held.Close()
	out, err := tmux.Ask(tmux.Own(), "list-sessions", "-F", "#{session_attached}\t#{pid}\t#{session_name}")
	if err != nil {
		return
	}
	attached, pid := map[string]bool{}, 0
	for _, line := range strings.Split(out, "\n") {
		if row := strings.SplitN(line, "\t", 3); len(row) == 3 {
			attached[row[2]] = row[0] != "0"
			if pid == 0 {
				pid, _ = strconv.Atoi(row[1])
			}
		}
	}
	relative, _ := processCgroup(pid)
	server := relative[strings.LastIndexByte(relative, '/')+1:]
	seats := seatsCgroup()
	entries, err := os.ReadDir(seats)
	if err != nil {
		return
	}
	for _, entry := range entries {
		name := entry.Name()
		launched := seatScope.FindStringSubmatch(name)
		if !entry.IsDir() || name != server && launched == nil {
			continue
		}
		first := name == server
		if !first {
			// a renamed seat is followed to its session; a chain that cannot be followed has no client
			now, _, err := config.ResolveSession(launched[1])
			first = err == nil && attached[now]
		}
		weight := behind
		if first {
			weight = cpuWeightMax
		}
		if now, ok := number(filepath.Join(seats, name, "cpu.weight")); ok && now == float64(weight) {
			continue
		}
		if _, err := setProperty(name, "CPUWeight="+strconv.Itoa(weight)); err != nil {
			return // the rest would fare the same
		}
	}
}

// seatsCgroup is the seats' slice under ak's (orch.seat_slice_name).
func seatsCgroup() string {
	name := tmux.Own() + ".slice"
	if tmux.Own() == "agentkit" {
		name = "agentkit-seats.slice"
	}
	return filepath.Join(sliceCgroup(), name)
}
