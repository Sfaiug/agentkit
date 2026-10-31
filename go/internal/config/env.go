package config

import (
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
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

// ChildEnv is the environment for anything a run spawns, Python's config.child_env: the run's
// folder, scope and account, and each seat's own variables, are the launch's and none of its
// children's.
func ChildEnv() ([]string, error) {
	dropped, err := SeatEnv()
	if err != nil {
		return nil, err
	}
	dropped = append(dropped, "AGENTKIT_RUN_DIR", "AK_RUN_SCOPE", "AGENTKIT_ACCOUNT")
	var env []string
	for _, pair := range os.Environ() {
		if key, _, _ := strings.Cut(pair, "="); !slices.Contains(dropped, key) {
			env = append(env, pair)
		}
	}
	return env, nil
}

// SeatlessEnv is ChildEnv without the seat's name, saying it is unattended, Python's
// config.seatless_env: nothing below the loop speaks for a seat, and what starts there is
// machinery, on no menu.
func SeatlessEnv() ([]string, error) {
	child, err := ChildEnv()
	var env []string
	for _, pair := range child {
		if !strings.HasPrefix(pair, "AGENTKIT_SESSION=") {
			env = append(env, pair)
		}
	}
	return append(env, "AGENTKIT_UNATTENDED=1"), err
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

// MaxDigits is the longest int Python converts from text (sys.int_info.default_max_str_digits),
// and MinDigits the longest every PYTHONINTMAXSTRDIGITS lets it convert
// (sys.int_info.str_digits_check_threshold).
const (
	MaxDigits = 4300
	MinDigits = 640
)

// Int is the number Python's int() reads in stripped text, or nil: a sign, then decimal
// digits of any script Python knows, with single underscores between them, so `1_0` is ten, and
// no more digits than PYTHONINTMAXSTRDIGITS lets it read, leading zeros among them.
func Int(text string) *big.Int {
	digits := strings.TrimLeft(text, "+-")
	sign := text[:len(text)-len(digits)]
	if len(sign) > 1 {
		return nil
	}
	var number strings.Builder
	for _, part := range strings.Split(digits, "_") {
		if part == "" {
			return nil
		}
		for _, r := range part {
			digit := decimal(r)
			if digit < 0 {
				return nil
			}
			number.WriteRune('0' + digit)
		}
	}
	if limit := intDigits(); limit > 0 && number.Len() > limit {
		return nil
	}
	value, _ := new(big.Int).SetString(sign+number.String(), 10)
	return value
}

// pythonZeros is the zero of each run of ten decimal digits Python 3.13's int() reads, Unicode
// 15.1's: Go's unicode tables follow a later release, whose new digits Python refuses.
var pythonZeros = []rune{
	0x30, 0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66,
	0xDE6, 0xE50, 0xED0, 0xF20, 0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90,
	0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0,
	0xFF10, 0x104A0, 0x10D30, 0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0,
	0x11650, 0x116C0, 0x11730, 0x118E0, 0x11950, 0x11C50, 0x11D50, 0x11DA0, 0x11F50, 0x16A60,
	0x16AC0, 0x16B50, 0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0, 0x1E4F0,
	0x1E950, 0x1FBF0,
}

// decimal is the value of a digit Python's int() reads, or -1 for any other character.
func decimal(r rune) rune {
	i, found := slices.BinarySearch(pythonZeros, r)
	if !found {
		i--
	}
	if i < 0 || r-pythonZeros[i] > 9 {
		return -1
	}
	return r - pythonZeros[i]
}

// intDigits is the most digits Python's int() reads, 0 for any number: PYTHONINTMAXSTRDIGITS
// as Python reads it, else MaxDigits. A value Python refuses stops Python before it starts.
func intDigits() int {
	raw := strings.TrimLeft(os.Getenv("PYTHONINTMAXSTRDIGITS"), " \t\n\v\f\r")
	if limit, err := strconv.ParseInt(raw, 10, 32); err == nil && (limit == 0 || limit >= MinDigits) {
		return int(limit)
	}
	return MaxDigits
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
