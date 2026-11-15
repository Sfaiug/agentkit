package tmux

import (
	"cmp"
	"context"
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

// Client is the environment variable naming, to a popup's menu alone, the tmux client the popup
// opened on (orch.CLIENT_ENV): a seat picked in it opens in that window (Switch), not the one tmux
// last heard a key from, as a key pressed in a popup is none.  No call to tmux carries it (command).
const Client = "AGENTKIT_CLIENT"

// Conf writes ak's own tmux config, ~/.agentkit/state/tmux.conf, and returns its path
// (orch.tmux_conf): its own, as the owner's ~/.tmux.conf is theirs, neither read nor written.  A
// link a harness prints, and each repaint, reaches the owner's terminal whole; every other line is
// one that loads again as it loaded once (again).
func Conf() (string, error) {
	lines, err := again()
	if err != nil {
		return "", err
	}
	text := "# written by ak: ak's own tmux config, never the owner's ~/.tmux.conf\n" +
		"set -as terminal-features \",*:RGB:hyperlinks:sync\"\n" + lines
	path := filepath.Join(config.Home(), "state", "tmux.conf")
	if kept, err := os.ReadFile(path); err == nil && string(kept) == text {
		return path, nil
	}
	if err := write(path, text); err != nil {
		return "", fmt.Errorf("cannot write the tmux config %s: %v", path, err)
	}
	return path, nil
}

// Reload loads those lines (again) into ak's own server (orch.set_hook_options), as tmux reads
// Conf only when a seat starts its server or opens on it: a server running a Ctrl-b m from an older
// ak would keep it.  tmux runs each line on its own, so one it refuses leaves the rest set, and a
// server that is not up starts on none; what tmux refuses is the next tick's to try again.  Its
// error is the one composing the lines.
func Reload() error {
	lines, err := again()
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), ceiling)
	defer cancel()
	call := command(ctx, Own(), "source-file", "-")
	call.Stdin = strings.NewReader(lines)
	call.Run()
	return nil
}

// again is Conf's lines that leave a server as they found it however often it loads them
// (orch.server_conf): all but terminal-features, which -a adds to each time.  A touch scroll on a
// phone scrolls a seat's output, 50000 lines of it, rather than sending arrow keys to the harness;
// a harness that quits as it opens keeps its pane, as the file is read before the seat exists; and
// Ctrl-b m is the menu of the program a seat runs (config.Live) over whatever is running, the
// whole client on a phone, told the client it opened on (Client).  Its hooks are in force before
// the seat exists too, so even a harness that ends as it starts meets them.
func again() (string, error) {
	program, err := config.Live()
	hooks, failed := Hooks()
	if err = cmp.Or(err, failed); err != nil {
		return "", err
	}
	// run-shell -C expands the client's name and size into the popup, read as the key is pressed:
	// display-popup expands neither
	size := func(small, large string) string { return "#{?" + phone + "," + small + "," + large + "}" }
	popup := "display-popup -E -w " + size("100%", "80%") + " -h " + size("100%", "70%") + " " +
		Word(Client+"=#{client_name} ") +
		unformatted(Word(commandhelp.ShellJoin([]string{program, "attach", "--overlay"})))
	text := "set -g mouse on\n" +
		"set -g history-limit 50000\n" +
		"set -g remain-on-exit on\n"
	for _, hook := range hooks {
		text += "set -gq " + hook[0] + " " + Word(hook[1]) + "\n"
	}
	return text + "set -g allow-passthrough on\n" +
		"bind-key m run-shell -C " + Word(popup) + "\n", nil
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
