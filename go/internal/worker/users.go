package worker

import (
	"fmt"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// comment is a YAML comment closing a front matter value.
var comment = regexp.MustCompile(`(^|` + config.SpaceClass + `)#.*`)

// UsersDeclared is the `users:` answer, `real` or `none`, "" until the owner is asked, Python's
// users_declared: read at base, the target the work lands on, as a branch cannot switch off the
// rule its own review is held to, else as the workspace's AGENTS.md is written.  Read as the YAML
// scalar it is: `users: "real"  # launched in May` says `real`, as a comment or quotes left on
// the word would quietly drop the reviewer's rule for it.
func UsersDeclared(workspace, base string) string {
	value := ""
	if base != "" {
		value = gitcall.DeclaredAt(workspace, base, "users")
	} else {
		value = gitcall.Declared(workspace, "users")
	}
	value = strings.TrimFunc(comment.ReplaceAllString(value, ""), config.Space)
	if len(value) >= 2 && value[0] == value[len(value)-1] && strings.ContainsRune(`'"`, rune(value[0])) {
		value = strings.TrimFunc(value[1:len(value)-1], config.Space)
	}
	return value
}

// UsersRefusal is why a launch into checkout waits for its owner, "" for none, Python's
// users_refusal: its AGENTS.md at ref, "" for a commit git cannot name, has no `users:` answer,
// which decides whether a reviewer holds a new feature to the project's switch (real-users.md),
// and only the owner can give it.  then says where the answer goes.
func UsersRefusal(checkout, ref, then string) string {
	if ref != "" && UsersDeclared(checkout, ref) != "" {
		return ""
	}
	return fmt.Sprintf(`%s/AGENTS.md has no users: line. Ask the owner "Does %s have real users?": "No, straight to live" is users: none; "Yes, new features stay hidden until I switch them on" is users: real. %s`,
		checkout, filepath.Base(checkout), then)
}
