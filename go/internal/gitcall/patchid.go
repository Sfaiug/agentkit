package gitcall

import "strings"

// PatchID is Python's roundloop.patch_id: the stable id of the change base...head, which a new
// commit of the same change keeps; "" for an empty diff or a git that failed.
func (g Git) PatchID(base, head string) (string, error) {
	code, diff, err := g.Out("diff", base+"..."+head)
	if err != nil || code != 0 || diff == "" {
		return "", err
	}
	g.In = []byte(diff)
	code, out, _, err := g.Run("patch-id", "--stable")
	if fields := strings.Fields(out); err == nil && code == 0 && len(fields) > 0 {
		return fields[0], nil
	}
	return "", err
}
