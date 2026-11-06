package tick

import (
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/screen"
	"agentkit/internal/seat"
	"agentkit/internal/tmux"
)

// fixedLines are the lines of ak's own a pass types into a seat and the held lines row sends with
// its Enter, wherever one was left in the composer (watch.ACCOUNT_LINE, MIDTURN_LINE, MOVED_LINE,
// ASKED_LINE, CONTINUE_LINE).
var fixedLines = []string{
	"Your turn was cut off when its usage ran out, and there is usage again. Continue that turn and finish it; do not start over.",
	seat.MidturnContinue,
	"This seat moved to you in the middle of a turn. Continue that turn from where the conversation your instructions point you to leaves it; do not start over.",
	seat.QuestionContinue,
	"continue",
}

// holdsNoLine is whether the seat's composer holds none of those lines, nor the one its
// continue_turns mark owes, nor its harness's resume key, alone or among the lines ak typed there
// last that it is all of (watch.finish_own_lines).
func holdsNoLine(live seat.Live) bool {
	lines := slices.Clone(fixedLines)
	if mark := live.File.Dict("midturn"); mark != nil && mark.Str("line") != "" {
		lines = append(lines, mark.Str("line"))
	}
	if resume, _ := config.Section(live.Own, "resume"); resume != nil {
		if key, _ := resume["key"].(string); key != "" {
			lines = append(lines, key)
		}
	}
	return live.Draft == "" || !slices.ContainsFunc(lines, func(line string) bool {
		line = screen.Unspaced(line)
		return live.Draft == line || slices.Contains(live.Typed, line)
	})
}

// noneSetAside is whether ak's editor keeps no text set aside from a seat's pane, which the draft
// return row would ask back (watch.drafts_back, aside_editor.kept); a server that cannot say keeps
// none it could ask back.
func noneSetAside() bool {
	names, err := tmux.Ask(tmux.Own(), "list-buffers", "-F", "#{buffer_name}")
	return err != nil || !slices.ContainsFunc(strings.Split(names, "\n"), func(name string) bool {
		return strings.HasPrefix(name, "ak_aside-")
	})
}
