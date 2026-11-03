package cli

import (
	"strconv"

	"agentkit/internal/run"
)

// sendsBack is how many times one turn goes back to say what it asked: the third stop stands.
const sendsBack = 2

// remind is the reason a turn whose closing message left a recorded question unsaid goes back
// with, counted on the turn's latch; "" once it went back sendsBack times.
func remind(launched string, turned *run.Object, unseen string) string {
	number, _ := turned.Get("blocks").(run.Number)
	blocks, err := strconv.Atoi(string(number))
	if err != nil {
		blocks = 0
	}
	if blocks++; blocks > sendsBack {
		return ""
	}
	turned.Set("session", launched)
	turned.Set("blocks", blocks)
	if relatch(launched, run.Line(turned)) != nil {
		return ""
	}
	return unseen
}
