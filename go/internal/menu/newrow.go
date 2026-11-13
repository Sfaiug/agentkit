package menu

import (
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

// Model keeps the screen's transient state together, independent of readings and drawing.
type Model struct {
	Highlight Highlight
	New       *Draft
}

// Draft is the new seat's name and models until Enter starts it or Esc drops it.
type Draft struct {
	Typed, Hint, Orchestrator string
	Workers, Reviewers        []string
	Names                     []string
	Models                    map[string]config.Model
	Levels                    map[string][]string
	Taken                     map[string]bool
	Picker                    bool
	At, Column                int
	Find                      string
}

func NewDraft(hint string, taken map[string]bool) (*Draft, error) {
	d := &Draft{Hint: hint, Taken: taken, Levels: map[string][]string{}}
	var err error
	if d.Orchestrator, err = config.DefaultOrchestrator(); err != nil {
		return nil, err
	}
	if d.Workers, d.Reviewers, err = config.Groups(); err != nil {
		return nil, err
	}
	if d.Reviewers == nil {
		d.Reviewers = d.Workers
	}
	d.Workers, d.Reviewers = slices.Clone(d.Workers), slices.Clone(d.Reviewers)
	if len(d.Reviewers) == 0 {
		d.Reviewers = []string{d.Orchestrator}
	}
	if d.Names, err = config.Offered(); err != nil {
		return nil, err
	}
	d.At = max(0, slices.Index(d.Names, d.Orchestrator))
	if d.Models, err = config.Models(); err != nil {
		return nil, err
	}
	for name, model := range d.Models {
		d.Levels[name], _ = config.Efforts(model.Harness, model.ID)
	}
	return d, nil
}

func (d *Draft) Name() string {
	if d.Typed == "" {
		return d.Hint
	}
	return config.SessionName(d.Typed)
}

func (d *Draft) Refusal() string {
	if d.Taken[d.Name()] {
		return "a seat is called " + d.Name() + " already"
	}
	if d.Name() == "" {
		return "a session needs a name"
	}
	return ""
}

// Key changes only this draft. Its result is the action the screen must carry out.
func (d *Draft) Key(key terminal.Key) string {
	if d.Picker {
		return d.pickerKey(key)
	}
	switch key.Name {
	case "esc", "eof":
		return key.Name
	case "tab":
		d.Picker, d.Find = true, ""
		return "models"
	case "enter":
		return "start"
	case "backspace":
		d.Typed = d.Typed[:max(0, len(d.Typed)-1)]
	case "space", "char":
		char := strings.ToLower(key.Char)
		if key.Name == "space" {
			char = "-"
		}
		if len(d.Typed) < 40 && len(char) == 1 && strings.ContainsRune("abcdefghijklmnopqrstuvwxyz0123456789_-", rune(char[0])) {
			d.Typed += char
		}
	}
	return ""
}

func (view View) withNew() View {
	d := view.New
	if d == nil {
		return view
	}
	caret := "▏"
	if view.Screen.ASCII() {
		caret = "_"
	}
	name := d.Typed + caret
	if d.Typed == "" {
		name = caret + d.Hint
	}
	number := 1
	for _, each := range view.Seats {
		number = max(number, each.Number+1)
	}
	view.Seats = append(slices.Clone(view.Seats), Seat{Number: number, Name: name,
		Model: config.ModelAt(d.Orchestrator, "effort", d.Models), Alone: config.ModelName(d.Orchestrator, d.Models),
		Word: "new", draft: d})
	view.Highlight = Highlight{Cursor: name, Open: true}
	view.Keys = "⏎ start   tab models   esc back"
	if view.Screen.ASCII() {
		view.Keys = "enter start   tab models   esc back"
	}
	return view
}

// The draft is always last and has its own heading, even when other seats are unfiled.
func projects(seats []Seat) []project {
	if last := len(seats) - 1; last >= 0 && seats[last].draft != nil {
		return append(grouped(seats[:last]), project{seats: seats[last:]})
	}
	return grouped(seats)
}

func (d *Draft) block(s terminal.Screen, seat Seat, w widths) []row {
	caret, hint, typed := "▏", "", d.Typed
	if s.ASCII() {
		caret = "_"
	}
	if typed == "" {
		hint = terminal.Cut(d.Hint, max(0, w.name-1))
	} else {
		typed = typed[max(0, len(typed)-max(0, w.name-1)):]
	}
	name := padded(s.Bold(typed)+s.Styled(caret, "accent")+s.Styled(hint, "dim"), w.name)
	line := "  " + terminal.Pad(strconv.Itoa(seat.Number), w.num) + "  " + name + "  " + cell(s, seat.orchestrator(w.orch), w.orch, "dim")
	if w.count > 0 {
		line += "  " + s.Styled("new", "dim")
	}
	lines := []row{{strings.TrimRight(line, " "), seat.Name}}
	indent := strings.Repeat(" ", 2+w.num+2)
	if w.count == 0 {
		lines = append(lines, row{indent + s.Styled("new", "dim"), seat.Name})
	}
	named := func(names []string, effort string) []string {
		var shown []string
		for _, name := range names {
			shown = append(shown, config.ModelAt(name, effort, d.Models))
		}
		return shown
	}
	room := max(1, w.room-len(indent))
	parts, tone := []string{terminal.CutSpaced(terminal.Crew(seat.Model, named(d.Workers, "exec_effort"), named(d.Reviewers, "review_effort")), room)}, "dim"
	if why := d.Refusal(); why != "" {
		parts, tone = terminal.Wrap(why, room), "amber"
	}
	for _, part := range parts {
		lines = append(lines, row{indent + s.Styled(part, tone), seat.Name})
	}
	return lines
}

func padded(text string, room int) string {
	return text + strings.Repeat(" ", max(0, room-terminal.Cells(text)))
}

func (d *Draft) marks(name string) [3]bool {
	return [3]bool{name == d.Orchestrator, slices.Contains(d.Workers, name) || len(d.Workers) == 0 && name == d.Orchestrator,
		slices.Contains(d.Reviewers, name)}
}

func (d *Draft) mark() {
	name := d.Names[d.At]
	if d.Column == 0 {
		d.Orchestrator = name
		return
	}
	group := &d.Workers
	if d.Column == 2 {
		group = &d.Reviewers
		if len(*group) == 1 && (*group)[0] == name {
			return
		}
	}
	if at := slices.Index(*group, name); at >= 0 {
		*group = slices.Delete(*group, at, at+1)
	} else {
		*group = append(*group, name)
	}
}

func (d *Draft) pickerKey(key terminal.Key) string {
	switch key.Name {
	case "esc":
		d.Picker = false
	case "eof":
		return "eof"
	case "enter":
		return "start"
	case "up", "down":
		by := 1
		if key.Name == "up" {
			by = -1
		}
		d.At = max(0, min(len(d.Names)-1, d.At+by))
		d.Find = ""
	case "left":
		d.move(-1)
	case "right":
		d.move(1)
	case "space":
		if d.Column >= 3 {
			d.step()
		} else {
			d.mark()
		}
	case "backspace":
		d.Find = d.Find[:max(0, len(d.Find)-1)]
	case "char":
		d.Find += strings.ToLower(key.Char)
		for at, name := range d.Names {
			if strings.EqualFold(name, d.Find) || strconv.Itoa(at+1) == d.Find {
				d.At, d.Orchestrator = at, name
				break
			}
		}
	}
	d.keepColumn()
	return ""
}
