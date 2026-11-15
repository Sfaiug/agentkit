package config

import (
	"os"
	"path/filepath"
	"strings"
)

// ServerAlias is the ssh alias of the server, which install.sh records on a client and nowhere
// else (config.server_alias); "" on a server.
func ServerAlias() string {
	saved, _ := os.ReadFile(filepath.Join(Home(), "state", "server"))
	return strings.TrimFunc(string(saved), Space)
}
