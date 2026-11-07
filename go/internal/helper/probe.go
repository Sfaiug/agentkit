package helper

import (
	"agentkit/internal/commandhelp"
	"agentkit/internal/gitcall"
)

// Places is how many pieces of that cost the machines that take tests fit now, as Start weighs
// each, Python's places: a red stack's narrowing sends as many probes in a round.  0 where the
// repository has no recipe, as Start then sends nothing.
func Places(cpus, memoryMB float64, cwd string) int {
	aliases := takers("tests")
	if len(aliases) == 0 {
		return 0
	}
	repo := gitcall.RepositoryID(cwd)
	if image, _, err := recipeOf(cwd, repo); err != nil || image == "" {
		return 0
	}
	count := 0
	for _, alias := range aliases {
		fit, _ := room(alias, cpus, memoryMB, least(repo), false)
		count += fit.count
	}
	return count
}

// Probe sends just the tests only of command, one piece of that cost, as Start does, Python's
// start(one=True) of gate.pinned(only=): it holds only the CPUs its one piece gets there, so the
// probes of its round started beside it find the rest.  The piece is `1/1`, its tests listed in
// the file AK_ONLY names; nil where no machine took it.
func Probe(cwd string, cpus, memoryMB float64, command string, only []string) (*Away, error) {
	listed := `export AK_ONLY="$(mktemp)" && printf '%s\n' ` + commandhelp.ShellJoin(only) + ` >"$AK_ONLY" || exit` + "\n"
	away, _, err := start(cwd, cpus, memoryMB, listed+pinned(command), nil, true, func(string) {})
	return away, err
}
