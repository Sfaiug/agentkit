package handin

import (
	"regexp"
	"strings"

	"agentkit/internal/config"
)

// operatorChars are what Python's shlex reads with punctuation_chars=True.
const operatorChars = "();<>|&"

var (
	// a redirection or an operator in a run of operator characters, as Python's exit_guard parts it
	operators  = regexp.MustCompile(`(&?[<>][<>&|]*)|(\|\||&&|[;&|()])`)
	assignment = regexp.MustCompile(`^[A-Za-z_][\p{L}\p{N}_]*=`) // Python's \w reads all of Unicode
)

// A shellWord is a word as Python's shlex reads it, and whether it is a run of operator
// characters read outside quotes.
type shellWord struct {
	text      string
	operators bool
}

// exitGuard is the exit-0 guard in command's shell words, "" for none, as Python's
// hand_in.exit_guard finds it: `true` or `:` run right after `||`, `exit 0` or `set +e`, each a
// path to success whatever the code does.  A command's word is its first after any NAME=value
// words and redirections; quoted text, an operator's included, is a word and holds none, and a
// command shlex cannot split is left to bash.
func exitGuard(command string) string {
	words, ok := shellWords(command)
	if !ok {
		return ""
	}
	after, simple := ";", []shellWord{} // a simple command's words, a redirection as an operator
	for _, word := range append(words, shellWord{";", true}) {
		if !word.operators {
			simple = append(simple, word)
			continue
		}
		for _, part := range operators.FindAllStringSubmatch(word.text, -1) {
			if part[1] != "" {
				simple = append(simple, shellWord{part[1], true})
				continue
			}
			for len(simple) > 0 {
				if simple[0].operators {
					simple = simple[min(2, len(simple)):] // a redirection and its target
				} else if assignment.MatchString(simple[0].text) ||
					config.Digits(simple[0].text) && len(simple) > 1 && simple[1].operators {
					simple = simple[1:] // NAME=value, or the descriptor of a redirection
				} else {
					break
				}
			}
			if after == "||" && len(simple) > 0 && (simple[0].text == "true" || simple[0].text == ":") {
				return "|| " + simple[0].text
			}
			if len(simple) > 1 {
				if pair := simple[0].text + " " + simple[1].text; pair == "exit 0" || pair == "set +e" {
					return pair
				}
			}
			after, simple = part[2], nil
		}
	}
	return ""
}

// shellWords is command's words as Python's shlex.shlex(command, posix=True,
// punctuation_chars=True) reads them with whitespace_split: apart at whitespace and around each
// run of operator characters, a `#` outside quotes ending the line, quotes and backslashes as
// commandhelp.ShellSplit takes them.  False where shlex refuses command: a quote left open, or a
// backslash ending it.
func shellWords(command string) ([]shellWord, bool) {
	var words []shellWord
	var text strings.Builder
	state, back := ' ', 'a' // shlex's state, and the one a backslash returns to
	end := func() {
		words = append(words, shellWord{text.String(), state == 'c'})
		text.Reset()
		state = ' '
	}
	runes := []rune(command)
	for i := 0; i < len(runes); i++ {
		r := runes[i]
		switch {
		case state == '\\':
			if back == '"' && r != '"' && r != '\\' {
				text.WriteRune('\\')
			}
			text.WriteRune(r)
			state = back
		case state == '\'' && r != '\'', state == '"' && r != '"' && r != '\\':
			text.WriteRune(r)
		case state == '"' && r == '\\':
			state, back = '\\', '"'
		case state == '\'' || state == '"':
			state = 'a'
		case strings.ContainsRune(" \t\r\n", r):
			if state != ' ' {
				end()
			}
		case r == '#':
			if state != ' ' {
				end()
			}
			for i < len(runes) && runes[i] != '\n' {
				i++
			}
		case state == 'c' && strings.ContainsRune(operatorChars, r):
			text.WriteRune(r)
		case state == 'c' || state == 'a' && strings.ContainsRune(operatorChars, r):
			end()
			i-- // the next word's first
		case r == '\'' || r == '"':
			state = r
		case r == '\\':
			state, back = '\\', 'a'
		case strings.ContainsRune(operatorChars, r):
			text.WriteRune(r)
			state = 'c'
		default:
			text.WriteRune(r)
			state = 'a'
		}
	}
	switch state {
	case 'a', 'c':
		end()
	case '\\', '\'', '"':
		return nil, false
	}
	return words, true
}
