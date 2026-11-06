package loop

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/helper"
)

// roundChecks is a round's checks, Python's gate.run_round: on the suite helper first, as one
// piece of the tree at HEAD, so a command reads what an earlier one left untracked, at the cost of
// a piece of the repository's `tests:` suite.  Green there is the round's answer.  Anything else --
// no helper, no recipe, no room, a red, the helper failing -- runs the list here, which decides,
// below what the piece printed there: a command that needs this host, its network or a file only
// it holds, is only slower.  A list naming AK_SHARD runs here, as a suite has its own way there
// (pieces).
func (r *repoPlace) roundChecks(l *loop, cmds []string, path string) (bool, string, error) {
	there := ""
	if len(cmds) > 0 && !slices.ContainsFunc(cmds, namesShard.MatchString) {
		green, said, why, err := l.onePiece(r.wt, cmds, path)
		if err != nil || green {
			return green, said, err
		}
		there = said
		l.say("done-when runs here: " + why)
	}
	ok, text, err := r.checks(l, cmds, path)
	if there != "" {
		text = there + "\n\n" + text
	}
	return ok, text, err
}

// onePiece runs cmds one after another on the suite helper that takes them, as one piece, its
// output into path: whether all were green there, the round's record of them then, else what the
// piece printed, "" where none ran, and why the list runs here.
func (l *loop) onePiece(cwd string, cmds []string, path string) (bool, string, string, error) {
	cpus, memory := suiteCost(l.dir, cwd, gitcall.Declared(cwd, "tests"))
	lines := make([]string, len(cmds))
	for i, cmd := range cmds {
		// each command's header is no record (`$ cmd`, then its exit): those are counted
		lines[i] = fmt.Sprintf("printf '%%s\\n' %s && bash -c %s || exit", commandhelp.ShellJoin([]string{"--- $ " + cmd + " ---"}), commandhelp.ShellJoin([]string{cmd}))
	}
	away, why, err := helper.Start(cwd, cpus, memory, strings.Join(lines, "\n"), func(string) {})
	if away == nil || err != nil {
		return false, "", why, err
	}
	defer away.Finish()
	l.say("done-when on the suite helper " + away.Alias + ", as one piece")
	// a stop marked while it prepared starts none
	if err := l.stopCheck(); err != nil {
		return false, "", "", err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return false, "", "", err
	}
	progress, err := os.Create(path)
	if err != nil {
		return false, "", "", err
	}
	defer progress.Close()
	code, stopped, err := l.onHelper(away, "1/1", l.ceiling, progress)
	if err == nil {
		err = l.stopCheck()
	}
	if err != nil {
		return false, "", "", err
	}
	out, err := cutFrom(progress, 0, l.dir, stem(path), outCap)
	if err != nil {
		return false, "", "", err
	}
	status, why := fmt.Sprintf("exit %d", code), "helper "+away.Alias+" "+helper.Failure(code)
	if stopped != "" {
		status, why = "killed at the limit", "helper "+away.Alias+" stopped it at its limit"
	}
	there := strings.TrimRightFunc(fmt.Sprintf("On the suite helper %s, as one piece: [%s]\n%s", away.Alias, status, out), config.Space)
	if code != 0 || stopped != "" {
		return false, there, why, nil
	}
	records := []string{there}
	for _, cmd := range cmds {
		records = append(records, "$ "+cmd+"\n[exit 0]")
	}
	return true, strings.Join(records, "\n\n"), "", nil
}
