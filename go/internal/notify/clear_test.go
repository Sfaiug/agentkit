//go:build unix

package notify

import (
	"testing"

	"agentkit/internal/run"
)

func TestClearEndsTheOldConversationsQuestion(t *testing.T) {
	_, write := questionHome(t)
	write(seatFile("notify", "acme", "json"), `{"kind":"needs","text":"Which database?","time":100}`)
	write(seatFile("card", "acme", "json"), `{"word":"needs you","since":100}`)
	if err := Clear("acme"); err != nil {
		t.Fatal(err)
	}
	notice, _ := run.ReadJSON(seatFile("notify", "acme", "json"))
	card, _ := run.ReadJSON(seatFile("card", "acme", "json"))
	if Standing("acme") || notice.Get("seen") != true || notice.Str("text") != "Which database?" || card.Get("answered_at") == nil {
		t.Fatal(run.Line(notice), run.Line(card))
	}
	if err := Clear("acme"); err != nil {
		t.Fatal(err)
	}
	again, _ := run.ReadJSON(seatFile("card", "acme", "json"))
	if !run.Equal(card, again) {
		t.Fatal("clearing an already seen question rewrote its answer", run.Line(again))
	}
}
