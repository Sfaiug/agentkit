package cli

import (
	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// doneCheckNote is what `Done check` says under its rows.
const doneCheckNote = "A model reads what you asked a seat and names what its work does not hold."

// menuDoneCheck is `Done check` on `c` (menu.config_done_check): whether it is on and the model
// that makes it, a row each, each change written to `[done_check]` at once.  Space on `On` turns
// it the other way; Enter on `Model` opens the seat's reviewer and every model offered, ● the one
// in use.  A setting DoneCheck cannot read is Python's, to say why and mend.  The rows are read
// once and again after each write, as Python's page reads the config it holds.
func menuDoneCheck(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	var rows []menu.PageRow // as last read
	saved := func(key string, value any) string {
		rows = nil
		if err := config.SaveDoneCheck(key, value, seat.KeepConfigEfforts); err != nil {
			return "done check: " + err.Error()
		}
		return ""
	}
	return configPage("done check", doneCheckNote, func() ([]menu.PageRow, bool) {
		if rows != nil {
			return rows, true
		}
		checker, on, err := config.DoneCheck()
		models, listed := config.Models()
		// a config Go binds otherwise than Python is Python's to save (seat.KeepConfigEfforts):
		// handed over as the page opens, before anything is written
		_, unbound := config.Bind()
		if err != nil || listed != nil || unbound != nil {
			return nil, false
		}
		rows = []menu.PageRow{
			{Label: "On", Value: onOff(on), On: on, Flip: func() string { return saved("on", !on) }},
			{Label: "Model", Value: checkerName(checker, models),
				List: func() ([]menu.PageRow, bool) { return checkerChoices(saved) }},
		}
		return rows, true
	}, keyboard, painter)
}

// checkerChoices is the list `Model` opens, read afresh: the seat's reviewer, then every model the
// config offers, ● the one in use, Space taking it through `saved`, the seat's reviewer by taking
// `model` out.
func checkerChoices(saved func(key string, value any) string) ([]menu.PageRow, bool) {
	checker, _, err := config.DoneCheck()
	models, listed := config.Models()
	offered, asked := config.Offered()
	if err != nil || listed != nil || asked != nil {
		return nil, false
	}
	var choices []menu.PageRow
	for _, name := range append([]string{""}, offered...) {
		value := any(name)
		if name == "" {
			value = nil
		}
		choices = append(choices, menu.PageRow{Value: checkerName(name, models), On: name == checker,
			Flip: func() string { return saved("model", value) }})
	}
	return choices, true
}

// checkerName is the model that makes the done check, `name`, by its full name, else the seat's
// reviewer (menu.checker_name), as `c`'s row and its page say it.
func checkerName(name string, models map[string]config.Model) string {
	if name == "" {
		return "the seat's reviewer"
	}
	return config.ModelName(name, models)
}
