package seat

import (
	"path/filepath"
	"strings"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// CheckoutFor is the checkout here of that GitHub repository, Python's local_checkout; "" for none.
func CheckoutFor(slug string) string {
	for _, path := range checkouts(sync.OnceValue(listed)) {
		if origin, err := (gitcall.Git{Repo: path}).Try("remote", "get-url", "origin"); err == nil && gitcall.OwnerName(origin) == strings.ToLower(slug) {
			return path
		}
	}
	return ""
}

// CheckoutOf is the project a repository path is, Python's orch.checkout_of; "" for none.
func CheckoutOf(repo string) string {
	return checkoutOf(repo, sync.OnceValue(listed))
}

// Project is the project a seat opened in cwd is filed under, as orch.cwd_project files it: that
// of the first checkout cwd, or a folder above it, is; "" for none.
func Project(cwd string) string {
	stands := sync.OnceValue(listed)
	for dir := config.Resolve(cwd); ; dir = filepath.Dir(dir) {
		if project := checkoutOf(dir, stands); project != "" || filepath.Dir(dir) == dir {
			return project
		}
	}
}
