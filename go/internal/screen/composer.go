package screen

import (
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
)

// atComposer is what a draft or suggestion rule reads: only the composer, so a transcript echoing
// a past turn can never read as one, and what a harness draws between composer and footer, a
// user's status line, never hides it or reads as it; false where it does not match.  `reach` is
// every row up the pane a ruled composer's draft may go on in.
func (r *Rules) atComposer(each rule, raws, region, reach []string) (Reading, bool) {
	low := strings.ToLower(strings.Join(mapped(raws, func(raw string) string {
		return strings.TrimRightFunc(strip(raw), config.Space)
	}), "\n"))
	if slices.ContainsFunc(each.none, func(mark string) bool { return strings.Contains(low, mark) }) {
		return Reading{}, false
	}
	marked := promptRows(raws)
	end := -1
	switch {
	case each.atComposer && r.ruled:
		// its box from its prompt row, in the rule's own rows or up from them, under the footer at
		// the pane's bottom, or with none drawn a prompt row right on that bottom
		raws, region = upToPrompt(reach, len(region))
		var at int
		at, end = r.ruledComposer(raws)
		if at >= 0 && !r.chromeLine(region[len(region)-1]) {
			at = -1
		} else if at < 0 && promptRow.MatchString(region[len(region)-1]) {
			at, end = len(region)-1, len(region)
		}
		marked = nil
		if at >= 0 {
			marked = []int{at}
		}
	case each.atComposer:
		marked, end = r.unruledComposer(marked, raws, region)
	}
	if len(marked) == 0 {
		return Reading{}, false
	}
	at := marked[0]
	if end < 0 {
		end = at + 1
	}
	if each.id == "prompt.draft" {
		draft := strings.Join(r.composerParts(raws, region, at, end), " ")
		return Reading{each.state, each.id, cut(draft)}, draft != ""
	}
	return Reading{each.state, each.id, cut(region[at])}, r.suggested(raws[at], region[at])
}

// unruledComposer is the prompt rows a composer with no rule of its own may open on, bottom-most
// first, and where its first ends: a line with a rule right under it first, else one on the
// footer; a draft a wrap took past its prompt row goes on in indented rows down to that chrome.
func (r *Rules) unruledComposer(marked []int, raws, region []string) ([]int, int) {
	under := func(index int) int {
		for row := index + 1; row < len(region); row++ {
			if r.chromeLine(region[row]) {
				return row
			}
			if first, _ := utf8.DecodeRuneInString(strip(raws[row])); !config.Space(first) {
				return -1
			}
		}
		return -1
	}
	marked = slices.DeleteFunc(slices.Clone(marked), func(index int) bool {
		return index+1 != len(region) && (under(index) < 0 || !r.chromeLine(region[len(region)-1]))
	})
	if ruled := slices.DeleteFunc(slices.Clone(marked), func(index int) bool {
		return index+1 >= len(region) || !bareRule.MatchString(region[index+1])
	}); len(ruled) > 0 {
		marked = ruled
	}
	if len(marked) == 0 || marked[0]+1 == len(region) {
		return marked, -1
	}
	return marked, under(marked[0])
}

// promptRows are the rows a composer's mark can open, bottom-most first: of those opening on a
// mark, the ones whose mark sits furthest left.  A draft's later rows are indented past it.
func promptRows(rows []string) []int {
	columns := map[int]int{}
	left := -1
	for at, row := range rows {
		plain := strings.TrimRightFunc(strip(row), config.Space)
		if found := markAt.FindStringSubmatchIndex(plain); found != nil {
			columns[at] = utf8.RuneCountInString(plain[:found[2]])
			if left < 0 || columns[at] < left {
				left = columns[at]
			}
		}
	}
	var marked []int
	for at := len(rows) - 1; at >= 0; at-- {
		if column, has := columns[at]; has && column == left {
			marked = append(marked, at)
		}
	}
	return marked
}

// ruledComposer is the prompt row and closing rule of the composer a ruled harness draws, -1 for
// both where it draws none: the bottom-most prompt row whose first chrome row under it is a bare
// rule, so a user's status line under that rule is never the composer.  Only rows at the left edge
// are its prompt row and its chrome: nothing typed is ever the box.
func (r *Rules) ruledComposer(rows []string) (int, int) {
	if !r.ruled {
		return -1, -1
	}
	cells := mapped(rows, func(row string) string {
		cell := strip(row)
		if rest, inBox := strings.CutPrefix(cell, "│"); inBox {
			first, size := utf8.DecodeRuneInString(rest)
			cell = rest
			if rest != "" && config.Space(first) {
				cell = rest[size:]
			}
		}
		return strings.TrimRightFunc(cell, config.Space)
	})
	for at := len(cells) - 1; at >= 0; at-- {
		if first, _ := utf8.DecodeRuneInString(cells[at]); !strings.ContainsRune("❯›⟩", first) {
			continue
		}
		end := len(cells)
		for row := at + 1; row < len(cells); row++ {
			if !strings.HasPrefix(cells[row], " ") && r.chromeLine(cells[row]) {
				end = row
				break
			}
		}
		if end < len(cells) && bareRule.MatchString(cells[end]) {
			return at, end
		}
	}
	return -1, -1
}

// composerParts is what is typed in a composer from its prompt row down to `stop`, a part a row,
// none empty: bright text only, and a box's edges, chrome on every row, left out.
func (r *Rules) composerParts(raws, rows []string, at, stop int) []string {
	boxed := strings.HasPrefix(rows[at], "│") && strings.HasSuffix(rows[at], "│")
	bright := r.brightRows(raws)
	first := bright[at]
	if boxed {
		first = strings.TrimRightFunc(strings.TrimSuffix(first, "│"), config.Space)
	}
	parts := []string{r.draftText(first)}
	for _, plain := range bright[at+1 : min(stop, len(bright))] {
		if boxed {
			plain = insideBox(plain)
		}
		parts = append(parts, plain)
	}
	return slices.DeleteFunc(parts, func(part string) bool { return part == "" })
}

// draftText is typed, unsent text after the prompt mark, or "": only a line starting at the prompt
// holds one, and one the composer's pattern fullmatches holds nothing the owner typed.
func (r *Rules) draftText(plain string) string {
	found := typed.FindStringSubmatch(plain)
	if found == nil || strings.TrimFunc(found[1], config.Space) == "" || r.composer != nil && r.composer.MatchString(plain) {
		return ""
	}
	return config.Fold(found[1])
}

func insideBox(row string) string {
	if row == "│" {
		return ""
	}
	if strings.HasPrefix(row, "│") && strings.HasSuffix(row, "│") {
		return strings.TrimFunc(row[len("│"):len(row)-len("│")], config.Space)
	}
	return row
}

// suggested is whether the composer's content is faint alone: a suggestion, treated as empty.
func (r *Rules) suggested(raw, plain string) bool {
	runs, _ := r.faintRuns(raw, faintState{})
	drawn := slices.ContainsFunc(runs, func(each faintRun) bool {
		return each.faint && strings.TrimFunc(each.text, config.Space) != ""
	})
	found := typed.FindStringSubmatch(plain)
	return drawn && found != nil && strings.TrimFunc(found[1], config.Space) != ""
}

// A faintRun is a row's text between two codes; a faintState what tmux carries from row to row:
// faint is SGR 2, muted a foreground its harness draws only placeholders in (`[screen] faint`).
type (
	faintRun struct {
		text            string
		faint, reversed bool
	}
	faintState struct{ faint, muted bool }
)

// sgrCodes are one sequence's codes: an extended colour comes out whole, the `2` inside it naming
// a colour and never faint, and a bare `m` is a reset.
func sgrCodes(params string) (extended []string, codes []int, order []bool) {
	parts := strings.Split(params, ";")
	if params == "" {
		parts = []string{"0"}
	}
	for at := 0; at < len(parts); at++ {
		if (parts[at] == "38" || parts[at] == "48") && at+1 < len(parts) && (parts[at+1] == "5" || parts[at+1] == "2") {
			size := 3
			if parts[at+1] == "2" {
				size = 5
			}
			end := min(at+size, len(parts))
			extended = append(extended, strings.Join(parts[at:end], ";"))
			order = append(order, true)
			at = end - 1
			continue
		}
		if code, err := strconv.Atoi(parts[at]); err == nil {
			codes = append(codes, code)
			order = append(order, false)
		}
	}
	return extended, codes, order
}

func (r *Rules) faintRuns(raw string, state faintState) ([]faintRun, faintState) {
	reversed := false
	var runs []faintRun
	at := 0
	for _, found := range sgrSeq.FindAllStringSubmatchIndex(raw, -1) {
		runs = append(runs, faintRun{raw[at:found[0]], state.faint || state.muted, reversed})
		extended, codes, order := sgrCodes(raw[found[2]:found[3]])
		for _, isRun := range order {
			if isRun {
				if strings.HasPrefix(extended[0], "38;") {
					state.muted = slices.Contains(r.faint, extended[0])
				}
				extended = extended[1:]
				continue
			}
			code := codes[0]
			codes = codes[1:]
			switch code {
			case 2:
				state.faint = true
			case 0, 22:
				state.faint = false
			}
			switch code {
			case 7:
				reversed = true
			case 0, 27:
				reversed = false
			}
			if code == 0 || code == 39 || code >= 30 && code <= 37 || code >= 90 && code <= 97 {
				state.muted = false
			}
		}
		at = found[1]
	}
	return append(runs, faintRun{raw[at:], state.faint || state.muted, reversed}), state
}

// brightRows is each raw row as plain text, its faint text blanked: what is left is what was
// typed, a suggestion drawn on after it none of it, nor the cursor's reversed cell on its first
// letter.
func (r *Rules) brightRows(raws []string) []string {
	state := faintState{}
	return mapped(raws, func(raw string) string {
		var runs []faintRun
		runs, state = r.faintRuns(raw, state)
		var shown []int
		for at, each := range runs {
			if Plain(each.text) != "" {
				shown = append(shown, at)
			}
		}
		under := map[int]bool{}
		for at := 0; at+1 < len(shown); at++ {
			if runs[shown[at]].reversed && runs[shown[at+1]].faint {
				under[shown[at]] = true
			}
		}
		var row strings.Builder
		for at, each := range runs {
			if each.faint || under[at] {
				row.WriteString(strings.Repeat(" ", utf8.RuneCountInString(each.text)))
			} else {
				row.WriteString(each.text)
			}
		}
		return Plain(row.String())
	})
}

// draftWords is what the composer holds where a rule other than the draft rule found a draft: the
// owner reads its words, read as watch._composer_rows does; a full tail can leave its prompt above
// the read.
func (r *Rules) draftWords(each rule, tail string, rows int) string {
	parts, found := r.composerRows(tail)
	if !found && each.atComposer && each.row != nil && rows >= tailRows {
		parts = r.croppedRows(tail)
	}
	return strings.Join(parts, " ")
}

// composerRows are the rows of text in the composer, from its prompt row down to the chrome under
// it; false where none is found.
func (r *Rules) composerRows(pane string) ([]string, bool) {
	if r.boxed {
		pane = cutBoxes(pane)
	}
	raws := contentRows(Tail(pane))
	rows := plains(raws)
	if r.draft != nil {
		return r.framedRows(pane, rows)
	}
	marked := promptRows(raws)
	at, stop := -1, -1
	if len(marked) > 0 {
		at, stop = marked[0], len(rows)
		for row := at + 1; row < len(rows); row++ {
			if r.chromeLine(rows[row]) {
				stop = row
				break
			}
		}
	}
	if r.ruled {
		at, stop = r.ruledComposer(raws)
		if at < 0 && len(marked) > 0 && marked[0]+1 == len(rows) {
			at, stop = marked[0], len(rows)
		}
	}
	if at < 0 {
		return nil, false
	}
	return r.unscrolled(r.composerParts(raws, rows, at, stop)), true
}

// framedRows is a composer no mark finds: its manifest finds the framed block it holds, read as
// drawn, the tail's blank rows among them; finding none reads as empty only where the composer's
// own row is on the screen.
func (r *Rules) framedRows(pane string, rows []string) ([]string, bool) {
	drawn := mapped(config.SplitLines(pane), func(row string) string {
		return strings.TrimRightFunc(strip(row), config.Space)
	})
	var top []int
	for at, row := range drawn {
		if strings.TrimFunc(row, config.Space) != "" {
			top = append(top, at)
		}
	}
	source := ""
	if top = top[max(0, len(top)-tailRows):]; len(top) > 0 {
		source = strings.Join(drawn[top[0]:], "\n")
	}
	found := r.draft.FindAll(source, -1)
	if len(found) == 0 && (r.composer == nil || !slices.ContainsFunc(rows, r.composer.MatchString)) {
		return nil, false
	}
	var parts []string
	for _, match := range found {
		edge, _ := match.Group("edge")
		text, ok := match.Group("text")
		if !ok {
			return nil, false
		}
		for _, row := range config.SplitLines(text) {
			runes := []rune(row)
			parts = append(parts, strings.TrimFunc(string(runes[min(utf8.RuneCountInString(edge), len(runes)):]), config.Space))
		}
	}
	return r.unscrolled(parts), true
}

// croppedRows is a composer whose top is above the read: every row over its bottom chrome is its
// text.
func (r *Rules) croppedRows(pane string) []string {
	if r.boxed {
		pane = cutBoxes(pane)
	}
	return r.unscrolled(mapped(r.Said(Tail(pane)), insideBox))
}

// unscrolled is those rows without what a harness draws on a composer scrolled past its height
// (`[screen] scrolled`), none left empty.
func (r *Rules) unscrolled(rows []string) []string {
	var kept []string
	for _, row := range rows {
		if r.scrolled != nil {
			row = r.scrolled.RemoveAll(row)
		}
		if strings.TrimFunc(row, config.Space) != "" {
			kept = append(kept, row)
		}
	}
	return kept
}

// cutBoxes is the capture with each row cut where a box drawn on it ends: where, after cells on
// another background, the background of its first cell comes back.  What is drawn beside a
// composer on its own background, a sidebar, is none of it (watch._boxed).
func cutBoxes(pane string) string {
	back := ""
	rows := mapped(config.SplitLines(pane), func(raw string) string {
		first, away, cut, at := true, false, -1, 0
		start := ""
		look := func(upto int) {
			if cut >= 0 || raw[at:upto] == "" {
				return
			}
			switch {
			case first:
				start, first = back, false
			case back != start:
				away = true
			case away:
				cut = at
			}
		}
		for _, found := range sgrAll.FindAllStringIndex(raw, -1) {
			look(found[0])
			at = found[1]
			sgr := sgrSeq.FindStringSubmatch(raw[found[0]:found[1]])
			if sgr == nil || len(sgr[0]) != found[1]-found[0] {
				continue
			}
			extended, codes, order := sgrCodes(sgr[1])
			for _, isRun := range order {
				if isRun {
					if strings.HasPrefix(extended[0], "48;") {
						back = extended[0]
					}
					extended = extended[1:]
					continue
				}
				code := codes[0]
				codes = codes[1:]
				switch {
				case code == 0 || code == 49:
					back = ""
				case code >= 40 && code <= 47 || code >= 100 && code <= 107:
					back = strconv.Itoa(code)
				}
			}
		}
		look(len(raw))
		if cut >= 0 {
			return raw[:cut]
		}
		return raw
	})
	return strings.Join(rows, "\n")
}

func mapped(rows []string, each func(string) string) []string {
	out := make([]string, len(rows))
	for at, row := range rows {
		out[at] = each(row)
	}
	return out
}
