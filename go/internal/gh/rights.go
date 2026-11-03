package gh

import (
	"slices"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// Rights is the repository the checkout at dir is a clone of, as GitHub names it, and this
// account's permission on it, Python's deliver.rights: no name where gh cannot say, with what gh
// said.  A gh that never answered, or wanted a prompt, said nothing at all, which is not saying it
// does not know: that is a Stopped.
func Rights(dir string) (repo, permission, said string, err error) {
	code, said, err := Call(dir, "repo", "view", "--json", "nameWithOwner,viewerPermission")
	if err != nil {
		return "", "", "", err
	}
	if Halted(code, said) {
		return "", "", "", &gitcall.Stopped{Why: said}
	}
	if code != 0 {
		return "", "", said, nil
	}
	value, _ := run.Decode([]byte(said))
	answer, _ := value.(*run.Object)
	if answer == nil || !answer.Truthy("nameWithOwner") {
		return "", "", said, nil
	}
	return answer.Str("nameWithOwner"), answer.Str("viewerPermission"), said, nil
}

// Writable is whether a permission may push to the repository and merge into it, Python's
// PUSH_RIGHTS.
func Writable(permission string) bool {
	return slices.Contains([]string{"ADMIN", "MAINTAIN", "WRITE"}, permission)
}

// Halted is whether a gh that ended so never answered, or wanted a prompt, Python's stopped.
func Halted(code int, said string) bool {
	return code == -1 || gitcall.Halted(code, said)
}
