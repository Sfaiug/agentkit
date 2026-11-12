package helper

import "agentkit/internal/commandhelp"

// pinned is command as a piece runs it there, Python's gate.pinned.  The machine hands a piece no
// environment, so what one here is handed goes in its command: AK_TIMES holding times, the record
// of each test's seconds as its suite started; and AK_ONLY, for a piece that runs only those
// tests, naming one that lists them.  The piece runs in a clone the lander's look at its checkout
// never sees, so it checks that clone itself, and fails where it changed.
func pinned(command, times string, only []string) string {
	line := "export AK_TIMES=" + commandhelp.ShellJoin([]string{times}) + "\n"
	if only != nil {
		line += `export AK_ONLY="$(mktemp)" && printf '%s\n' ` + commandhelp.ShellJoin(only) + ` >"$AK_ONLY" || exit` + "\n"
	}
	return line + "head=$(git rev-parse HEAD) && bash -c " + commandhelp.ShellJoin([]string{command}) + " || exit\n" +
		`[ "$(git rev-parse HEAD)" = "$head" ] && git diff --quiet HEAD ||` +
		` { echo "the piece changed the checkout it tests" >&2; exit 1; }`
}
