package host

import "os/exec"

// Witnessed is the command running program with args where Place can tell it started though the
// program may not say so for itself, as this one does (Placed): a shell gives that word for it, as
// Python's orch.WITNESS does, then becomes it.
func Witnessed(program string, args ...string) *exec.Cmd {
	witness := `[ -z "$` + placedEnv + `" ] || printf %s "$$" >"$` + placedEnv + `" || exit 1; unset ` + placedEnv + `; exec "$0" "$@"`
	return exec.Command("sh", append([]string{"-c", witness, program}, args...)...)
}
