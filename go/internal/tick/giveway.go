package tick

import (
	"cmp"
	"errors"
	"fmt"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// giveWay is the seat headroom row, Python's run.give_way: it holds the runs under what ak's
// slice's ceilings leave the seats, its memory and its tasks. No ceiling sets nothing.
func (t *ticking) giveWay() error {
	if err := t.giveWayMemory(); err != nil {
		return err
	}
	return t.giveWayTasks()
}

// giveWayMemory sets the runs slice's MemoryHigh to the ceiling less the seats and a margin. At
// the slice's MemoryMax every allocation in it reclaims first, so a seat waited 29 s to draw a
// scroll behind the runs' memory (27 Oct 2026). The margin is what the seats grew by since the
// last tick, a twentieth of the ceiling at least: MemoryHigh is a throttle, and runs overshoot it
// by what they allocate before reclaim catches up. Never under one run's cap, so an admitted run
// can always finish.
func (t *ticking) giveWayMemory() error {
	ceiling, seats, ok := host.SliceMemory()
	if !ok {
		return nil
	}
	grown := 0
	if before, ok := t.state.Num("seats_mb"); ok {
		grown = seats - int(before)
	}
	t.state.Set("seats_mb", seats)
	runCap, err := run.MemoryCapMB(ceiling)
	if err != nil {
		return err
	}
	return t.setOnRuns("MemoryHigh", fmt.Sprintf("%dM", max(runCap, ceiling-seats-max(ceiling/20, grown))))
}

// giveWayTasks holds the runs' task cap so the other children of the slice keep half again the
// most they have used, never under a third of the ceiling: cgroups have ceilings and no
// reservations, and four harnesses died mid-turn when a seat was refused a fork (30 Oct 2026). The
// kernel's peak only rises, so the cap needs no state of ours; an owner's lower number in the
// drop-in stands, and a daemon-reload that puts the drop-in's back is set again next tick.
func (t *ticking) giveWayTasks() error {
	ceiling, ok := host.SliceTasks()
	if !ok {
		return nil
	}
	dropIn, held, holds := host.RunsTasks()
	cap := min(cmp.Or(dropIn, ceiling), max(ceiling/3, ceiling-host.OthersTasksPeak()*3/2))
	if holds && cap == held {
		return nil
	}
	return t.setOnRuns("TasksMax", fmt.Sprint(cap))
}

// setOnRuns sets one property of the runs slice for this boot only: a refusal is one WARN line,
// and the next tick sets it again.
func (t *ticking) setOnRuns(name, value string) error {
	code, err := host.SetOnRuns(name + "=" + value)
	switch {
	case errors.Is(err, host.ErrNoAnswer):
		t.log.line(fmt.Sprintf("WARN the runs slice's %s was not set: systemctl did not answer", name))
	case err != nil:
		return err
	case code != 0:
		t.log.line(fmt.Sprintf("WARN the runs slice's %s was not set: systemctl exited %d", name, code))
	}
	return nil
}
