package gitcall

import (
	"fmt"
	"strings"
)

// Raw is what git printed with every byte kept, so a name handed back to git names the same file,
// its failure an error.
func (g Git) Raw(args ...string) (string, error) {
	code, out, said, err := g.Bytes(args...)
	if err != nil {
		return "", err
	}
	if code != 0 {
		return "", fmt.Errorf("git %s failed in %s: %s", strings.Join(args[:min(2, len(args))], " "), g.Repo, Strip(Decoded(string(said))))
	}
	return string(out), nil
}
