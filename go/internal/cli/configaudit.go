package cli

import (
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// auditNote is what `Weekly audit` says under its rows.
const auditNote = "Once a week ak opens a seat named audit with the week's largest loss."

// menuAudit is `Weekly audit` on `c` (menu.config_audit): whether it runs and the models its seat
// takes, a row each, each change written to `[audit]` at once.  Space on `On` turns it the other
// way; Enter on `Orchestrator` opens every model, ● the one it is, and on `Builds` and `Reviews`
// every model, ■ each in that role.  A setting Audit cannot read is Python's, to say why and mend.
func menuAudit(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	return configPage("weekly audit", auditNote, func() ([]menu.PageRow, bool) {
		held, on, err := config.Audit()
		models, listed := config.Models()
		if err != nil || listed != nil {
			return nil, false
		}
		roles := func(key string) func() ([]menu.PageRow, bool) {
			return func() ([]menu.PageRow, bool) { return auditChoices(key) }
		}
		return []menu.PageRow{
			{Label: "On", Value: onOff(on), On: on, Flip: func() string { return auditSaved("on", !on) }},
			{Label: "Orchestrator", Value: config.ModelName(held.Orchestrator, models), List: roles("orchestrator")},
			{Label: "Builds", Value: auditNames(held.Workers, models), List: roles("workers"), Several: true},
			{Label: "Reviews", Value: auditNames(held.Reviewers, models), List: roles("reviewers"), Several: true},
		}, true
	}, keyboard, painter)
}

// auditChoices is the list a role's row opens, read afresh: every model the config offers, marked
// where it holds the role, Space moving the orchestrator to it or taking it in or out of the role.
func auditChoices(key string) ([]menu.PageRow, bool) {
	held, _, err := config.Audit()
	models, listed := config.Models()
	offered, asked := config.Offered()
	if err != nil || listed != nil || asked != nil {
		return nil, false
	}
	group := map[string][]string{"orchestrator": {held.Orchestrator}, "workers": held.Workers, "reviewers": held.Reviewers}[key]
	var choices []menu.PageRow
	for _, name := range offered {
		in := slices.Contains(group, name)
		value := any(name)
		if key != "orchestrator" && in {
			value = slices.DeleteFunc(slices.Clone(group), func(each string) bool { return each == name })
		} else if key != "orchestrator" {
			value = append(slices.Clone(group), name)
		}
		choices = append(choices, menu.PageRow{Value: config.ModelName(name, models), On: in,
			Flip: func() string { return auditSaved(key, value) }})
	}
	return choices, true
}

// auditSaved writes a change of the weekly audit (config.SaveAudit), and what the page says of it:
// why it was refused, nothing where it held.
func auditSaved(key string, value any) string {
	if err := config.SaveAudit(key, value, seat.KeepConfigEfforts); err != nil {
		return "weekly audit: " + err.Error()
	}
	return ""
}

// auditNames is the models of an audit's role by their full names, as `c` and its page show them.
func auditNames(names []string, models map[string]config.Model) string {
	labels := []string{}
	for _, name := range names {
		labels = append(labels, config.ModelName(name, models))
	}
	if len(labels) == 0 {
		return "nobody"
	}
	return strings.Join(labels, ", ")
}
