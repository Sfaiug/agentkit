package config

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode"
)

var envKey = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

// lineBreaks are the breaks Python's str.splitlines() splits at: both programs read one file alike.
var lineBreaks = strings.NewReplacer("\r\n", "\n", "\r", "\n", "\v", "\n", "\f", "\n", "\x1c", "\n",
	"\x1d", "\n", "\x1e", "\n", "\u0085", "\n", " ", "\n", " ", "\n")

// SpaceClass is Python's whitespace as a regular expression's class: what its str.isspace(),
// strip(), split() and a regular expression's \s read as space, Unicode's separators included.
const SpaceClass = `[\t\n\v\f\r\x{1c}-\x{1f} \x{85}\p{Z}]`

// Space is whether Python reads the character as whitespace: Go's White_Space and the four
// information separators, the set SpaceClass names.
func Space(r rune) bool {
	return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f
}

// SplitLines is text's lines, as Python's str.splitlines() reads them.
func SplitLines(text string) []string {
	if text == "" {
		return nil
	}
	return strings.Split(strings.TrimSuffix(lineBreaks.Replace(text), "\n"), "\n")
}

// Digits is whether text is one or more of the ASCII digits 0 to 9.
func Digits(text string) bool {
	for _, r := range text {
		if r < '0' || r > '9' {
			return false
		}
	}
	return text != ""
}

// RepoEnv is the KEY=value pairs of ~/.agentkit/env/<checkout name>.env, none without that
// file: a project's test secrets live on the machine, never in its repository.  A line the file
// gets wrong is an error, by its number and without its value: a variable dropped in silence
// would read as a test failing.
func RepoEnv(repo string) (map[string]string, error) {
	path := filepath.Join(Home(), "env", filepath.Base(repo)+".env")
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("cannot read %s: %w", path, err)
	}
	env := map[string]string{}
	for n, line := range SplitLines(string(data)) {
		line = strings.TrimFunc(line, Space)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if rest, ok := strings.CutPrefix(line, "export "); ok {
			line = strings.TrimLeftFunc(rest, Space)
		}
		key, value, found := strings.Cut(line, "=")
		if key = strings.TrimFunc(key, Space); !found || !envKey.MatchString(key) {
			return nil, fmt.Errorf("%s:%d: not a KEY=value line", path, n+1)
		}
		value = strings.TrimFunc(value, Space)
		if len(value) > 1 && value[0] == value[len(value)-1] && strings.ContainsRune(`"'`, rune(value[0])) {
			value = value[1 : len(value)-1]
		}
		env[key] = value
	}
	return env, nil
}
