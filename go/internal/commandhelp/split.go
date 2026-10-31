package commandhelp

import "strings"

// ShellSplit is a command line's words as Python's shlex.split reads them: whitespace apart,
// quotes and backslashes as a POSIX shell takes them, but that inside double quotes a backslash
// escapes only `"` and itself.  False where shlex refuses the line: a quote left open, or a
// backslash ending it.
func ShellSplit(line string) ([]string, bool) {
	var words []string
	var word strings.Builder
	quote, escaped, in := rune(0), false, false
	for _, r := range line {
		switch {
		case escaped:
			if quote == '"' && r != '"' && r != '\\' {
				word.WriteRune('\\')
			}
			word.WriteRune(r)
			escaped = false
		case quote == '\'' && r != '\'' || quote == '"' && r != '"' && r != '\\':
			word.WriteRune(r)
		case r == '\\':
			escaped, in = true, true
		case quote != 0:
			quote = 0
		case r == '\'' || r == '"':
			quote, in = r, true
		case strings.ContainsRune(" \t\r\n", r):
			if in {
				words, in = append(words, word.String()), false
				word.Reset()
			}
		default:
			word.WriteRune(r)
			in = true
		}
	}
	if in {
		words = append(words, word.String())
	}
	return words, !escaped && quote == 0
}
