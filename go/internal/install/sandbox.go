package install

import (
	"os"
	"os/exec"
	"os/user"
	"strings"

	"agentkit/internal/config"
)

// sandbox is whether HOME is not the account's own, as install.sh reads it: the home of the
// name `id -un` gives, $USER's where id fails, and HOME itself where the name is empty.  In a
// sandbox nothing outside HOME changes, so the suite's throwaway homes never reach the host.
func sandbox() bool {
	home := config.UserHome()
	said, err := exec.Command("id", "-un").Output()
	name := strings.TrimRight(string(said), "\n")
	if err != nil {
		name = os.Getenv("USER")
	}
	own := home
	if name != "" {
		account, err := user.Lookup(name)
		if err != nil {
			return true // a home nobody can name is not HOME's account's
		}
		own = account.HomeDir
	}
	return config.Resolve(own) != config.Resolve(home)
}
