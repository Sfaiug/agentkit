package tmux

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"os/user"
	"runtime"
	"strconv"
	"strings"
	"sync"

	"agentkit/internal/config"
)

// Own is the server ak's seats live on (orch.socket_name): the one AGENTKIT_TMUX_SOCKET names,
// else the one this HOME names, and never the person's default one.
func Own() string {
	if name := os.Getenv("AGENTKIT_TMUX_SOCKET"); name != "" {
		return name
	}
	return HomeServer()
}

// HomeServer is the server this HOME names (orch.home_socket): `agentkit` under the account's own
// home, and one of that home's own under any other, as each HOME has its own ~/.agentkit.  An ak
// under a scratch HOME on the seats' server would take a seat it has no record of for a forgotten one.
func HomeServer() string {
	if account := accountHome(); account != "" && config.Resolve(config.UserHome()) == account {
		return "agentkit"
	}
	sum := sha256.Sum256([]byte(config.Resolve(config.Home())))
	return "agentkit-" + hex.EncodeToString(sum[:4])
}

// accountHome is the passwd entry's home, resolved, and "" for a uid with none, as in a container.
// Read once: an open screen asks for its server many times a second.
var accountHome = sync.OnceValue(func() string {
	if home, found := passwdHome(os.Getuid()); found {
		return config.Resolve(home)
	}
	return ""
})

// passwdHome is the home in that uid's passwd entry.  Linux's is read from /etc/passwd, as os/user
// without cgo reads it, since that os/user makes up an entry from $USER and $HOME where none
// is; a row as glibc takes one: blank space and `#` comments skipped, its ids numbers.  macOS
// keeps its accounts elsewhere, and os/user asks its libc for them.
func passwdHome(uid int) (string, bool) {
	if runtime.GOOS == "darwin" {
		account, err := user.LookupId(strconv.Itoa(uid))
		if err != nil {
			return "", false
		}
		return account.HomeDir, true
	}
	passwd, _ := os.ReadFile("/etc/passwd")
	for _, line := range strings.Split(string(passwd), "\n") {
		line = strings.TrimSpace(line)
		fields := strings.Split(line, ":")
		if strings.HasPrefix(line, "#") || len(fields) < 6 {
			continue
		}
		id, err := strconv.ParseUint(fields[2], 10, 32)
		if _, bad := strconv.ParseUint(fields[3], 10, 32); err == nil && bad == nil && id == uint64(uid) {
			return fields[5], true
		}
	}
	return "", false
}
