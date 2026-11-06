package seat

import (
	"context"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// revivalLines recognizes only the continuations this pass owns. Other deliveries, and a
// partially typed continuation whose send has to be resumed, remain Python's at owed lines.
func revivalLines(file *run.Object) bool {
	if file == nil {
		return false
	}
	lines := file.List("owed_lines")
	if len(lines) == 0 {
		return false
	}
	for _, each := range lines {
		line, ok := each.(*run.Object)
		if !ok || line.Str("id") == "" || !only(line, []string{"line", "id", "typed"}) ||
			!slices.ContainsFunc([]string{QuestionContinue, MidturnContinue}, func(owed string) bool {
				return line.Str("line") == owed || line.Str("line") == owed+freshContinue
			}) {
			return false
		}
	}
	return true
}

func revivalStopped(file *run.Object) (bool, bool) {
	if file != nil && !file.Truthy("stopped_at") && !file.Truthy("closed_by_owner") {
		file = file.Copy()
		file.Delete("owed_lines")
	}
	return stopped(file)
}

func oweRevivalLine(name, line string) error {
	return OweLine(name, line)
}

// TellRevivalLines is the tick's owed-lines row: a gone seat takes no keys; every live
// continuation is checked at its own turn, leaving earlier deliveries standing.
func TellRevivalLines(log func(string)) (bool, error) {
	for _, path := range config.SeatFiles() {
		name, _ := sessionFile(filepath.Base(path))
		if carried, err := tellRevivalLine(name, log); err != nil || !carried {
			return carried, err
		}
	}
	return true, nil
}

func tellRevivalLine(name string, log func(string)) (bool, error) {
	file := revivalFile(name)
	if !file.Truthy("owed_lines") || !Watching(name) {
		return true, nil
	}
	if !revivalLines(file) {
		return false, nil
	}
	owed := file.List("owed_lines")[0].(*run.Object)
	if owed.Truthy("typed") {
		return false, nil
	}
	change := func(current string, mark *run.Object, remove bool) error {
		path := seatFile(current)
		return put(path, filepath.Join(filepath.Dir(path), "seat-"+current+".lock"), run.Line, true, func(file *run.Object) bool {
			lines := file.List("owed_lines")
			if len(lines) == 0 || !run.Equal(lines[0], owed) {
				return false
			}
			var left any
			if remove {
				if len(lines) > 1 {
					left = lines[1:]
				}
			} else {
				owed = owed.Copy()
				owed.Set("typed", mark)
				lines[0] = owed
				left = lines
			}
			return set([]field{{"owed_lines", left}}, field{"session", current})(file)
		})
	}
	stale := func(current string) bool {
		lines := revivalFile(current).List("owed_lines")
		return len(lines) == 0 || !run.Equal(lines[0], owed)
	}
	typed := typeAtPrompt(name, owed.Str("line"), nil, func(mark *run.Object) error {
		current, _, err := config.ResolveSession(name)
		if err != nil {
			return err
		}
		return change(current, mark, false)
	}, log, stale)
	if !typed {
		return !owed.Truthy("typed"), nil
	}
	err := notify.Held(context.Background(), name, func(current string) error { return change(current, nil, true) })
	if err == nil {
		log("told " + name + ": " + owed.Str("line"))
	}
	return true, err
}
