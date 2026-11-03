package tick

import (
	"os"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/tmux"
)

// wayBack is what a seat's pane left dead says, where tmux would say `Pane is dead` (orch.WAY_BACK).
const wayBack = "The harness ended. To open it again: Ctrl-b m, then this seat's number."

// hookOptions is the end hook row (orch.set_hook_options): on ak's own server, which one started
// before them lacks, the options that run ak, named by the program that runs: what brings back a
// seat whose harness ended without ak ending it, and what puts the seat a client is in first.  A
// server that is not up gets nothing, and a set that fails is the next tick's to try again.
func hookOptions() error {
	self, err := os.Executable()
	if err != nil {
		return nil
	}
	ak, log := commandhelp.ShellJoin([]string{self, "orch"}), commandhelp.ShellJoin([]string{logPath()})
	job := func(verb string) string {
		return "run-shell -b " + tmuxWord(tmuxText(ak)+" "+verb+" >>"+tmuxText(log)+" 2>&1; true")
	}
	front := job("front")
	options := [][2]string{{"pane-died", job("ended #{q:session_name} #{pane_dead_time}")}, {"remain-on-exit-format", wayBack},
		{"client-attached", front}, {"client-detached", front}, {"client-session-changed", front}}
	var lists [][]string
	for _, option := range options {
		lists = append(lists, []string{"set-option", "-gq", option[0], option[1]})
	}
	tmux.Lists(tmux.Own(), lists)
	return nil
}

// tmuxWord is one word of a tmux command line, quoted as a shell would read it (orch.tmux_word).
func tmuxWord(text string) string {
	if !strings.Contains(text, "'") {
		return "'" + text + "'"
	}
	for _, char := range []string{`\`, `"`, "$", "#"} {
		text = strings.ReplaceAll(text, char, `\`+char)
	}
	return `"` + text + `"`
}

// tmuxText is literal text for a tmux option, its `#`, which starts a format, doubled.
func tmuxText(text string) string { return strings.ReplaceAll(text, "#", "##") }
