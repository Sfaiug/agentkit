package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
)

var sessionPunctuation = regexp.MustCompile(`[^a-z0-9_-]+`)
var sessionDashes = regexp.MustCompile(`-+`)

const renameHops = 8

func normalizeSession(name string) string {
	return strings.Join(strings.FieldsFunc(name, func(r rune) bool {
		return unicode.IsSpace(r) || (r >= '\x1c' && r <= '\x1f')
	}), " ")
}

func sessionPath(name string) (string, error) {
	if name == "" || name == "." || name == ".." || filepath.Base(name) != name {
		return "", fmt.Errorf("invalid AGENTKIT_SESSION name %s", commandhelp.Quote(name))
	}
	return filepath.Join(Home(), "state", "session-"+name+".json"), nil
}

// A rename leaves a pointer because the running seat keeps its original
// environment. Return the resolved record with its name so lookups agree.
func CurrentSession() (string, map[string]any, error) {
	name := os.Getenv("AGENTKIT_SESSION")
	if name == "" {
		return "", nil, nil
	}
	name = normalizeSession(name)
	path, err := sessionPath(name)
	if err != nil {
		return "", nil, err
	}
	if strings.Contains(name, " ") {
		if _, err := os.Stat(path); err != nil {
			name = sessionPunctuation.ReplaceAllString(strings.ToLower(name), "-")
			name = strings.Trim(sessionDashes.ReplaceAllString(name, "-"), "-")
			if len(name) > 40 {
				name = name[:40]
			}
			name = strings.Trim(name, "-")
			if name == "_ak" {
				name = ""
			}
		}
	}
	origin, err := sessionPath(name)
	if err != nil {
		return "", nil, err
	}
	seen := []string{name}
	for hops := 0; hops <= renameHops; hops++ {
		path, err := sessionPath(name)
		if err != nil {
			return "", nil, err
		}
		data, err := os.ReadFile(path)
		if os.IsNotExist(err) {
			return name, nil, nil
		}
		if err != nil {
			return "", nil, fmt.Errorf("cannot read %s: %w", path, err)
		}
		if !utf8.Valid(data) {
			return "", nil, fmt.Errorf("%s: invalid UTF-8", path)
		}
		var value any
		if err := json.Unmarshal(data, &value); err != nil {
			return "", nil, fmt.Errorf("%s: %w", path, err)
		}
		record, _ := value.(map[string]any)
		next, renamed := record["renamed"].(string)
		if !renamed {
			return name, record, nil
		}
		name = normalizeSession(next)
		for _, old := range seen {
			if name == old {
				return "", nil, fmt.Errorf("%s: the rename chain loops through %s", origin, strings.Join(seen, " -> "))
			}
		}
		seen = append(seen, name)
	}
	return "", nil, fmt.Errorf("%s: more than %d renames deep", origin, renameHops)
}
