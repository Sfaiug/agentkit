package menu

import (
	"slices"
	"strings"

	"agentkit/internal/terminal"
)

// A List is a choice picked on a screen of its own (terminal.choose): under its title, Over's lines,
// then each choice on a line of its own, then Under's.
type List struct {
	Title, Clock string
	Over, Under  []string
	Choices      []string            // by name, as Frame.Open answers them
	Text         func(string) string // a choice as drawn, its name where nil
	Warn         string              // the choice drawn in the warn colour: the one that ends something
	Enter        func(string) string // what Enter does on the choice lit, named on the key line
}

// Frame is the list drawn: the choice the highlight is on lit while the pointer is not away from
// it, and the key line naming what Enter does there; nothing is lit while it is on no choice.
func (l List) Frame(s terminal.Screen, h Highlight) Frame {
	frame := Frame{order: l.Choices, hidden: h.Hidden, width: s.Width(), height: s.Height(), spots: make([]string, 2+len(l.Over))}
	if slices.Contains(l.Choices, h.Cursor) {
		frame.cursor = h.Cursor
	}
	body := slices.Clone(l.Over)
	for _, choice := range l.Choices {
		text := choice
		if l.Text != nil {
			text = l.Text(choice)
		}
		line := terminal.Cut(text, s.Width()-3)
		if choice == l.Warn {
			line = s.Styled(line, "amber")
		}
		line = "  " + line
		if choice == frame.cursor && !h.Hidden {
			line = s.Highlight(line, true)
		}
		body, frame.spots = append(body, line), append(frame.spots, choice)
	}
	enter := ""
	if frame.cursor != "" {
		enter = l.Enter(frame.cursor)
	}
	frame.Lines = Panel(s, l.Title, l.Clock, append(body, l.Under...), pageKeys(s, enter))
	return frame
}

// Confirm is the card every yes-or-no question is asked on (terminal.confirm): the question, what
// answer means dim, then `✓ Keep`, which the highlight starts on, and `× <answer>` in the warn
// colour, Enter named for the one lit.
func Confirm(s terminal.Screen, title, clock, question, meaning, answer string) List {
	keep, end := "✓ Keep", "× "+answer
	if s.ASCII() {
		keep, end = "v Keep", "x "+answer
	}
	card := []string{""}
	for i, text := range []string{question, meaning} {
		for _, line := range terminal.Wrap(text, s.LayoutWidth()-2) {
			if i == 1 {
				line = s.Styled(line, "dim")
			}
			card = append(card, "  "+line)
		}
	}
	return List{Title: title, Clock: clock, Over: card, Under: []string{""}, Choices: []string{"Keep", answer}, Warn: answer,
		Text:  func(choice string) string { return map[string]string{"Keep": keep, answer: end}[choice] },
		Enter: strings.ToLower}
}
