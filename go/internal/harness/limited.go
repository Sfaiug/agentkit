package harness

import (
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/config"
)

// limits are the words that say a rate limit, Python's harness.LIMITS.
var limits = []string{"429", "too many requests", "rate~limit", "rate~limited", "rate~limit~error"}

// Limited is whether text says a rate limit, whole, as Python's harness.limited reads it.
func Limited(text string) bool {
	for _, word := range limits {
		if says(text, word) {
			return true
		}
	}
	return false
}

// wordClass is what Python's \w matches.
var (
	wordClass = `[\p{L}\p{N}_]`
	words     = wordClass + `+`
	// what a path runs over: anything but Python's \s and the marks that end a path in a line
	pathed = `[^` + config.SpaceClass[1:len(config.SpaceClass)-1] + `"'` + "`" + `{}<>,:;|]*`
	// paths and file names with their line references, run ids, and a traceback's `", line 429`
	paths    = regexp.MustCompile(`(?:` + pathed + `/` + pathed + `|(?:[A-Za-z]:\\|\\\\)` + pathed + `)(?::\p{Nd}+)*`)
	files    = regexp.MustCompile(words + `(?:[-.]` + words + `)*\.[A-Za-z]` + wordClass + `*(?:[-.]` + words + `)*(?::\p{Nd}+)*`)
	runIDs   = regexp.MustCompile(`\p{Nd}{8}-\p{Nd}{4,6}(?:-[\p{L}\p{N}_.]+)+`)
	slugIDs  = regexp.MustCompile(`\p{Nd}{8}-\p{Nd}{4,6}(?:-[a-z0-9]+)+`)
	lines    = regexp.MustCompile(`line \p{Nd}+`)
	numbers  = regexp.MustCompile(`\p{Nd}+`)
	wordChar = func(r rune) bool { return unicode.IsLetter(r) || unicode.IsNumber(r) || r == '_' }
)

// says is whether text says word on its own, as Python's harness.says reads a word of one part:
// never inside a longer word, nor its digits inside a longer number, a file path or a run id, nor
// a word without digits inside a run id.  A `#` in it is any one digit, a `~` up to three
// characters that are neither letters nor digits, or none.
func says(text, word string) bool {
	word = strings.TrimFunc(word, config.Space)
	if word == "" {
		return false
	}
	var pattern strings.Builder
	pattern.WriteString("(?i)")
	for _, r := range word {
		switch r {
		case '#':
			pattern.WriteString(`\p{Nd}`)
		case '~':
			pattern.WriteString(`[^\p{L}\p{N}]{0,3}`)
		default:
			pattern.WriteString(regexp.QuoteMeta(string(r)))
		}
	}
	first, _ := utf8.DecodeRuneInString(word)
	last, _ := utf8.DecodeLastRuneInString(word)
	lead, trail := wordChar(first) || first == '#', wordChar(last) || last == '#'
	found := spans(regexp.MustCompile(pattern.String()), text, func(start, end int) bool {
		return (!lead || !joinedBefore(text, start)) && (!trail || !joinedAfter(text, end))
	})
	// what a match inside does not count in: a word with digits, its numbers; one without, whole
	digits := strings.ContainsFunc(word, func(r rune) bool { return r == '#' || unicode.IsDigit(r) })
	var ignored [][2]int
	if digits {
		ignored = append(ignored, spans(paths, text, nil)...)
		ignored = append(ignored, spans(files, text, bounded(text))...)
		ignored = append(ignored, spans(runIDs, text, bounded(text))...)
		ignored = append(ignored, spans(lines, text, func(start, _ int) bool { return strings.HasSuffix(text[:start], `", `) })...)
	} else {
		ignored = spans(slugIDs, text, bounded(text))
	}
	for _, match := range found {
		inner := [][2]int{match}
		if digits {
			inner = nil
			for _, number := range numbers.FindAllStringIndex(text[match[0]:match[1]], -1) {
				inner = append(inner, [2]int{match[0] + number[0], match[0] + number[1]})
			}
		}
		for _, part := range inner {
			if !within(part, ignored) {
				return true
			}
		}
	}
	return false
}

// spans is each match of re in text that ok takes, nil for every one, as Python's re.finditer
// finds them when ok is the pattern's own lookaround: a match ok refuses is tried again one
// character on.
func spans(re *regexp.Regexp, text string, ok func(start, end int) bool) [][2]int {
	var found [][2]int
	for at := 0; at <= len(text); {
		loc := re.FindStringIndex(text[at:])
		if loc == nil {
			break
		}
		start, end := at+loc[0], at+loc[1]
		if ok == nil || ok(start, end) {
			found = append(found, [2]int{start, end})
			if end > start {
				at = end
				continue
			}
		}
		_, size := utf8.DecodeRuneInString(text[start:])
		at = start + max(size, 1)
	}
	return found
}

// bounded is Python's leading \b before a word character: none just before.
func bounded(text string) func(start, end int) bool {
	return func(start, _ int) bool {
		r, _ := utf8.DecodeLastRuneInString(text[:start])
		return start == 0 || !wordChar(r)
	}
}

// joinedBefore is whether the match at start follows a word character or a digit and a dot, which
// Python's (?<!\w)(?<!\d\.) refuse.
func joinedBefore(text string, start int) bool {
	r, size := utf8.DecodeLastRuneInString(text[:start])
	if start == 0 {
		return false
	}
	if r == '.' {
		previous, _ := utf8.DecodeLastRuneInString(text[:start-size])
		return start-size > 0 && unicode.IsDigit(previous)
	}
	return wordChar(r)
}

// joinedAfter is whether a word character, or a dot and a digit, follows the match ending at end,
// which Python's (?!\w)(?!\.\d) refuse.
func joinedAfter(text string, end int) bool {
	r, size := utf8.DecodeRuneInString(text[end:])
	if end == len(text) {
		return false
	}
	if r == '.' {
		next, _ := utf8.DecodeRuneInString(text[end+size:])
		return end+size < len(text) && unicode.IsDigit(next)
	}
	return wordChar(r)
}

// within is whether part lies inside one of spans.
func within(part [2]int, spans [][2]int) bool {
	for _, span := range spans {
		if span[0] <= part[0] && part[1] <= span[1] {
			return true
		}
	}
	return false
}
