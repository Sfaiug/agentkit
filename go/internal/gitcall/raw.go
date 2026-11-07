package gitcall

import (
	"errors"
	"fmt"
	"strings"
)

// Raw is what git printed with every byte kept, so a name handed back to git names the same file,
// its failure an error.
func (g Git) Raw(args ...string) (string, error) {
	return g.raw(true, args)
}

// RawTry is Raw as Try is Must: a git that said no is no failure, one that never answered is a
// Stopped.
func (g Git) RawTry(args ...string) (string, error) {
	return g.raw(false, args)
}

func (g Git) raw(check bool, args []string) (string, error) {
	code, out, said, err := g.Bytes(args...)
	if err != nil {
		return "", err
	}
	stop := Halted(code, Decoded(string(said)))
	if (check || stop) && code != 0 {
		why := fmt.Sprintf("git %s failed in %s: %s", strings.Join(args[:min(2, len(args))], " "), g.Repo, Strip(Decoded(string(said))))
		if stop {
			return "", &Stopped{why}
		}
		return "", errors.New(why)
	}
	return string(out), nil
}
