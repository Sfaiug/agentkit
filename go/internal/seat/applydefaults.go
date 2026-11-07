package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// DefaultsMove is what `a` on a fresh window's `c` asks about (menu.apply_defaults): of the seats
// `rows` names, in their order, those with a record of their own but the weekly audit's, and of
// those the ones not running `lead` at its entry's effort that their running harness cannot move
// there in place (orch.switch_lines). False where Go cannot tell.
func DefaultsMove(rows []string, lead string) (open, restarts []string, known bool) {
	models, err := config.Models()
	entry, named := models[lead]
	skip, _, unread := config.ResolveSession(audit)
	if err != nil || !named || unread != nil {
		return nil, nil, false
	}
	for _, name := range rows {
		current, record, err := config.ResolveSession(name)
		if err != nil {
			return nil, nil, false
		}
		if current != name || record == nil || name == skip { // a rename's pointer is no record
			continue
		}
		open = append(open, name)
		at, read := atOwnEfforts(entry, lead, record)
		if !read {
			return nil, nil, false
		}
		was, _ := record["orchestrator"].(string)
		if was == lead && at.Efforts["effort"] == entry.Efforts["effort"] {
			continue
		}
		inPlace, err := switchesInPlace(name, models[was], entry)
		if err != nil || inPlace && harness.AsksSwitchable(entry.Harness) {
			return nil, nil, false
		}
		if !inPlace {
			restarts = append(restarts, name)
		}
	}
	return open, restarts, true
}
