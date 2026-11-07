package seat

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/tmux"
)

// Menu reads a frame's seats and runs once, filing projectless records before numbering them:
// read first, so a home Go leaves to Python is left before filing writes into it, and again once
// filing wrote.  Looking and commands that publish a word use the same run interpretation without
// filing.
func Menu(now time.Time) (Home, bool) {
	held, known := screenRuns.Read()
	if !known {
		return Home{}, false
	}
	runs, projects, known := menuRuns(held, now)
	if !known {
		return Home{}, false
	}
	kept := judging(held)
	read := func() (Home, bool) { return reading(now, true, func([]string) judges { return kept }, nil) }
	home, known := read()
	if !known {
		return Home{}, false
	}
	wrote, known := menuProjects(runs, projects)
	if wrote && known {
		home, known = read()
	}
	if !known {
		return Home{}, false
	}
	state := filepath.Join(config.Home(), "state")
	for i := range home.Seats {
		each := &home.Seats[i]
		if !each.looked() {
			continue
		}
		pane, exited := harnessScreen(each.Name)
		found, _ := observed(state, each.Name, each.reader, pane, seconds(now))
		if exited {
			found.stall, found.login = nil, nil
		}
		attached, _ := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+each.Name+":", "#{session_attached}")
		// when one out of usage comes back, and the model it could go on with, are Python's to draw
		if each.decided(state, found, seconds(now), attached != "" && attached != "0") != nil || each.Word == "out of usage" {
			return Home{}, false
		}
	}
	return home, true
}

// Said is what the row opens: a done seat's last done line, else its question or way back in.
func (seat Seat) Said() string {
	if seat.Word == "done" {
		return config.Fold(plan.LastDone(seat.Name))
	}
	return seat.reason
}

// Crew is the same full model names the seat's bar reads from its saved role selection.
func (home Home) Crew(seat Seat) (builds, reviews []string) {
	_, builds, reviews = barSelection(filepath.Join(config.Home(), "state"), seat.Name, home.models)
	return builds, reviews
}

// Tasks is the seat's tasks in flight, furthest behind first, working before waiting at a stage.
func (seat Seat) Tasks() []Task {
	var tasks []Task
	for _, each := range seat.mine {
		if each.view != nil && each.view.task != nil {
			tasks = append(tasks, *each.view.task)
		}
	}
	slices.SortStableFunc(tasks, func(a, b Task) int {
		if a.Stage != b.Stage {
			return a.Stage - b.Stage
		}
		if a.Moving != b.Moving {
			if a.Moving {
				return -1
			}
			return 1
		}
		return 0
	})
	return tasks
}
