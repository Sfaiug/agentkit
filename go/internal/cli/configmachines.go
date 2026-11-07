package cli

import (
	"cmp"
	"fmt"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/googlecloud"
	"agentkit/internal/machines"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// menuMachines is `Machines` on `c` (menu.config_machines), from the tick's records alone: a row
// for every machine ak may use, this one first, Enter opening its work but on this one's; then
// the cloud's, Space switching it on or off, saved at once, and Enter opening its work.
func menuMachines(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	return configPage("machines", "", func() ([]menu.PageRow, bool) {
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
		active, _ := config.CloudBudget()
		work, known := workWords(machines.Cloud)
		return append(rows, menu.PageRow{Label: "Google Cloud", Value: googlecloud.Summary(true) + " · " + work, On: active,
			Flip: func() string { return saved(machines.Cloud.Save("active", !active, seat.KeepConfigEfforts)) },
			Open: func() bool { return menuMachineWork(machines.Cloud.Name, keyboard, painter) }}), known
	}, keyboard, painter)
}

// menuMachineWork is `config · machines · <name>`: a mark for each work a machine may take,
// Space flipping it, saved at once, but builds and reviews on a Mac.  A machine ak rents takes
// the cloud's marks, whose page has its monthly cap too, a field (saveCap).  Each draw and each
// flip reads the machine afresh, as a probe may land while the page is open.
func menuMachineWork(name string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	if machines.Named(name).Rented() {
		name = ""
	}
	return configPage("machines · "+cmp.Or(name, "Google Cloud"), "", func() ([]menu.PageRow, bool) {
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
		if name == "" {
			_, cap := config.CloudBudget()
			rows = append(rows, menu.PageRow{Label: "Monthly cap", Value: fmt.Sprintf("€%.6g", cap),
				Field: saveCap, Placeholder: "whole euros per month, 0 or more"})
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
	return saved(machine.Save("work", flipped, seat.KeepConfigEfforts))
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
