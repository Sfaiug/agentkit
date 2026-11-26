package cli

import (
	"context"
	"slices"
	"strings"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/machines"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// menuMachines is `Machines` on `c` (menu.config_machines), from the tick's records alone: a row
// for every machine ak may use, this one first, Enter opening its work but on this one's.  Last,
// `+ add a machine` takes an ssh address, with the line that makes a new machine ready under its
// field, and adds the machine once it answers, else says why not (machines.Ask, machines.Add);
// Esc while it is asked goes back, nothing written.
func menuMachines(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	join := sync.OnceValues(machines.JoinLine) // made as the field first opens: it makes ak's key
	add := menu.PageRow{Label: "+ add a machine", Field: func(typed string) string {
		name := strings.TrimFunc(typed, config.Space)
		if name == "" {
			return ""
		}
		why, err := waitAdapter("config · machines", "asking "+name, nil, keyboard, painter, func(ctx context.Context) (string, error) {
			return machines.Ask(ctx, name), nil
		})
		if err != nil || why != "" {
			return why // gone back, or it did not answer: nothing written
		}
		return saved(machines.Add(name, seat.KeepConfigEfforts))
	}, Placeholder: "its ssh address: a Host of ~/.ssh/config, a host name or user@host",
		Around: func(s terminal.Screen) []string {
			line, err := join()
			words := "Run this on a new Linux machine, then type above the address it prints:"
			if err != nil {
				words = "The line that makes a new machine ready cannot be made: " + config.PyError(err)
			}
			lines := []string{""}
			for _, part := range terminal.Wrap(words, s.LayoutWidth()-4) {
				lines = append(lines, s.Styled("    "+part, "dim"))
			}
			if err != nil {
				return lines
			}
			return append(lines, s.Unbroken("    "+line)...)
		}}
	return configPage("machines", "", func() ([]menu.PageRow, bool) {
		if config.Check() != nil { // a file that will not load closes the page, saying why on `c`
			return nil, false
		}
		var rows []menu.PageRow
		for _, machine := range machines.Known() {
			work, known := workWords(machine)
			if !known {
				return nil, false
			}
			row := menu.PageRow{Label: machine.Name, Value: machine.Overview() + " · " + work}
			if machine.Name != machines.Here {
				row.Open = func() bool { return menuMachineWork(machine.Name, keyboard, painter) }
			}
			rows = append(rows, row)
		}
		return append(rows, add), true
	}, keyboard, painter)
}

// menuMachineWork is `config · machines · <name>`: a mark for each work a machine may take,
// Space flipping it, saved at once, but builds and reviews on a Mac.  Each draw and each flip reads
// the machine afresh, as a probe may land while the page is open.
func menuMachineWork(name string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	return configPage("machines · "+name, "", func() ([]menu.PageRow, bool) {
		work, known := machines.Named(name).Work()
		if !known {
			return nil, false
		}
		var rows []menu.PageRow
		for _, mark := range [][2]string{{"turns", "builds and reviews"}, {"tests", "tests"}} {
			on, value := slices.Contains(work, mark[0]), "off"
			if on {
				value = "on"
			}
			rows = append(rows, menu.PageRow{Label: mark[1], Value: value, On: on, Flip: func() string { return flipWork(name, mark[0]) }})
		}
		return rows, true
	}, keyboard, painter)
}

// flipWork saves the machine's marks with `word` flipped, refusing, nothing written, marks it
// could not take as saved (menu.config_machines' flip).  Marks that cannot be read Save refuses.
func flipWork(name, word string) string {
	machine := machines.Named(name)
	work, _ := machine.Work()
	flipped := slices.DeleteFunc([]string{"turns", "tests"}, func(each string) bool {
		return slices.Contains(work, each) == (each == word)
	})
	if !slices.Equal(machine.Takes(flipped), flipped) {
		return "this machine cannot build or review"
	}
	return saved(machine.Save(flipped, seat.KeepConfigEfforts))
}

// workWords is the work a machine's marks allow as the page names it (menu.work_words).
func workWords(machine machines.Machine) (string, bool) {
	work, known := machine.Work()
	var words []string
	if machine.Name == machines.Here {
		words = append(words, "sessions")
	}
	if slices.Contains(work, "turns") {
		words = append(words, "builds", "reviews")
	}
	if slices.Contains(work, "tests") {
		words = append(words, "tests")
	}
	if len(words) == 0 {
		return "no work", known
	}
	return strings.Join(words, ", "), known
}

// saved is what a page says of a save, Python's menu._saved: nothing where it held.
func saved(err error) string {
	if err != nil {
		return "config: " + config.PyError(err)
	}
	return ""
}
