package seat

import (
	"cmp"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/screen"
)

// loginHint is an error that may be a login: it is never typed past (watch.LOGIN_HINT).
var loginHint = regexp.MustCompile(`(?i)/login\b|\b(?:log[ -]?in|sign[ -]in|logged out|expired|revoked|unauthori[sz]ed|401|403)\b|\b(?:authentication|authorization) (?:failed|required)\b`)

// stallOn is the error the tick would type this seat back past, nil for none (watch.stall_mark and
// stalled_on).  Where its harness keeps a record, what that recorded last says, whatever it says;
// else its screen's last line, which only counts drawn as the harness draws its own notices.
func (seen eye) stallOn(own, pane, tail, recorded string, kept bool) any {
	marks, _ := config.Words(own, "stall", "signatures")
	said := recorded
	if !kept {
		said = outputLine(seen.rules.Said(tail))
	}
	if loginHint.MatchString(said) {
		return nil
	}
	first := func(text string) string {
		for _, mark := range marks {
			if harness.Says(text, mark) {
				return mark
			}
		}
		return ""
	}
	if kept {
		word, _ := harness.Failure(own, recorded)
		word = cmp.Or(word, first(recorded), config.Fold(recorded))
		if word == "" {
			return nil
		}
		return word
	}
	lines := seen.rules.Said(tail)
	if len(lines) == 0 {
		return nil
	}
	last := lines[len(lines)-1]
	if block, _ := config.Section(own, "stall"); block["coloured"] == true && !inOwnColour(pane, lines, marks) {
		return nil
	}
	mark := first(last)
	if mark == "" {
		return nil
	}
	if word, spent := harness.Failure(own, last); spent {
		return word
	}
	return mark
}

// inOwnColour is whether the last of those lines is drawn wholly in a colour where the pane has
// attributes, as the answer styles spans of its own too; where it has none, whether the line
// begins with a stall word behind its mark, as a sentence about one names it further on.
func inOwnColour(pane string, lines, marks []string) bool {
	last := lines[len(lines)-1]
	if whole, attributes := screen.LastInColour(pane, len(lines)-1, last); attributes {
		return whole
	}
	said := strings.ToLower(strings.TrimLeftFunc(strings.TrimLeftFunc(last, func(r rune) bool {
		return !wordRune(r) && !config.Space(r)
	}), config.Space))
	for _, mark := range marks {
		if strings.HasPrefix(said, strings.ToLower(mark)) {
			return true
		}
	}
	return false
}

// loginOn is the harness's words for an expired login this seat shows, nil for none
// (watch.auth_expired_on): its own lines, wrapped ones too, and never quoted prose; in what it
// recorded last, where it keeps a record, as that holds no prose to quote.
func (seen eye) loginOn(own, tail, recorded string, kept bool) any {
	signatures, _ := config.Words(own, "auth", "signatures")
	if kept {
		for _, mark := range signatures {
			if harness.Says(recorded, mark) {
				return mark
			}
		}
		if seen.wrapper != nil {
			if found := seen.wrapper.FindString(recorded); found != "" {
				return found
			}
		}
		return nil
	}
	stalls, _ := config.Words(own, "stall", "signatures")
	has := func(line string, marks []string) bool {
		for _, mark := range marks {
			if strings.Contains(strings.ToLower(line), strings.ToLower(mark)) {
				return true
			}
		}
		return false
	}
	lines := seen.rules.Said(tail)
	// a capacity error can accompany a logout, and the login still wins over resuming that error
	for len(lines) > 0 && has(lines[len(lines)-1], stalls) && !has(lines[len(lines)-1], signatures) {
		lines = seen.rules.Said(strings.Join(lines[:len(lines)-1], "\n"))
	}
	for _, mark := range signatures {
		whole, err := screen.Pattern(`\A(?:[●■⎿✕!]\s*)?(?:Error:\s*)?`+regexp.QuoteMeta(mark)+`(?:, url: https?://\S+)?\z`, "(?i)")
		if err != nil {
			continue
		}
		for start := range lines {
			if whole.MatchString(config.Fold(strings.Join(lines[start:], " "))) {
				return mark
			}
		}
	}
	if seen.wrapper != nil {
		if found := seen.wrapper.FindString(outputLine(lines)); found != "" {
			return found
		}
	}
	return nil
}

// outputLine is the latest output line without prompt text or quotes (watch.output_line).
func outputLine(lines []string) string {
	if len(lines) == 0 || promptOpened.MatchString(lines[len(lines)-1]) {
		return ""
	}
	line := lines[len(lines)-1]
	var kept strings.Builder
	for at := 0; at < len(line); {
		if end := quotedEnd(line, at); end > at {
			at = end
			continue
		}
		_, size := utf8.DecodeRuneInString(line[at:])
		kept.WriteString(line[at : at+size])
		at += size
	}
	return kept.String()
}

// quotedEnd is where the quotation opening at that place of the line ends, or that place: a
// back-quoted or double-quoted span, or a single-quoted one standing apart from a word, which is
// an apostrophe otherwise.
func quotedEnd(line string, at int) int {
	opening, size := utf8.DecodeRuneInString(line[at:])
	closing, ok := map[rune]rune{'`': '`', '"': '"', '“': '”', '\'': '\''}[opening]
	if !ok {
		return at
	}
	end := strings.IndexRune(line[at+size:], closing)
	if end < 0 {
		return at
	}
	end += at + size + utf8.RuneLen(closing)
	if opening == '\'' {
		before, _ := utf8.DecodeLastRuneInString(line[:at])
		after, _ := utf8.DecodeRuneInString(line[end:])
		if at > 0 && wordRune(before) || end < len(line) && wordRune(after) {
			return at
		}
	}
	return end
}

func wordRune(r rune) bool { return unicode.IsLetter(r) || unicode.IsNumber(r) || r == '_' }
