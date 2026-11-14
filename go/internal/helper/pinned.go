package helper

import "agentkit/internal/commandhelp"

// pinned is command as a piece runs it there, Python's gate.pinned: its line, and the files its
// parcel takes there, each named for the variable piece.sh names it in.  The machine hands a piece
// no environment, so what one here is handed goes in a file: AK_TIMES, times, the record of each
// test's seconds as its suite started; and AK_ONLY, for a piece that runs only those tests, one
// that lists them.  Neither is in the line, which one argument must hold (start).  The piece runs
// in a clone the lander's look at its checkout never sees, so it checks that clone itself, and
// fails where it changed.
func pinned(command, times string, only []string) (string, map[string]file) {
	files := map[string]file{"AK_TIMES": made(0o644, []byte(times))}
	if only != nil {
		var listed []byte
		for _, test := range only {
			listed = append(listed, test+"\n"...)
		}
		files["AK_ONLY"] = made(0o644, listed)
	}
	return "head=$(git rev-parse HEAD) && bash -c " + commandhelp.ShellJoin([]string{command}) + " || exit\n" +
		`[ "$(git rev-parse HEAD)" = "$head" ] && git diff --quiet HEAD ||` +
		` { echo "the piece changed the checkout it tests" >&2; exit 1; }`, files
}
