package config

import (
	"os"
	"path/filepath"
	"strings"
)

// LoginPath is the login's own of the paths a harness's `[login]` table lists under key, resolved
// in the login's environment and the caller's directory as ManifestPaths resolves them: the last
// one left, so a path naming $AGENTKIT_ACCOUNT, listed after the usual login's, is a named
// login's.  "" where none is left.
func LoginPath(harness, key string, login Login) string {
	paths, _ := Words(harness, "login", key)
	env := map[string]string{}
	for _, pair := range login.Environ(os.Environ()) {
		name, value, _ := strings.Cut(pair, "=")
		env[name] = value
	}
	cwd, _ := os.Getwd()
	found := ManifestPaths(paths, env, cwd)
	if len(found) == 0 {
		return ""
	}
	return found[len(found)-1]
}

// WorkerToken is the file ak keeps the harness's worker token in for the login, and the variable
// a turn is handed its text in, as its manifest's `[worker_token]` names them: the file under
// ~/.agentkit/secrets, an account's beside it under its name.  Both "" where it names none.
func WorkerToken(harness string, login Login) (file, variable string) {
	table, _ := Section(harness, "worker_token")
	file, _ = table["file"].(string)
	variable, _ = table["env"].(string)
	if file == "" || variable == "" {
		return "", ""
	}
	if login.Account != "" {
		file += "." + login.Account
	}
	return filepath.Join(Home(), "secrets", file), variable
}
