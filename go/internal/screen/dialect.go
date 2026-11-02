package screen

import (
	"fmt"
	"regexp"
	"strings"

	"agentkit/internal/config"
)

// A manifest's patterns are written for Python's `re`, whose classes read all of Unicode where
// Go's read ASCII alone, so `\s` would miss the U+00A0 a composer draws.  Each form here is the
// class Python means, as it stands alone and as it stands inside `[...]`; "" where Go cannot say
// it there.  `\b` stays Go's, an ASCII edge: it differs only with a non-ASCII letter against a
// manifest's word, which no harness draws.
var classes = map[byte][2]string{
	's': {config.SpaceClass, strings.Trim(config.SpaceClass, "[]")},
	'S': {"[^" + strings.Trim(config.SpaceClass, "[]") + "]", ""},
	'w': {`[\p{L}\p{N}_]`, `\p{L}\p{N}_`},
	'W': {`[^\p{L}\p{N}_]`, ""},
	'd': {`\p{Nd}`, `\p{Nd}`},
	'D': {`\P{Nd}`, `\P{Nd}`},
}

// said is a Python pattern's classes as Go says them; false where one has no way to be said.
func said(source string) (string, bool) {
	var out strings.Builder
	inClass := false
	for at := 0; at < len(source); at++ {
		switch char := source[at]; {
		case char == '\\' && at+1 < len(source):
			at++
			form, known := classes[source[at]]
			switch {
			case !known:
				out.WriteByte(char)
				out.WriteByte(source[at])
			case !inClass:
				out.WriteString(form[0])
			case form[1] == "":
				return "", false
			default:
				out.WriteString(form[1])
			}
		case char == '[' && !inClass:
			inClass = true
			out.WriteByte(char)
			// a `]` right here is a member of the class, in both dialects
			if strings.HasPrefix(source[at+1:], "^") {
				at++
				out.WriteByte('^')
			}
			if strings.HasPrefix(source[at+1:], "]") {
				at++
				out.WriteByte(']')
			}
		case char == ']':
			inClass = false
			out.WriteByte(char)
		default:
			out.WriteByte(char)
		}
	}
	return out.String(), true
}

// Pattern is one of a manifest's patterns, for Python's re.search; an error where Go cannot say
// it, a look-around among others.
func Pattern(source, flags string) (*regexp.Regexp, error) {
	translated, ok := said(source)
	if !ok {
		return nil, fmt.Errorf("Go cannot say %q", source)
	}
	return regexp.Compile(flags + translated)
}

// pattern is a `[screen]` or `[[rule]]` pattern, nil where none is written; `whole` has it read a
// whole row, as Python's fullmatch.
func pattern(value any, flags string, whole bool) (*regexp.Regexp, error) {
	if value == nil || value == "" {
		return nil, nil
	}
	source, ok := value.(string)
	if !ok {
		return nil, fmt.Errorf("a pattern must be text, not %v", value)
	}
	if whole {
		translated, ok := said(source)
		if !ok {
			return nil, fmt.Errorf("Go cannot say %q", source)
		}
		return regexp.Compile(flags + `\A(?:` + translated + `)\z`)
	}
	return Pattern(source, flags)
}
