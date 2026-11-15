package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/guard/keys"
	"agentkit/internal/pyre"
	"agentkit/internal/screen"
)

// asks is watch._asks: whether the seat's bottom rows, read once as drawn, end on what its harness
// asks before it takes a line of its `[switch]` (`asks`); a card above a composer is the
// transcript's.  Where they do, the keys that say yes (`yes`) go into its pane and answered is
// told, unless its terminal holds input unread, which the card would take first.
func (at seatAt) asks(line string, answered func(), log func(string)) bool {
	block, err := config.Section(at.own, "switch")
	source, _ := block["asks"].(string)
	if err != nil || source == "" {
		return false
	}
	var yes []string
	listed, _ := block["yes"].([]any)
	for _, key := range listed {
		if key, ok := key.(string); ok && key != "" {
			yes = append(yes, key)
		}
	}
	asks, err := pyre.Compile(`(?:`+source+`)\Z`, pyre.Multiline)
	if err != nil || len(yes) == 0 || !asks.MatchString(screen.Drawn(at.capture())) {
		return false
	}
	if !at.unread() {
		if _, err := keys.Type(at.pane, yes...); err == nil {
			answered()
			log("said yes to what " + at.name + " asked before it took " + line)
		}
	}
	return true
}
