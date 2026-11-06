package tmux

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

// phone is a client too small for a popup of 80% by 70%, under sixty columns or twenty-five rows,
// which would hold a key line and nothing to press it on (orch.SMALL_CLIENT).
const phone = "#{||:#{e|<:#{client_width},60},#{e|<:#{client_height},25}}"

// Conf writes ak's own tmux config, ~/.agentkit/state/tmux.conf, and returns its path
// (orch.tmux_conf): its own, as the owner's ~/.tmux.conf is theirs, neither read nor written.  A
// touch scroll on a phone scrolls a seat's output, 50000 lines of it, rather than sending arrow keys
// to the harness; a harness that quits as it opens keeps its pane, as the file is read before the
// seat exists; a link it prints, and each repaint, reaches the owner's terminal whole; and Ctrl-b m
// is this program's menu over whatever is running, the whole client on a phone.  What runs
// Python's verbs, the pane-died hook and its kin, is the tick's to set.
func Conf() (string, error) {
	program, err := os.Executable()
	if err != nil {
		return "", err
	}
	menu := Word(commandhelp.ShellJoin([]string{program, "attach", "--overlay"}))
	text := "# written by ak: ak's own tmux config, never the owner's ~/.tmux.conf\n" +
		"set -g mouse on\n" +
		"set -g history-limit 50000\n" +
		"set -g remain-on-exit on\n" +
		"set -g allow-passthrough on\n" +
		"set -as terminal-features \",*:RGB:hyperlinks:sync\"\n" +
		"bind-key m if-shell -F " + Word(phone) + " " + Word("display-popup -E -w 100% -h 100% "+menu) +
		" " + Word("display-popup -E -w 80% -h 70% "+menu) + "\n"
	path := filepath.Join(config.Home(), "state", "tmux.conf")
	if kept, err := os.ReadFile(path); err == nil && string(kept) == text {
		return path, nil
	}
	if err := write(path, text); err != nil {
		return "", fmt.Errorf("cannot write the tmux config %s: %v", path, err)
	}
	return path, nil
}

// write lands text at path whole, as a server may be reading the one there: made in ak's scratch
// folder, as state holds only what its readers know.
func write(path, text string) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	aside, err := os.CreateTemp(filepath.Join(config.Home(), "tmp"), "tmux.conf-")
	if err != nil {
		return err
	}
	defer os.Remove(aside.Name()) // gone already once it lands
	_, err = aside.WriteString(text)
	if closed := aside.Close(); err == nil {
		err = closed
	}
	if err != nil {
		return err
	}
	return os.Rename(aside.Name(), path)
}

// Word is one word of a tmux command line, quoted as a shell would read it (orch.tmux_word).
func Word(text string) string {
	if !strings.Contains(text, "'") {
		return "'" + text + "'"
	}
	for _, char := range []string{`\`, `"`, "$", "#"} {
		text = strings.ReplaceAll(text, char, `\`+char)
	}
	return `"` + text + `"`
}
