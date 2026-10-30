package commandhelp

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"
)

// shellSafe is a word Python's shlex.quote leaves bare.
var shellSafe = regexp.MustCompile(`^[\w@%+=:,./-]+$`)

// ShellJoin is a command line as Python's shlex.join writes it: each word a shell would read
// otherwise in single quotes.
func ShellJoin(words []string) string {
	quoted := make([]string, len(words))
	for i, word := range words {
		quoted[i] = word
		if !shellSafe.MatchString(word) {
			quoted[i] = "'" + strings.ReplaceAll(word, "'", `'"'"'`) + "'"
		}
	}
	return strings.Join(quoted, " ")
}

// Python's repr is part of the existing refusal text, including its choice of quotes.
func Quote(value string) string {
	quote := '\''
	if strings.ContainsRune(value, '\'') && !strings.ContainsRune(value, '"') {
		quote = '"'
	}
	var out strings.Builder
	out.WriteRune(quote)
	for _, r := range value {
		switch {
		case r == quote || r == '\\':
			out.WriteRune('\\')
			out.WriteRune(r)
		case r == '\n':
			out.WriteString("\\n")
		case r == '\r':
			out.WriteString("\\r")
		case r == '\t':
			out.WriteString("\\t")
		case unicode.IsPrint(r) && (r == ' ' || !unicode.IsSpace(r)):
			out.WriteRune(r)
		case r <= 0xff:
			fmt.Fprintf(&out, "\\x%02x", r)
		case r <= 0xffff:
			fmt.Fprintf(&out, "\\u%04x", r)
		default:
			fmt.Fprintf(&out, "\\U%08x", r)
		}
	}
	out.WriteRune(quote)
	return out.String()
}
