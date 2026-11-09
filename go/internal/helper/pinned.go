package helper

import (
	"os"

	"agentkit/internal/commandhelp"
)

// pinned is command as a piece runs it there, Python's gate.pinned.  The machine hands a piece no
// environment, so what one here is handed goes in its command: AK_TIMES holding times, the record
// of each test's seconds as its suite started; AK_CHANGED, where changed names a file here, naming
// a file there holding the same paths; and AK_ONLY, for a piece that runs only those tests, naming
// one that lists them.  The piece runs in a clone the lander's look at its checkout never sees, so
// it checks that clone itself, and fails where it changed.
func pinned(command, times, changed string, only []string) (string, error) {
	line := "export AK_TIMES=" + commandhelp.ShellJoin([]string{times}) + "\n"
	if changed != "" {
		paths, err := os.ReadFile(changed)
		if err != nil {
			return "", err
		}
		line += `export AK_CHANGED="$(mktemp)" && printf %s ` + commandhelp.ShellJoin([]string{string(paths)}) + ` >"$AK_CHANGED" || exit` + "\n"
	}
	if only != nil {
		line += `export AK_ONLY="$(mktemp)" && printf '%s\n' ` + commandhelp.ShellJoin(only) + ` >"$AK_ONLY" || exit` + "\n"
	}
	return line + "head=$(git rev-parse HEAD) && bash -c " + commandhelp.ShellJoin([]string{command}) + " || exit\n" +
		`[ "$(git rev-parse HEAD)" = "$head" ] && git diff --quiet HEAD ||` +
		` { echo "the piece changed the checkout it tests" >&2; exit 1; }`, nil
}
