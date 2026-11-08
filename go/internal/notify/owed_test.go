//go:build unix

package notify

import (
	"errors"
	"slices"
	"testing"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// Each question a notice asks for the first time is the owner's time from when the notice dates
// it, once the notice is written; one asked again beside it adds nothing.  Where Go cannot name
// the seat's conversation, the ask is Python's, nothing written.
func TestEachQuestionANoticeAsksFirstIsAskedOnce(t *testing.T) {
	_, write := questionHome(t)
	port, branch := "Which port?", "Which branch?"
	asked := func() (at []float64) {
		t.Helper()
		db, err := history.Open()
		if err != nil || db == nil {
			return nil
		}
		defer db.Close()
		rows, _ := db.Owner(0, clock()+1)
		for _, row := range rows {
			if row["kind"] == "asked" {
				at = append(at, row["at"].(float64))
			}
		}
		return at
	}
	dated := func(question string) float64 {
		at, _ := Last("acme").Dict("asked_at").Num(questionKey(question))
		return at
	}

	if err := AskKept("acme", []Kept{{Text: port}}); err != nil {
		t.Fatal(err)
	}
	first := dated(port)
	if err := AskKept("acme", []Kept{{Text: port}, {Text: branch}}); err != nil {
		t.Fatal(err)
	}
	if got := asked(); !slices.Equal(got, []float64{first, dated(branch)}) {
		t.Fatal(got, run.Line(Last("acme")))
	}

	write(seatFile("session", "acme", "json"), `{"orchestrator":"opus","cwd":"/code/acme","conversation":"conv-other"}`)
	before := run.Line(Last("acme"))
	if err := AskKept("acme", []Kept{{Text: "Which scope?"}}); !errors.Is(err, ErrUnread) {
		t.Fatal(err)
	}
	if run.Line(Last("acme")) != before || len(asked()) != 2 {
		t.Fatal("an ask Go cannot name the conversation of wrote", run.Line(Last("acme")), asked())
	}
}
