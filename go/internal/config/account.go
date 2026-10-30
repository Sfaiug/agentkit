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
	account, _ := root.get("account").(*table)
	value := func(key string) string {
		text, _ := account.get(key).(string)
		return text
	}
	if name := os.Getenv("AGENTKIT_ACCOUNT"); name != "" {
		return strings.ReplaceAll(spelled(value("home")), "{account}", name)
	}
	if set := os.Getenv(value("env")); set != "" && !dropped(set, value("drop")) {
		return set
	}
	return spelled(value("usual"))
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
