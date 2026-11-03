// Package pyre compiles a pattern written for Python's re, with Python's flags, and matches as
// Python's re.search matches it.  It hides the backtracking engine it runs on (regexp2, vendored:
// Go's own regexp has no lookaround or backreference), how Python's syntax is said to that engine
// (named groups, `\Z`, `{,n}`, and the classes and word edge Python reads over all of Unicode),
// and that the engine counts runes where every offset here is a byte of the Go string.
package pyre

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/dlclark/regexp2"
)

// A Flag is one of Python's re flags.
type Flag int

const (
	IgnoreCase Flag = 1 << iota // re.I
	Multiline                   // re.M
)

// A Regexp is one compiled pattern.
type Regexp struct{ engine *regexp2.Regexp }

// A Match is where a pattern matched, in bytes, and its named groups.
type Match struct {
	Start, End int
	Text       string
	named      map[string]*string
}

// Group is the text a named group took, false where it took part in no match.
func (m Match) Group(name string) (string, bool) {
	text := m.named[name]
	if text == nil {
		return "", false
	}
	return *text, true
}

// Python's \s and \w, as members of a class: the engine's own classes read other characters.
var sets = map[byte]string{'s': `\t\n\v\f\r\x1c-\x1f \x85\p{Z}`, 'w': `\p{L}\p{N}_`}

// edge is Python's word edge, \b, its \w on one side alone; the engine's own reads its \w.
var edge = `(?:(?<=[` + sets['w'] + `])(?![` + sets['w'] + `])|(?<![` + sets['w'] + `])(?=[` + sets['w'] + `]))`

// Compile is Python's re.compile(pattern, flags); an error where Python's would refuse it, or
// where the engine has no way to say it.
func Compile(pattern string, flags Flag) (*Regexp, error) {
	said, err := translated(pattern)
	if err != nil {
		return nil, err
	}
	options := regexp2.None
	if flags&IgnoreCase != 0 {
		options |= regexp2.IgnoreCase
	}
	if flags&Multiline != 0 {
		options |= regexp2.Multiline
	}
	engine, err := regexp2.Compile(said, options)
	if err != nil {
		return nil, fmt.Errorf("%q: %w", pattern, err)
	}
	return &Regexp{engine}, nil
}

// translated is a Python pattern in the engine's syntax.
func translated(source string) (string, error) {
	var out strings.Builder
	for at := 0; at < len(source); at++ {
		char, rest := source[at], source[at+1:]
		switch {
		case char == '\\' && rest != "":
			at++
			switch set, complement := sets[rest[0]], sets[rest[0]|0x20]; {
			case set != "":
				out.WriteString("[" + set + "]")
			case complement != "":
				out.WriteString("[^" + complement + "]")
			case rest[0] == 'b':
				out.WriteString(edge)
			case rest[0] == 'Z':
				out.WriteString(`\z`)
			default:
				out.WriteString(source[at-1 : at+1])
			}
		case char == '[':
			said, length, err := class(source[at:])
			if err != nil {
				return "", fmt.Errorf("%q: %w", source, err)
			}
			out.WriteString(said)
			at += length - 1
		case char == '(' && strings.HasPrefix(rest, "?P<"):
			out.WriteString("(?<")
			at += 3
		case char == '(' && strings.HasPrefix(rest, "?P="):
			name, _, _ := strings.Cut(rest[3:], ")")
			out.WriteString(`\k<` + name + `>`)
			at += 3 + len(name) + 1
		case strings.HasPrefix(source[at:], "{,") && strings.HasPrefix(strings.TrimLeft(source[at+2:], "0123456789"), "}"):
			// Python's {,n} is {0,n}; the engine reads it as text
			out.WriteString("{0")
		default:
			out.WriteByte(char)
		}
	}
	return out.String(), nil
}

// class is the `[...]` that source opens with, as the engine says it, and the bytes it takes.  A
// \S or \W in it is a set apart, as no class of the engine's can hold Python's complement.
func class(source string) (string, int, error) {
	at := 1
	negated := strings.HasPrefix(source[at:], "^")
	if negated {
		at++
	}
	var members strings.Builder
	var apart []string
	for first := true; at < len(source) && (first || source[at] != ']'); at, first = at+1, false {
		switch char := source[at]; {
		case char == '\\' && at+1 < len(source):
			at++
			switch set, complement := sets[source[at]], sets[source[at]|0x20]; {
			case set != "":
				members.WriteString(set)
			case complement != "":
				apart = append(apart, "[^"+complement+"]")
			default:
				members.WriteString(source[at-1 : at+1])
			}
		case char == '[' || char == ']':
			// a member to Python, a `]` as the first; to the engine `-[` opens a subtraction
			members.WriteString(`\` + string(char))
		default:
			members.WriteByte(char)
		}
	}
	switch {
	case at == len(source):
		return "", 0, fmt.Errorf("unterminated character set")
	case len(apart) == 0 && negated:
		return "[^" + members.String() + "]", at + 1, nil
	case len(apart) == 0:
		return "[" + members.String() + "]", at + 1, nil
	case negated:
		return "", 0, fmt.Errorf(`no negated class here can hold \S or \W`)
	case members.Len() > 0:
		apart = append([]string{"[" + members.String() + "]"}, apart...)
	}
	return "(?:" + strings.Join(apart, "|") + ")", at + 1, nil
}

// MatchString is whether the pattern matches anywhere in text.
func (r *Regexp) MatchString(text string) bool {
	return r.Find(text) != nil
}

// FindString is the text of the first match, "" for none.
func (r *Regexp) FindString(text string) string {
	if found := r.Find(text); found != nil {
		return found.Text
	}
	return ""
}

// Find is the first match, Python's re.search; nil for none.
func (r *Regexp) Find(text string) *Match {
	found := r.FindAll(text, 1)
	if len(found) == 0 {
		return nil
	}
	return &found[0]
}

// FindAll is the first n matches, every one for n < 0, as Python's re.finditer finds them.
func (r *Regexp) FindAll(text string, n int) []Match {
	// the byte each rune starts at, the engine's offsets read as an index, and the end
	var bytes []int
	for at := range text {
		bytes = append(bytes, at)
	}
	bytes = append(bytes, len(text))
	var found []Match
	// an error is only a timeout, and none is set
	match, _ := r.engine.FindStringMatch(text)
	for ; match != nil && n != 0; n-- {
		start, end := bytes[match.Index], bytes[match.Index+match.Length]
		each := Match{Start: start, End: end, Text: text[start:end], named: map[string]*string{}}
		for _, group := range match.Groups() {
			// the engine names a numbered group by its number, which no Python name can be
			if _, numbered := strconv.Atoi(group.Name); numbered != nil && len(group.Captures) > 0 {
				taken := text[bytes[group.Index]:bytes[group.Index+group.Length]]
				each.named[group.Name] = &taken
			}
		}
		found = append(found, each)
		match, _ = r.engine.FindNextMatch(match)
	}
	return found
}

// RemoveAll is Python's re.sub(pattern, "", text): text without any match.
func (r *Regexp) RemoveAll(text string) string {
	var kept strings.Builder
	at := 0
	for _, match := range r.FindAll(text, -1) {
		kept.WriteString(text[at:match.Start])
		at = match.End
	}
	return kept.String() + text[at:]
}
