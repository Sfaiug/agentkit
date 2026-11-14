package helper

import "agentkit/internal/commandhelp"

// pinned is command as a piece runs it there, Python's gate.pinned: its line, and the files its
// parcel takes there, each named for the variable piece.sh names it in.  The machine hands a piece
// no environment, so what one here is handed goes in a file: AK_TIMES, times, the record of each
// test's seconds as its suite started; and AK_ONLY, for a piece that runs only those tests, one
// that lists them.  Neither is in the line, which one argument must hold (start).  The piece runs
// in a clone the lander's look at its checkout never sees, so it checks that clone itself, and
// fails where it changed, however the command exited, dropping the tests it named as not there,
// which say nothing of the tree it was given.
func pinned(command, times string, only []string) (string, map[string]file) {
	files := map[string]file{"AK_TIMES": made(0o644, []byte(times))}
	if only != nil {
		var listed []byte
		for _, test := range only {
			listed = append(listed, test+"\n"...)
		}
		files["AK_ONLY"] = made(0o644, listed)
	}
	return "head=$(git rev-parse HEAD) || exit\nbash -c " + commandhelp.ShellJoin([]string{command}) + "\ncode=$?\n" +
		`[ "$(git rev-parse HEAD)" = "$head" ] && git diff --quiet HEAD ||` +
		` { echo "the piece changed the checkout it tests" >&2;` +
		` : >"${AK_NOT_THERE:-/dev/null}"; [ "$code" != 0 ] || code=1; }` + "\n" +
		`exit "$code"`, files
}
