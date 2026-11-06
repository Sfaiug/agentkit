package agent

import (
	"sync"
	"time"
)

// How long one `ps` answers every ask in this process (orch.processes): `every` at least, as a
// screen's draw asks for every seat and one table answers them all, and long enough that reading
// it spends at most `share` of a core, `ceiling` at most: with hundreds of processes one `ps`
// took a fifth of a second, and an open screen reads again every few seconds.  Python holds it
// past `every` only in a screen's pass; Go has none, and a command that is no screen asks once
// and is gone.
const (
	every   = 10 * time.Second
	share   = 0.005
	ceiling = time.Minute // open_runs.CEILING: how stale a row may be, whatever the machine
)

var reading struct {
	sync.Mutex
	at       time.Time // when the last reading ended; zero before the first
	took     time.Duration
	commands map[int][]string
	children map[int][]int
}

// processes is readProcesses's last reading, read again once held past its time; a failed reading
// is held too.  Only read what it returns: every asker shares it.
func processes() (map[int][]string, map[int][]int) {
	reading.Lock()
	defer reading.Unlock()
	if reading.at.IsZero() || time.Since(reading.at) >= max(every, min(ceiling, time.Duration(float64(reading.took)/share))) {
		began := time.Now()
		reading.commands, reading.children = readProcesses()
		reading.at = time.Now()
		reading.took = reading.at.Sub(began)
	}
	return reading.commands, reading.children
}
