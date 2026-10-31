package config

import (
	"fmt"
	"os"
	"slices"
	"strings"
)

// Words is the words a harness's `[launch]` table lists under key: a seat's line or a worker's
// turn, as the Go build's adapter verbs run its harness.  A word `{name}` is the call's words for
// that name where it has them, else the words this table's own `name` holds, a string being one
// word, so a manifest names its harness's switches once for both; a name neither gives is an
// error.  False where the table lists nothing under key.
func Words(harness, key string, call map[string][]string) ([]string, bool, error) {
	manifests, err := manifests()
	launch, _ := manifests[harness].get("launch").(*table)
	if _, ok := launch.get(key).([]any); err != nil || !ok {
		return nil, false, err
	}
	var expand func(key string, value any) ([]string, error)
	expand = func(key string, value any) ([]string, error) {
		switch value := value.(type) {
		case string:
			return []string{value}, nil
		case []any:
			var found []string
			for _, each := range value {
				word, _ := each.(string)
				name, ok := strings.CutPrefix(word, "{")
				if name, ok = strings.CutSuffix(name, "}"); !ok {
					found = append(found, word)
				} else if words, ok := call[name]; ok {
					found = append(found, words...)
				} else if words, err := expand(name, launch.get(name)); err != nil {
					return nil, err
				} else {
					found = append(found, words...)
				}
			}
			return found, nil
		}
		return nil, fmt.Errorf("adapter manifest %s.toml: [launch] names {%s}, which is no words", harness, key)
	}
	found, err := expand(key, launch.get(key))
	return found, err == nil, err
}

// A Login is the login a call is on, as a harness's `[account]` table names it, and what a
// named one shares with the usual one.
type Login struct {
	// Account is $AGENTKIT_ACCOUNT, "" on the usual login; Env the variable naming the login's
	// home, Home that home, and Usual the home a seat on the usual login runs on, which a named
	// one shares: `usual` where that seat's line unsets Env ([launch] env), whatever the caller's
	// Env says, else the home a call naming no account is on.
	Account, Env, Home, Usual string
	// Unset is what a call on an account unsets: the usual login's own credentials.
	Unset []string
	// Conversations is the directory under a home its conversations are kept in, and Settings
	// its settings files there, which a named login reads through links to the usual one's.
	Conversations string
	Settings      []string
	// Carry is whether a named login's own values, TOML, go into the usual files that lack
	// them first; Line whether a seat's line names an account's login itself.
	Carry, Line bool
	// handedDown is whether, on the usual login, Env names an account's home handed down.
	handedDown bool
}

// Account is the login a call to the harness is on, false where its manifest has no `[account]`.
func Account(harness string) (Login, bool, error) {
	manifests, err := manifests()
	root := manifests[harness]
	account, _ := root.get("account").(*table)
	env, _ := account.get("env").(string)
	if err != nil || env == "" {
		return Login{}, false, err
	}
	conversations, _ := account.get("conversations").(string)
	carry, _ := account.get("carry").(bool)
	line, _ := account.get("line").(bool)
	usual, seat := usualHome(root), words(root, "launch", "env")
	for i := range len(seat) - 1 {
		if seat[i] == "-u" && seat[i+1] == env {
			usual = spelled(accountValue(root, "usual"))
		}
	}
	name := os.Getenv("AGENTKIT_ACCOUNT")
	return Login{name, env, loginHome(root), usual, words(root, "account", "unset"),
		conversations, words(root, "account", "settings"), carry, line,
		name == "" && os.Getenv(env) != "" && handedDown(root)}, true, nil
}

// Environ is environ as a call on the login runs, as the adapter's shell sets it: an account's
// home in Env and Unset gone, or on the usual login an account's home handed down dropped.
func (login Login) Environ(environ []string) []string {
	var kept []string
	for _, pair := range environ {
		name, _, _ := strings.Cut(pair, "=")
		if name == login.Env && (login.Account != "" || login.handedDown) ||
			login.Account != "" && slices.Contains(login.Unset, name) {
			continue
		}
		kept = append(kept, pair)
	}
	if login.Account != "" {
		kept = append(kept, login.Env+"="+login.Home)
	}
	return kept
}
