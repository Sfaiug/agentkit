package config

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode"
)

// firstKey is a statement's first key component, bare or quoted, after its indent.
var firstKey = regexp.MustCompile(`^(\s*)(?:[\w-]+|'[^']*'|"(?:\\.|[^"\\])*")`)

// MigratePolicy renames config.toml's old policy names, as Python's every command does first
// (config.migrate_policy), keeping every other byte; a file naming both loses the old one. A file
// that does not read, or cannot be written, is left as it is: commands reading it report it, an old
// name among what they refuse.
func MigratePolicy() {
	path := filepath.Join(Home(), "config.toml")
	if _, root := policyFile(path); root == nil {
		return
	}
	// Lock, then read again: another first command may already have renamed it.
	held, err := editing()
	if err != nil {
		return
	}
	defer held.Close()
	data, root := policyFile(path)
	if root == nil {
		return
	}
	var chunks strings.Builder
	statement, inTable := "", false
	for _, line := range strings.SplitAfter(data, "\n") {
		statement += line
		if !inTable {
			declared, err := parseDocument(statement)
			if err != nil {
				continue // a multiline value; only the parser decides where it ends
			}
			inTable = strings.HasPrefix(strings.TrimLeftFunc(statement, unicode.IsSpace), "[")
			for _, names := range policyRenames {
				if _, named := declared.values[names[0]]; named && !inTable {
					statement = firstKey.ReplaceAllString(statement, "${1}"+names[1])
					if _, both := root.values[names[1]]; both {
						statement = ""
					}
				}
			}
		}
		chunks.WriteString(statement)
		statement = ""
	}
	chunks.WriteString(statement)
	tmp := filepath.Join(Home(), "config.tmp")
	if os.WriteFile(tmp, []byte(chunks.String()), 0o600) == nil && os.Chmod(tmp, 0o600) == nil {
		os.Rename(tmp, path)
	}
}

// policyFile is config.toml's text and what it declares, nil unless it reads as TOML naming an
// old policy name.
func policyFile(path string) (string, *table) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", nil
	}
	root, err := parseDocument(string(data))
	if err != nil {
		return "", nil
	}
	for _, names := range policyRenames {
		if _, old := root.values[names[0]]; old {
			return string(data), root
		}
	}
	return "", nil
}
