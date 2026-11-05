package task

import "strings"

// Contract is what every project declares in the front matter of AGENTS.md on its default
// branch, each line with what it means: `none` declares that there is no such command.
var Contract = []struct{ Key, Meaning string }{
	{"tests", "the command that runs the whole suite at landing, or none where the project has no suite"},
	{"health", "the command that checks the live product works, or none where nothing is live"},
}

// FrontDeclared is a key's value in AGENTS.md front matter and whether the front matter declares
// it, Python's front_value: a Contract line's `none` declares no command, "".
func FrontDeclared(text, key string) (string, bool) {
	match := agentsRe.FindStringSubmatch(text)
	if match == nil {
		return "", false
	}
	for _, line := range strings.Split(match[1], "\n") {
		name, value, found := strings.Cut(strings.TrimSpace(line), ":")
		if value = strings.TrimSpace(value); !found || strings.TrimSpace(name) != key || value == "" {
			continue
		}
		for _, line := range Contract {
			if line.Key == key && value == "none" {
				return "", true
			}
		}
		return value, true
	}
	return "", false
}
