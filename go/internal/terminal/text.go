package terminal

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
	"unicode"
)

type span struct{ lo, hi rune }

var ansi = regexp.MustCompile(`\x1b\[[0-?]*[ -/]*[@-~]`)

func within(spans []span, r rune) bool {
	at := sort.Search(len(spans), func(i int) bool { return spans[i].hi >= r })
	return at < len(spans) && spans[at].lo <= r
}

func cell(r rune) int {
	switch {
	case within(combining, r):
		return 0
	case within(wide, r):
		return 2
	}
	return 1
}

// space is a character Python's str.split() splits on: Go's White_Space and the
// four information separators.
func space(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// Cells is the columns a terminal gives text, its colour escapes taking none.
func Cells(text string) int {
	total := 0
	for _, r := range ansi.ReplaceAllString(text, "") {
		total += cell(r)
	}
	return total
}

// Plain is text with no escape or other control character, on one line, one space between its words.
func Plain(text string) string {
	var kept strings.Builder
	text = ansi.ReplaceAllString(text, "")
	for i, r := range text {
		// a byte that is no UTF-8 is a lone surrogate to Python, a control like any other
		invalid := r == unicode.ReplacementChar && !strings.HasPrefix(text[i:], "\uFFFD")
		if !invalid && (space(r) || !unicode.In(r, unicode.C)) {
			kept.WriteRune(r)
		}
	}
	return strings.Join(strings.FieldsFunc(kept.String(), space), " ")
}

// Cut fits text in room with one ellipsis, preferring a word boundary at most four
// columns before the cut.
func Cut(text string, room int) string {
	text = Plain(text)
	if Cells(text) <= room {
		return text
	}
	if room <= 0 {
		return ""
	}
	runes := []rune(text)
	end, used := 0, 0
	for _, r := range runes {
		used += cell(r)
		if used > room-1 {
			break
		}
		end++
	}
	prefix := string(runes[:end])
	boundary := strings.LastIndex(prefix, " ")
	if end < len(runes) && runes[end] != ' ' && boundary > 0 && Cells(prefix[boundary:]) <= 4 {
		prefix = prefix[:boundary]
	}
	return strings.TrimRight(prefix, " ") + "…"
}

// Wrap breaks text at words, splitting only a word that cannot fit on a line by itself.
func Wrap(text string, room int) []string {
	room = max(1, room)
	var lines []string
	line := ""
	for _, word := range strings.Split(Plain(text), " ") {
		if word == "" {
			continue
		}
		if line != "" && Cells(line+" "+word) > room {
			lines = append(lines, line)
			line = ""
		}
		for Cells(word) > room {
			runes := []rune(word)
			end, used := 0, 0
			for _, r := range runes {
				if used+cell(r) > room {
					break
				}
				used += cell(r)
				end++
			}
			if end == 0 { // a wide glyph cannot fit in a one-column terminal
				end = 1
			}
			if used > 0 {
				lines = append(lines, string(runes[:end]))
			} else {
				lines = append(lines, "…")
			}
			word = string(runes[end:])
		}
		if word != "" {
			if line != "" {
				line += " " + word
			} else {
				line = word
			}
		}
	}
	if line != "" {
		lines = append(lines, line)
	}
	return lines
}

// TitleLines is a title in at most two lines: wrapped once at a word, cut with ` …` past that.
func TitleLines(text string, room int) []string {
	room = max(1, room)
	lines := Wrap(text, room)
	if len(lines) <= 2 {
		return lines
	}
	tail := Cut(strings.Join(lines[1:], " "), room-1)
	if strings.HasSuffix(tail, "…") {
		tail = strings.TrimRight(strings.TrimSuffix(tail, "…"), " ") + " …"
	}
	return []string{lines[0], tail}
}

// FormatAge is `<1m`, `5m`, `2h` or `3d`: never seconds, on every screen.
func FormatAge(seconds float64) string {
	secs := max(0, int64(seconds))
	switch {
	case secs < 60:
		return "<1m"
	case secs < 3600:
		return fmt.Sprintf("%dm", secs/60)
	case secs < 86400:
		return fmt.Sprintf("%dh", secs/3600)
	}
	return fmt.Sprintf("%dd", secs/86400)
}
