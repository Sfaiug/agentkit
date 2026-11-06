package commandhelp

import "strings"

// ShellSplit is a command line's words as Python's shlex.split reads them: whitespace apart,
// quotes and backslashes as a POSIX shell takes them, but that inside double quotes a backslash
// escapes only `"` and itself.  False where shlex refuses the line: a quote left open, or a
// backslash ending it.
func ShellSplit(line string) ([]string, bool) {
	var words []string
	ok := shellWords(line, func(word string, _ int) bool {
		words = append(words, word)
		return true
	})
	return words, ok
}

// ShellWord is text's first word as ShellSplit reads it, and how much of text it takes: through
// the whitespace that ends it, as shlex's stream stands once it has read the word.  False where
// shlex refuses that word; "" and 0 where text holds none.
func ShellWord(text string) (word string, took int, ok bool) {
	ok = shellWords(text, func(first string, end int) bool {
		word, took = first, end
		return false
	})
	return word, took, ok
}

// shellWords hands take each word and where it ends, until take says to stop.
func shellWords(line string, take func(word string, end int) bool) bool {
	var word strings.Builder
	quote, escaped, in := rune(0), false, false
	for at, r := range line {
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
				if !take(word.String(), at+1) {
					return true
				}
				in = false
				word.Reset()
			}
		default:
			word.WriteRune(r)
			in = true
		}
	}
	if in {
		take(word.String(), len(line))
	}
	return !escaped && quote == 0
}
