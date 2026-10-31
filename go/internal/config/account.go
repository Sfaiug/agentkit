package config

import (
	"os"
	"regexp"
	"strings"
)

// loginHome is the home of the login a call is on, as the manifest's `[account]` table names
// it and its adapter's shell spells it: an account's own where $AGENTKIT_ACCOUNT names one, else
// the one its `env` variable names unless that is an account's (`drop`), else the usual one.
func loginHome(root *table) string {
	if name := os.Getenv("AGENTKIT_ACCOUNT"); name != "" {
		return strings.ReplaceAll(spelled(accountValue(root, "home")), "{account}", name)
	}
	return usualHome(root)
}

// usualHome is the home of the login a call naming no account is on.
func usualHome(root *table) string {
	if set := os.Getenv(accountValue(root, "env")); set != "" && !handedDown(root) {
		return set
	}
	return spelled(accountValue(root, "usual"))
}

// handedDown is whether the `env` variable names an account's home (`drop`), which that account's
// seat handed down to what it started.
func handedDown(root *table) bool {
	return dropped(os.Getenv(accountValue(root, "env")), accountValue(root, "drop"))
}

func accountValue(root *table, key string) string {
	account, _ := root.get("account").(*table)
	text, _ := account.get(key).(string)
	return text
}

// dropped is whether text matches the pattern as a shell's `case` matches it, each `*` any
// text, slashes included, and nothing else a wildcard: not even a `*` in the home's own name.
func dropped(text, pattern string) bool {
	parts := strings.Split(pattern, "*")
	parts[0] = spelled(parts[0])
	for i, part := range parts {
		parts[i] = regexp.QuoteMeta(part)
	}
	matched, _ := regexp.MatchString(`(?s)\A`+strings.Join(parts, ".*")+`\z`, text)
	return matched
}

// spelled is path with a leading `~` put in the home's place as a shell puts $HOME there:
// joined as text, never cleaned.
func spelled(path string) string {
	if rest, ok := strings.CutPrefix(path, "~"); ok && (rest == "" || rest[0] == '/') {
		home, _ := os.UserHomeDir()
		return home + rest
	}
	return path
}
