package tmux

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"os/user"
	"strconv"
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
	account, err := user.LookupId(strconv.Itoa(os.Getuid()))
	if err != nil {
		return ""
	}
	return config.Resolve(account.HomeDir)
})
