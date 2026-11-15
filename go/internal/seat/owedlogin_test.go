package seat

import (
	"errors"
	"testing"

	"agentkit/internal/run"
)

// [1a] of a seat's runs parked on a login: the login it waits for until the tick finds it back,
// then only one a login keeps refusing (watch.owed_login), the oldest by its ending naming the
// login and dating the word, among the runs a login refuses too; what it said is the stall's.  One
// parked on a login named by no text is Python's.
func TestARunParkedOnALoginOwesItUntilTheTickFindsItBack(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "login-refusals.json"), `{"shop": ["r-refused", "r-refused", "r-back", "r-back"]}`)
	of := func(name string, fields ...any) ran {
		return ran{name: name, record: run.Fields(fields...), view: &runView{}}
	}
	parked := of("r-parked", "state", "waiting_login", "waiting_for", "acme", "finished_at", 20, "error", "acme login expired")
	refused := of("r-refused", "state", "running", "finished_at", 30)
	back := of("r-back", "state", "waiting_login", "waiting_for", "acme", "login_back_at", 25, "finished_at", 10)
	resumed := of("r-resumed", "state", "waiting_login", "waiting_for", "acme", "login_back_at", 25, "finished_at", 5)
	unnamed := of("r-unnamed", "state", "waiting_login", "waiting_for", "", "finished_at", 1)
	for _, each := range []struct {
		mine   []ran
		reason string
		owed   *Owed
	}{
		{[]ran{refused, parked}, "acme login expired: open it and log in again", &Owed{"acme", run.Number("20"), "acme login expired"}},
		{[]ran{parked, back}, "shop login expired: open it and log in again", &Owed{"shop", run.Number("10"), ""}},
		{[]ran{resumed, unnamed}, "", nil},
	} {
		said, err := runOnALogin(climbing{mine: each.mine})
		owed, _ := owedOf(each.mine)
		switch {
		case err != nil:
			t.Fatal(err)
		case said == nil || owed == nil:
			if each.reason != "" || said != nil || owed != nil {
				t.Errorf("%d runs say %v, owe %v", len(each.mine), said, owed)
			}
		case said.word != "needs you" || said.reason != each.reason || said.since != each.owed.Since || *owed != *each.owed:
			t.Errorf("%d runs say %+v, owe %+v", len(each.mine), *said, *owed)
		}
	}
	if _, err := runOnALogin(climbing{mine: []ran{of("r-odd", "state", "waiting_login", "waiting_for", 7)}}); !errors.Is(err, ErrUnread) {
		t.Errorf("a login named by no text was read: %v", err)
	}
}
