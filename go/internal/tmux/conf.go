package tmux

import (
	"cmp"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

// release is the release a tmux names as it says its version.
var release = regexp.MustCompile(`(\d+)\.(\d+)`)

// float is what Ctrl-b m runs in the background on a tmux that floats a popup (floats), as
// orch.FLOAT does and for the reasons it gives, on the same pane options and lock, so popups of
// either ak over one pane keep and put back its styles together: p the pane it opens over, c its
// client, w and h its size; the popup is bordered in the theme's border -- where the look reads on
// the colour kept, titled (orch.POPUP_TITLE) and bordered in the look's on that colour, which its
// menu is handed (terminal.Background) -- and the pane draws in its dim while the popup is up, then
// has exactly its own styles back once the last popup over it is down.  The colours are asked as the
// key is pressed (ColoursVerb), so they are in the shades kept then, whichever ak's menu kept them,
// and frame and menu of that one read.  Its words: tmux itself (real), the command that says the
// colours, and the popup's command.
const float = `tmux() { command %s "$@"; }; set -- $(%s); b="fg=#$1${3:+,bg=#$3}" m="fg=#$2"; ` +
	`o() { tmux show-options -pqv -t "$p" "$1"; }; ` +
	`h() { [ -n "$(tmux show-options -pq -t "$p" "$1")" ]; }; ` +
	`l() { tmux wait-for "$1" "ak-float$p"; }; { l -L; n=$(o @ak_floats); ` +
	`for s in window-style window-active-style; do ` +
	`if [ -z "$n" ] && h $s; then tmux set-option -p -t "$p" @ak_was_$s "$(o $s)"; fi; ` +
	`tmux set-option -p -t "$p" $s "$m"; done; ` +
	`tmux set-option -p -t "$p" @ak_floats $((${n:-0} + 1)); l -U; } & d=$!; ` +
	`tmux display-popup -E -b rounded -S "$b" ${3:+-T ' agentkit '} -w "$w" -h "$h" -e "` + Client + `=$c" ` +
	`${3:+-e ` + terminal.Background + `=$3} -c "$c" -t "$p" %s; ` +
	`wait $d; l -L; n=$(o @ak_floats); ` +
	`if [ "${n:-1}" -gt 1 ]; then tmux set-option -p -t "$p" @ak_floats $((n - 1)); ` +
	`else for s in window-style window-active-style; do ` +
	`if h @ak_was_$s; then tmux set-option -p -t "$p" $s "$(o @ak_was_$s)" \; ` +
	`set-option -pu -t "$p" @ak_was_$s; else tmux set-option -pu -t "$p" $s; fi; done; ` +
	`tmux set-option -pu -t "$p" @ak_floats; fi; l -U; true`

// ColoursVerb is the unlisted command float asks its colours of, `ak colours look <role>...`: each
// role's colour in the look on the colour kept, as Python's themes.py run bare says it
// (terminal.InLook).  A word outside every command's own, it is never a seat's name.
const ColoursVerb = "colours"

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
// whole client on a phone, told the client it opened on (Client), floating on a tmux that floats it
// (float).  Its hooks are in force before the seat exists too, so even a harness that ends as it
// starts meets them.
func again() (string, error) {
	program, err := config.Live()
	hooks, failed := Hooks()
	if err = cmp.Or(err, failed); err != nil {
		return "", err
	}
	// run-shell -C expands the client's name and size into the popup, read as the key is pressed:
	// display-popup expands neither
	size := func(small, large string) string { return "#{?" + phone + "," + small + "," + large + "}" }
	overlay := commandhelp.ShellJoin([]string{program, "attach", "--overlay"})
	bind := "run-shell -C " + Word("display-popup -E -w "+size("100%", "80%")+" -h "+size("100%", "70%")+" "+
		Word(Client+"=#{client_name} ")+unformatted(Word(overlay)))
	if floats() {
		// run-shell expands the pane, the client and the size into the job as the key is pressed
		bind = "run-shell -b " + Word("p='#{pane_id}' c='#{client_name}' w='"+size("100%", "80%")+"' h='"+
			size("100%", "70%")+"'; "+unformatted(fmt.Sprintf(float, commandhelp.ShellJoin([]string{real()}),
			commandhelp.ShellJoin([]string{program, ColoursVerb, "look", "border", "dim"}),
			commandhelp.ShellJoin([]string{overlay}))))
	}
	text := "set -g mouse on\n" +
		"set -g history-limit 50000\n" +
		"set -g remain-on-exit on\n"
	for _, hook := range hooks {
		text += "set -gq " + hook[0] + " " + Word(hook[1]) + "\n"
	}
	return text + "set -g allow-passthrough on\n" +
		"bind-key m " + bind + "\n", nil
}

// floats is whether this tmux floats a popup, 3.3 or later (orch.FLOATS): an older one refuses
// float's flags, and draws the plain popup.
func floats() bool {
	said, _ := run(Default, "-V")
	found := release.FindStringSubmatch(said)
	if found == nil {
		return false
	}
	major, _ := strconv.Atoi(found[1])
	minor, _ := strconv.Atoi(found[2])
	return major > 3 || major == 3 && minor >= 3
}

// real is tmux itself, never the shim ~/.agentkit/bin holds for a seat's PATH (guard.real): float's
// job runs in the server's environment, which may start with it, and every call through it would
// stand between the key and the popup.
func real() string {
	shims := filepath.Join(config.Home(), "bin")
	for _, dir := range filepath.SplitList(os.Getenv("PATH")) {
		if path, err := exec.LookPath(filepath.Join(dir, "tmux")); err == nil && filepath.Clean(dir) != shims {
			return path
		}
	}
	return "tmux"
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
