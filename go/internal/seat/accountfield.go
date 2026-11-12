package seat

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/tmux"
)

// errFieldHeld is a move off an account that waits: the respawn would end what the seat's input
// field holds, and it is not read whole and empty (watch.field_empty).
var errFieldHeld = errors.New("input field not read empty")

// fieldEmpty is watch.field_empty: that capture's input field, read whole, holds nothing.  A
// screen's rules can read a tall draft as an empty prompt; the composer read whole cannot.
func fieldEmpty(own, pane string) bool {
	held, drawn := eyeOf(own).rules.ComposerDraft(pane)
	return drawn && held == ""
}

// fieldWaits is whether a move over a field not read empty waits for it to empty: every move but
// a spent account's from a pane ak's editor is in, whose text Python lifts and carries across
// (watch.carry_draft).
func (at seatAt) fieldWaits(spent bool) bool {
	return !spent || !at.editorIn()
}

// editorIn is watch.seat_editor: the harness names the keys that open ak's editor, and the pane was
// launched with it.
func (at seatAt) editorIn() bool {
	chrome, _ := config.Section(at.own, "screen")
	if keys, _ := chrome["editor"].([]any); len(keys) == 0 {
		return false
	}
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", at.pane, "#{pane_id}\t#{pane_pid}\t#{pane_tty}")
	pane := strings.Split(said, "\t")
	return err == nil && len(pane) == 3 && strings.HasPrefix(pane[0], "%") && editorLaunched(pane[1], pane[2])
}

// editorLaunched is aside_editor.launched: the last process down from pid still on that terminal,
// whose environment the harness inherited, has ak's editor, the one a seat is launched with
// (config.LiveRepo), as its $VISUAL.  Each process's parent is read, as a kernel built without
// CONFIG_PROC_CHILDREN lists no task's children; with no /proc, as on a Mac, none is found.
func editorLaunched(pid, tty string) bool {
	entries, err := os.ReadDir("/proc")
	if _, number := strconv.Atoi(pid); err != nil || number != nil {
		return false
	}
	parents := map[string]string{}
	for _, entry := range entries {
		if n, err := strconv.Atoi(entry.Name()); err == nil {
			if stat, ok := host.ReadStat(n); ok {
				parents[entry.Name()] = strconv.Itoa(stat.Parent)
			}
		}
	}
	for {
		below := ""
		for _, entry := range entries {
			if child := entry.Name(); parents[child] == pid {
				if stdin, _ := os.Readlink("/proc/" + child + "/fd/0"); stdin == tty {
					below = child
					break
				}
			}
		}
		if below == "" {
			break
		}
		pid = below
	}
	env, err := os.ReadFile("/proc/" + pid + "/environ")
	if err != nil {
		return false
	}
	editor := resolved(filepath.Join(config.LiveRepo(), "tools", "aside-editor"))
	for _, entry := range bytes.Split(env, []byte{0}) {
		if visual, ok := bytes.CutPrefix(entry, []byte("VISUAL=")); ok && resolved(string(visual)) == editor {
			return true
		}
	}
	return false
}
