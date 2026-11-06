// Package move is `ak move ALIAS`: it copies this account's home to the same path on the machine
// `ssh ALIAS` reaches.  A pass taken while ak runs may tear a file being written: a handover's last
// pass, with ak stopped, is the one the other machine carries on from.
package move

import (
	"bytes"
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"syscall"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/task"
)

const (
	tmp      = ".agentkit/tmp"
	keys     = ".ssh/authorized_keys" // the keys that reach that machine
	profile  = ".local/share/browser-bridge/profile"
	vanished = 24 // rsync's exit for a file gone between its listing and its sending
)

var (
	// What each machine keeps of its own, neither sent nor deleted there: names, which `--delete`
	// would follow through a link, so a link at or above what is asked refuses the copy.  A lock
	// file is a link by nature, so its folder is asked instead.
	kept  = []string{tmp, keys, profile + "/SingletonLock", profile + "/SingletonSocket", profile + "/SingletonCookie"}
	asked = []string{tmp, keys, profile}
	// install.sh's own match for its tick's line, so what the tick looks like has one home
	cronMatch = regexp.MustCompile(`(?m)^CRON_MATCH='(.*)'$`)
	repo      = config.Repo
)

// Main is a refusal's 1, a usage or failure's 2, a Ctrl-C's 130, else what rsync says.
func Main(args []string, out, errOut io.Writer) int {
	if len(args) != 1 || strings.HasPrefix(args[0], "-") {
		fmt.Fprintf(errOut, "ak move: %s\n", commandhelp.Usage("move"))
		return 2
	}
	// a Ctrl-C still takes the token back
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	code, err := copyHome(ctx, args[0], config.Pure(config.UserHome()), out, errOut)
	if ctx.Err() != nil {
		fmt.Fprintln(errOut, "\nak move: interrupted")
		return 130
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak move: %s\n", err)
		return 2
	}
	return code
}

func copyHome(ctx context.Context, alias, home string, out, errOut io.Writer) (int, error) {
	refused, err := refusals(ctx, alias, home, errOut)
	if err != nil {
		return 0, err
	}
	for _, reason := range refused {
		fmt.Fprintf(errOut, "ak move: refused: %s\n", reason)
	}
	if len(refused) > 0 {
		return 1, nil
	}
	// -H keeps a file with several names, as a local clone's objects, one file there; the first
	// pass takes hours, so it shows how far it is
	flags := []string{"-aH", "--no-D", "--delete", "--info=progress2"}
	for _, path := range kept {
		flags = append(flags, "--exclude=/"+path)
	}
	rsync := exec.CommandContext(ctx, "rsync", append(flags, home+"/", alias+":"+home+"/")...)
	rsync.Stdin, rsync.Stdout, rsync.Stderr = os.Stdin, out, errOut
	err = rsync.Run()
	var exited *exec.ExitError
	if err != nil && !errors.As(err, &exited) {
		return 0, err
	}
	if status, ok := rsync.ProcessState.Sys().(syscall.WaitStatus); ok && status.Signaled() {
		return -int(status.Signal()), nil
	}
	if code := rsync.ProcessState.ExitCode(); code != vanished {
		return code, nil
	}
	return 0, nil
}

// refusals are the reasons not to copy: this machine's first, and only with none of those is the
// other machine asked.
func refusals(ctx context.Context, alias, home string, errOut io.Writer) ([]string, error) {
	facts, err := says(ctx, []string{"sh", "-c"}, home, "", errOut)
	if err != nil {
		return nil, err
	}
	var refused []string
	for _, path := range links(facts) {
		refused = append(refused, path+" is a link here")
	}
	if len(refused) > 0 {
		return refused, nil
	}
	install, err := os.ReadFile(filepath.Join(repo(), "install.sh"))
	if err != nil {
		return nil, err
	}
	tick := cronMatch.FindStringSubmatch(task.Text(install))
	if tick == nil {
		return nil, errors.New("install.sh holds no CRON_MATCH")
	}
	// a name only this run has made, gone before the copy: a machine whose home holds it shares
	// this home
	token, err := os.CreateTemp(home, ".ak-move-*")
	if err != nil {
		return nil, err
	}
	defer os.Remove(token.Name())
	defer token.Close()
	facts, err = says(ctx, []string{"ssh", alias}, home, `printf 'home %s\n' "$HOME"
[ ! -e `+commandhelp.ShellJoin([]string{filepath.Base(token.Name())})+` ] || echo here
if command -v crontab >/dev/null; then
  tab=$(crontab -l) || echo tick
  ! printf '%s\n' "$tab" | grep -qE `+commandhelp.ShellJoin(tick[1:])+` || echo tick
fi`, errOut)
	if err != nil {
		return nil, err
	}
	if slices.Contains(facts, "here") {
		refused = append(refused, alias+" is this machine")
	}
	if !slices.Contains(facts, "home "+home) {
		refused = append(refused, "the home on "+alias+" is not "+home)
	}
	if slices.Contains(facts, "tick") {
		refused = append(refused, "ak's tick is in the crontab on "+alias+", or that crontab cannot be read")
	}
	for _, path := range links(facts) {
		refused = append(refused, path+" is a link on "+alias)
	}
	return refused, nil
}

// says is what a machine's shell, in its home, says of it, a fact a line: first `link PATH` for
// each path at or above what is asked that is a link, then what script says.
func says(ctx context.Context, shell []string, home, script string, errOut io.Writer) ([]string, error) {
	line := commandhelp.ShellJoin([]string{"sh", "-c", `cd || exit
for part in ` + commandhelp.ShellJoin(parts(home)) + `; do [ ! -L "$part" ] || echo "link $part"; done
` + script})
	var stdout bytes.Buffer
	cmd := exec.CommandContext(ctx, shell[0], append(shell[1:], line)...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, &stdout, errOut
	if cmd.Run() != nil {
		return nil, fmt.Errorf("`%s` failed", commandhelp.ShellJoin(shell))
	}
	return config.SplitLines(stdout.String()), nil
}

func links(facts []string) []string {
	var paths []string
	for _, fact := range facts {
		if path, ok := strings.CutPrefix(fact, "link "); ok {
			paths = append(paths, path)
		}
	}
	return paths
}

// parts is what is asked and each folder above it, sorted: they hang off one chain of folders by
// names none of which starts another, so a string's order is a path's.
func parts(home string) []string {
	var found []string
	for _, path := range asked {
		path = config.Pure(strings.TrimSuffix(home, "/") + "/" + path) // Path.home() / path, the root's too
		found = append(found, path)
		for i, char := range path {
			if char == '/' {
				found = append(found, cmp.Or(path[:i], "/"))
			}
		}
	}
	slices.Sort(found)
	return slices.Compact(found)
}
