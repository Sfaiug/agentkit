package seat

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// revivalLines recognizes only the continuation this pass owns. Other deliveries, and a
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
			line.Str("line") != QuestionContinue && line.Str("line") != QuestionContinue+freshContinue {
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
	return notify.Held(context.Background(), name, func(current string) error {
		path := seatFile(current)
		return put(path, filepath.Join(filepath.Dir(path), "seat-"+current+".lock"), run.Line, true, func(file *run.Object) bool {
			id := make([]byte, 8)
			rand.Read(id)
			lines := append(file.List("owed_lines"), run.Fields("line", line, "id", hex.EncodeToString(id)))
			return set([]field{{"owed_lines", lines}}, field{"session", current})(file)
		})
	})
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
	typed := typeAtPrompt(name, owed.Str("line"), func(mark *run.Object) error {
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

// TypeAtPrompt is the ordinary confirmed send; a delivery that owns a durable line also
// checks its identity under the typing lock before any key goes in.
func TypeAtPrompt(name, line string, receipt func(mark *run.Object) error, log func(string)) bool {
	return typeAtPrompt(name, line, receipt, log, func(string) bool { return false })
}
