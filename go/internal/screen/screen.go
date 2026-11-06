// Package screen reads what a harness has drawn: handed a harness's rules and its pane, it says
// which state that screen shows and the rule that said so, as Python's watch.screen_state does.
// It hides which rows a rule may read (a tray, a view scrolled away, the rule framing a footer, a
// composer's draft above them), the attributes that tell typed text from a faint suggestion, how
// far a composer goes, and the order rules are tried in.  It names no harness, captures no pane
// and writes no record: every fact about a harness is its manifest's, so another one comes in by
// its manifest alone.
package screen

import (
	"fmt"
	"math/big"
	"regexp"
	"slices"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/lifecycle"
	"agentkit/internal/pyre"
)

// A Reading is the state a screen shows, the rule that matched and the line it stands on; all
// empty where no rule matched.
type Reading struct{ State, Rule, Evidence string }

// Rules are one harness's `[screen]` chrome and `[[rule]]` list, compiled.
type Rules struct {
	composer, footer, tray *pyre.Regexp // each reads a whole row
	away, scrolled, draft  *pyre.Regexp
	held                   *pyre.Regexp // the background work it draws running
	ruled, boxed, scrolls  bool
	faint                  []string
	rules                  []rule
}

type rule struct {
	id, state         string
	lines             int
	all, some, none   []string
	row, rows, newest *pyre.Regexp
	atComposer        bool
}

// tailRows is how much of a pane's tail says what it is doing (watch.PANE_LINES).
const tailRows = 15

// ruleRow is a row of box-drawing, as every harness draws one (watch.RULE).
const ruleRow = `[─━═\-╭╮╰╯┌┐└┘]+`

var (
	bareRule   = regexp.MustCompile(`^` + ruleRow + `$`)
	bareFooter = regexp.MustCompile(`(?i)^(?:` + ruleRow + `|[>›❯])$`)
	// the marks a prompt row opens on, and one read at its start after a box's edge
	promptRow = regexp.MustCompile(`^(?:│` + config.SpaceClass + `*)?[❯›⟩]`)
	markAt    = regexp.MustCompile(`^` + config.SpaceClass + `*(?:│` + config.SpaceClass + `*)?([❯›⟩])`)
	typed     = regexp.MustCompile(`^(?:│` + config.SpaceClass + `*)?[❯›⟩]` + config.SpaceClass + `*(.*)$`)
)

// Compile reads a harness's `[screen]` table and `[[rule]]` list.  An error is a rule Python's
// would refuse, or one the engine cannot say: nothing of that harness can be read.
func Compile(chrome map[string]any, rules []map[string]any) (*Rules, error) {
	var parts []string
	listed, _ := chrome["footer"].([]any)
	for _, part := range listed {
		if part, ok := part.(string); ok {
			parts = append(parts, "(?:"+part+")")
		}
	}
	read := Rules{ruled: chrome["ruled"] == true, boxed: chrome["boxed"] == true, scrolls: chrome["scrolls"] == true}
	if listed, ok := chrome["faint"].([]any); ok {
		for _, colour := range listed {
			if colour, ok := colour.(string); ok {
				read.faint = append(read.faint, colour)
			}
		}
	}
	footer := ""
	if len(parts) > 0 {
		footer = "(?:" + strings.Join(parts, "|") + ")$"
	}
	for _, each := range []struct {
		into   **pyre.Regexp
		source any
		whole  bool
		flags  pyre.Flag
	}{{&read.composer, chrome["composer"], true, 0}, {&read.footer, footer, true, pyre.IgnoreCase}, {&read.tray, chrome["tray"], true, 0},
		{&read.away, chrome["away"], false, 0}, {&read.scrolled, chrome["scrolled"], false, 0}, {&read.draft, chrome["draft"], false, pyre.Multiline},
		{&read.held, chrome["held"], false, pyre.Multiline}} {
		var err error
		if *each.into, err = pattern(each.source, each.flags, each.whole); err != nil {
			return nil, err
		}
	}
	for _, entry := range rules {
		compiled, err := compileRule(entry)
		if err != nil {
			return nil, err
		}
		read.rules = append(read.rules, compiled)
	}
	return &read, nil
}

func compileRule(entry map[string]any) (rule, error) {
	found := rule{lines: 8, atComposer: entry["at_composer"] == true}
	found.state, _ = entry["state"].(string)
	if !slices.Contains(lifecycle.Live, found.state) {
		return rule{}, fmt.Errorf("every rule needs a state, not %v", entry["state"])
	}
	found.id, _ = entry["id"].(string)
	if found.id == "" {
		found.id = found.state
	}
	if lines, set := entry["lines"]; set {
		count, ok := lines.(*big.Int)
		if !ok || !count.IsInt64() {
			return rule{}, fmt.Errorf("rule %s: lines must be a whole number", found.id)
		}
		found.lines = int(max(1, count.Int64()))
	}
	found.all, found.some, found.none = marks(entry["all"]), marks(entry["any"]), marks(entry["none"])
	var err error
	if found.row, err = pattern(entry["row"], 0, false); err != nil {
		return rule{}, err
	}
	if found.rows, err = pattern(entry["rows"], pyre.Multiline, false); err != nil {
		return rule{}, err
	}
	found.newest, err = pattern(entry["newest"], 0, false)
	return found, err
}

// pattern is a `[screen]` or `[[rule]]` pattern, nil where none is written; `whole` has it read a
// whole row, as Python's fullmatch.
func pattern(value any, flags pyre.Flag, whole bool) (*pyre.Regexp, error) {
	if value == nil || value == "" {
		return nil, nil
	}
	source, ok := value.(string)
	if !ok {
		return nil, fmt.Errorf("a pattern must be text, not %v", value)
	}
	if whole {
		source = `\A(?:` + source + `)\Z`
	}
	return pyre.Compile(source, flags)
}

func marks(value any) (folded []string) {
	listed, _ := value.([]any)
	for _, mark := range listed {
		folded = append(folded, strings.ToLower(fmt.Sprint(mark)))
	}
	return folded
}

// Tail is the last rows of a pane's content: a harness can leave blank space above its composer
// (watch.pane_tail).
func Tail(pane string) string {
	rows := contentRows(pane)
	return strings.Join(lastOf(rows, tailRows), "\n")
}

// Read is the first rule, in the manifest's order, that the pane's tail matches.
func (r *Rules) Read(pane string) Reading {
	tail := Tail(pane)
	raws := contentRows(tail)
	if len(raws) == 0 {
		return Reading{}
	}
	lines := plains(raws)
	// A view scrolled up from its live bottom shows none of what a rule reads there, however much
	// of it the rows left look like one; the row holding its pill is never the composer's.
	if r.away != nil && len(lines) > 1 && r.drawnRule(lines[len(lines)-1]) && r.away.MatchString(lines[len(lines)-2]) {
		if _, end := r.ruledComposer(raws); end != len(lines)-1 {
			return Reading{}
		}
	}
	raws, lines = r.withoutTray(raws, lines)
	newest := r.newestRow(raws, lines)
	reach := r.reach(pane, raws)
	for _, each := range r.rules {
		region, rows := lastOf(lines, each.lines), lastOf(raws, each.lines)
		if each.id == "prompt.draft" || each.id == "prompt.suggestion" {
			if found, ok := r.atComposer(each, rows, region, reach); ok {
				return found
			}
			continue
		}
		var drawn []string
		together := make([]string, len(rows))
		for at, raw := range rows {
			together[at] = strings.TrimRightFunc(strip(raw), config.Space)
			if each.row != nil && each.row.MatchString(together[at]) {
				drawn = append(drawn, region[at])
			}
		}
		whole := strings.Join(together, "\n")
		low := strings.ToLower(whole)
		contains := func(mark string) bool { return strings.Contains(low, mark) }
		if len(each.all) > 0 && !allOf(each.all, contains) || len(each.some) > 0 && !slices.ContainsFunc(each.some, contains) ||
			slices.ContainsFunc(each.none, contains) || each.row != nil && len(drawn) == 0 ||
			each.rows != nil && !each.rows.MatchString(whole) || each.newest != nil && !each.newest.MatchString(newest) ||
			each.atComposer && !r.chromeLine(lines[len(lines)-1]) {
			continue
		}
		said := newest
		if len(drawn) > 0 {
			said = drawn[len(drawn)-1]
		}
		named := slices.Concat(each.all, each.some)
		for _, line := range slices.Backward(region) {
			if slices.ContainsFunc(named, func(mark string) bool { return strings.Contains(strings.ToLower(line), mark) }) {
				said = line
				break
			}
		}
		if each.state == "draft" && (r.draft != nil || each.atComposer) {
			if words := r.draftWords(each, tail, len(raws)); words != "" {
				said = words
			}
		}
		return Reading{each.state, each.id, cut(said)}
	}
	return Reading{}
}

// withoutTray leaves out a tray drawn under the footer, or between composer and footer: every rule
// reads the rows it reads where none is drawn, and never further up the transcript.
func (r *Rules) withoutTray(raws, lines []string) ([]string, []string) {
	if r.tray == nil {
		return raws, lines
	}
	at := len(lines)
	for at > 1 && r.tray.MatchString(lines[at-1]) {
		at--
	}
	if at < len(lines) && r.chromeLine(lines[at-1]) {
		raws, lines = raws[:at], lines[:at]
	}
	if r.chromeLine(lines[len(lines)-1]) {
		at = len(lines) - 1
		for at > 0 && r.tray.MatchString(lines[at-1]) {
			at--
		}
		raws = append(slices.Clone(raws[:at]), raws[len(raws)-1])
		lines = append(slices.Clone(lines[:at]), lines[len(lines)-1])
	}
	return raws, lines
}

// newestRow is the row a rule's `newest` reads: the bottom one, unless that is the frame ruled
// right under a row drawn at the left edge, which would hide a question's own footer.  A draft
// never sits there: its first row is prompt-marked and the rest are indented or inside a box.
func (r *Rules) newestRow(raws, lines []string) string {
	newest := lines[len(lines)-1]
	if !r.ruled || len(lines) < 2 || !r.drawnRule(newest) {
		return newest
	}
	above := strings.TrimRightFunc(strip(raws[len(raws)-2]), config.Space)
	first, _ := utf8.DecodeRuneInString(above)
	if above != "" && !config.Space(first) && !strings.ContainsRune("│┃║❯›⟩>", first) &&
		!r.drawnRule(strings.TrimFunc(above, config.Space)) {
		return lines[len(lines)-2]
	}
	return newest
}

// drawnRule is a bare rule, or one the harness's chrome names, as one carrying a session's name.
func (r *Rules) drawnRule(row string) bool {
	first, _ := utf8.DecodeRuneInString(row)
	return bareRule.MatchString(row) || strings.ContainsRune("─━═", first) && r.chromeLine(row)
}

// chromeLine is whether the line is the harness's composer or footer, rather than anything it
// said; read only after Python's Unicode strip, as `❯` and U+00A0 is its empty composer.
func (r *Rules) chromeLine(line string) bool {
	plain := Plain(line)
	return bareFooter.MatchString(plain) || r.footer != nil && r.footer.MatchString(plain) ||
		r.composer != nil && r.composer.MatchString(plain)
}

func allOf(marks []string, contains func(string) bool) bool {
	return !slices.ContainsFunc(marks, func(mark string) bool { return !contains(mark) })
}

func lastOf(rows []string, count int) []string {
	return rows[max(0, len(rows)-count):]
}

// cut is what evidence keeps of a line: its first 160 characters.
func cut(line string) string {
	if utf8.RuneCountInString(line) <= 160 {
		return line
	}
	return string([]rune(line)[:160])
}
