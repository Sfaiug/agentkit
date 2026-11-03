// Package pyre compiles a pattern written for Python's re, with Python's flags, and matches as
// Python's re.search matches it.  It hides the backtracking engine it runs on (regexp2, vendored:
// Go's own regexp has no lookaround or backreference), how Python's syntax is said to that engine
// (named groups, `\Z`, `{,n}`, the classes and word edges Python reads over all of Unicode, and the
// letters Python's ignore case pairs beyond upper and lower case), and that the engine counts runes
// where every offset here is a byte of the Go string.
package pyre

import (
	"fmt"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/dlclark/regexp2"
)

// A Flag is one of Python's re flags.
type Flag int

const (
	IgnoreCase Flag = 1 << iota // re.I
	Multiline                   // re.M
)

// A Regexp is one compiled pattern, and the same pattern refusing to match empty where its search
// starts (\G), as Python's re.finditer searches again where an empty match ended.
type Regexp struct{ engine, advancing *regexp2.Regexp }

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

// Python's word edge, \b, its \w on one side alone, and \B, on both or neither, never in an empty
// text: the engine's own read its \w.
var word = `[` + sets['w'] + `]`
var edges = map[byte]string{'b': `(?:(?<=` + word + `)(?!` + word + `)|(?<!` + word + `)(?=` + word + `))`,
	'B': `(?!\A\z)(?:(?<=` + word + `)(?=` + word + `)|(?<!` + word + `)(?!` + word + `))`}

// The lower case letters Python's re pairs under ignore case (re._compiler's _EXTRA_CASES), each
// matching all of its own: the engine pairs only a letter's upper and lower case.  Those a
// normalising editor would make one letter are escaped.
var pairs = []string{"iı", "sſ", "µμ", "\u0345\u03b9\u1fbe", "\u0390\u1fd3", "\u03b0\u1fe3", "βϐ", "εϵ",
	"θϑ", "κϰ", "πϖ", "ρϱ", "σς", "φϕ", "вᲀ", "дᲁ", "оᲂ", "сᲃ", "тᲄᲅ", "ъᲆ", "ѣᲇ", "ꙋᲈ", "ṡẛ", "ﬅﬆ"}

// flagged is a group that sets flags, Python's `(?i)` and `(?i-m:`.
var flagged = regexp.MustCompile(`^\(\?([aiLmsux]*)(?:-([imsx]*))?([:)])`)

// Python refuses to repeat an anchor, which the engine repeats: `\b*`, `^{2}`.
var anchors = []string{"^", "$", `\A`, `\Z`, `\b`, `\B`}
var repeat = regexp.MustCompile(`^(?:[*+?]|\{(?:\d+|\d*,\d*)\})`)

// Compile is Python's re.compile(pattern, flags); an error where Python's would refuse it, or
// where the engine has no way to say it.
func Compile(pattern string, flags Flag) (*Regexp, error) {
	said, err := translated(pattern, flags&IgnoreCase != 0)
	if err != nil {
		return nil, fmt.Errorf("%q: %w", pattern, err)
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
	// `)(?#\n)` closes the group once whether or not the pattern ends in a verbose comment
	advancing, err := regexp2.Compile("(?:"+said+")(?#\n)"+`(?!\G)`, options)
	if err != nil {
		return nil, fmt.Errorf("%q: %w", pattern, err)
	}
	return &Regexp{engine, advancing}, nil
}

// The flags translating reads, as each group that sets them changes them until the group closes.
type scope struct{ folding, verbose bool }

// translated is a Python pattern in the engine's syntax; folding is whether it ignores case where
// it opens.
func translated(source string, folding bool) (string, error) {
	var out strings.Builder
	flags := scope{folding: folding}
	var outer []scope // the flags around each open group
	anchored := false // the last item is an anchor
	for at, size := 0, 0; at < len(source); at += size {
		rest := source[at:]
		if anchored && repeat.MatchString(rest) {
			return "", fmt.Errorf("nothing to repeat")
		}
		size = 1
		switch {
		case rest[0] == '\\' && len(rest) > 1:
			size = 2
			switch set, complement := sets[rest[1]], sets[rest[1]|0x20]; {
			case set != "":
				out.WriteString("[" + set + "]")
			case complement != "":
				out.WriteString("[^" + complement + "]")
			case edges[rest[1]] != "":
				out.WriteString(edges[rest[1]])
			case rest[1] == 'Z':
				out.WriteString(`\z`)
			default:
				char, length, known, err := atom(rest, false)
				if err != nil {
					return "", err
				}
				if size = length; known {
					out.WriteString(folded(char, flags.folding, quoted(char)))
				} else {
					out.WriteString(rest[:size])
				}
			}
		case rest[0] == '[':
			said, length, err := class(rest, flags.folding)
			if err != nil {
				return "", err
			}
			out.WriteString(said)
			size = length
		case strings.HasPrefix(rest, "(?#"):
			// a comment, to its first `)` not escaped as Python reads it: no escape in it is
			// translated, and the engine, ending one at any `)`, sees it empty
			for size = 3; size < len(rest) && rest[size] != ')'; size++ {
				if rest[size] == '\\' {
					size++
				}
			}
			if size >= len(rest) {
				return "", fmt.Errorf("missing ), unterminated comment")
			}
			out.WriteString("(?#)")
			size++
		case flags.verbose && rest[0] == '#':
			// a verbose comment, to its line's end as Python reads it, empty for the same reason
			for ; size < len(rest) && rest[size] != '\n'; size++ {
				if rest[size] == '\\' {
					size++
				}
			}
			size = min(size, len(rest))
			out.WriteByte('#')
		case flagged.MatchString(rest):
			set := flagged.FindStringSubmatch(rest)
			if set[3] == ":" {
				outer = append(outer, flags)
			}
			on := func(was bool, flag string) bool {
				return strings.Contains(set[1], flag) || was && !strings.Contains(set[2], flag)
			}
			flags = scope{on(flags.folding, "i"), on(flags.verbose, "x")}
			out.WriteString(set[0])
			size = len(set[0])
		case strings.HasPrefix(rest, "(?P<"):
			// the name as written, never a letter of it folded
			name, _, _ := strings.Cut(rest[4:], ">")
			out.WriteString("(?<" + name + ">")
			size = 4 + len(name) + 1
			outer = append(outer, flags)
		case strings.HasPrefix(rest, "(?("):
			// a conditional's group, its name as written
			name, _, closed := strings.Cut(rest[3:], ")")
			if !closed {
				return "", fmt.Errorf("missing ), unterminated name")
			}
			out.WriteString("(?(" + name + ")")
			size = 3 + len(name) + 1
			outer = append(outer, flags)
		case strings.HasPrefix(rest, "(?P="):
			name, _, _ := strings.Cut(rest[4:], ")")
			out.WriteString(`\k<` + name + `>`)
			size = 4 + len(name) + 1
		case rest[0] == '(':
			out.WriteByte('(')
			outer = append(outer, flags)
		case rest[0] == ')' && len(outer) > 0:
			out.WriteByte(')')
			flags, outer = outer[len(outer)-1], outer[:len(outer)-1]
		case strings.HasPrefix(rest, "{,") && strings.HasPrefix(strings.TrimLeft(rest[2:], "0123456789"), "}"):
			// Python's {,n} is {0,n}; the engine reads it as text
			out.WriteString("{0")
		default:
			var char rune
			char, size = utf8.DecodeRuneInString(rest)
			out.WriteString(folded(char, flags.folding, rest[:size]))
		}
		// a comment, or a space read verbose, between an anchor and a repeat leaves the anchor last
		switch item := rest[:size]; {
		case slices.Contains(anchors, item):
			anchored = true
		case !strings.HasPrefix(item, "(?#") && !(flags.verbose && strings.ContainsAny(item[:1], "# \t\n\r\v\f")):
			anchored = false
		}
	}
	return out.String(), nil
}

// atom is the one character source opens with, an escape read as Python reads it in a class or
// out of one, and the bytes it takes; known is false for an escape that names no one character (a
// set, a group's number); err is Python's refusal of an octal escape past one byte.
func atom(source string, inClass bool) (char rune, size int, known bool, err error) {
	if source[0] != '\\' || len(source) == 1 {
		char, size = utf8.DecodeRuneInString(source)
		return char, size, true, nil
	}
	switch next := source[1]; {
	case strings.IndexByte("xuU", next) >= 0:
		size = 2 + map[byte]int{'x': 2, 'u': 4, 'U': 8}[next]
		if size > len(source) {
			return 0, 2, false, nil
		}
		code, bad := strconv.ParseUint(source[2:size], 16, 32)
		return rune(code), size, bad == nil, nil
	case '0' <= next && next <= '7':
		// octal: in a class always, out of one from a 0 or as three digits, else a group's number
		digits := source[1:min(len(source), 4)]
		digits = digits[:len(digits)-len(strings.TrimLeft(digits, "01234567"))]
		if !inClass && next != '0' && len(digits) < 3 {
			return 0, 2, false, nil
		}
		code, _ := strconv.ParseUint(digits, 8, 32)
		if code > 0o377 {
			return 0, 0, false, fmt.Errorf("octal escape value \\%s outside of range 0-0o377", digits)
		}
		return rune(code), 1 + len(digits), true, nil
	case strings.IndexByte("abfnrtv", next) >= 0:
		return rune("\a\b\f\n\r\t\v"[strings.IndexByte("abfnrtv", next)]), 2, true, nil
	case next >= utf8.RuneSelf || !alphanumeric(next):
		char, size = utf8.DecodeRuneInString(source[1:])
		return char, 1 + size, true, nil
	}
	return 0, 2, false, nil
}

// class is the `[...]` that source opens with, as the engine says it, and the bytes it takes.  A
// \S or \W in it is a set apart, as no class of the engine's can hold Python's complement.
func class(source string, folding bool) (string, int, error) {
	at := 1
	negated := strings.HasPrefix(source[at:], "^")
	if negated {
		at++
	}
	var members strings.Builder
	var apart []string
	var chars []rune
	for first := true; at < len(source) && (first || source[at] != ']'); first = false {
		low, size, known, err := atom(source[at:], true)
		if err != nil {
			return "", 0, err
		}
		set, complement := sets[source[at+size-1]], sets[source[at+size-1]|0x20]
		switch at += size; {
		case len(source[at:]) > 1 && source[at] == '-' && source[at+1] != ']':
			// a range, as Python reads one, whatever its ends; a set at either is a bad one
			high, size, highKnown, err := atom(source[at+1:], true)
			if err != nil {
				return "", 0, err
			}
			if !known || !highKnown || high < low {
				return "", 0, fmt.Errorf("bad character range")
			}
			for char := low; char <= high; char++ {
				chars = append(chars, char)
			}
			at += 1 + size
		case known:
			chars = append(chars, low)
		case set != "":
			members.WriteString(set)
		case complement != "":
			apart = append(apart, "[^"+complement+"]")
		default:
			members.WriteString(source[at-size : at])
		}
	}
	if at == len(source) {
		return "", 0, fmt.Errorf("unterminated character set")
	}
	if folding {
		// each character stands as the lower case letters ignoring case takes it for, as the
		// engine lowers the text it reads and its own lowering of a range misses most of Unicode
		var lowered []rune
		for _, char := range chars {
			lowered = append(lowered, paired(char)...)
		}
		chars = lowered
	}
	slices.Sort(chars)
	chars = slices.Compact(chars)
	for from := 0; from < len(chars); {
		to := from
		for to+1 < len(chars) && chars[to+1] == chars[to]+1 {
			to++
		}
		members.WriteString(quoted(chars[from]))
		if to > from {
			members.WriteString("-" + quoted(chars[to]))
		}
		from = to + 1
	}
	switch {
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

// paired is every lower case letter Python's ignore case takes char for.
func paired(char rune) []rune {
	lower := unicode.ToLower(char)
	for _, group := range pairs {
		if strings.ContainsRune(group, lower) {
			return []rune(group)
		}
	}
	return []rune{lower}
}

// folded is char outside a class: a class of the letters ignoring case pairs it with, where it
// has any, else as said.
func folded(char rune, folding bool, said string) string {
	if group := paired(char); folding && len(group) > 1 {
		return "[" + string(group) + "]"
	}
	return said
}

// quoted is char as the engine reads it as itself wherever it stands, in a class or out of one:
// any ASCII but a letter in hex, as a bare digit would lengthen a group's number or make a count,
// and a bare newline end a comment.
func quoted(char rune) string {
	if char < utf8.RuneSelf && !unicode.IsLetter(char) {
		return fmt.Sprintf(`\x%02x`, char)
	}
	return string(char)
}

func alphanumeric(char byte) bool {
	return 'a' <= char|0x20 && char|0x20 <= 'z' || '0' <= char && char <= '9'
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
	runes := []rune(text)
	var found []Match
	// no search past the n-th match: it costs work, exponential on some patterns, for nothing
	search, at := r.engine, 0
	for len(found) != n {
		// an error is only a timeout, and none is set
		match, _ := search.FindRunesMatchStartingAt(runes, at)
		if match == nil {
			break
		}
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
		search, at = r.engine, match.Index+match.Length
		if match.Length == 0 {
			search = r.advancing
		}
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
