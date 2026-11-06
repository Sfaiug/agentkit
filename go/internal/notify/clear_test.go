//go:build unix

package notify

import (
	"os"
	"path/filepath"
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

func TestClearRetiresTheOldConversationsQueuedCard(t *testing.T) {
	_, write := questionHome(t)
	write(seatFile("notify", "acme", "json"), `{"kind":"needs","text":"Which schema should acme use?","time":100}`)
	card := `{"word":"done","since":90,"episode":"old-conversation","sent":true}`
	write(seatFile("card", "acme", "json"), card)
	key := cardKey("old-conversation")
	write(filepath.Join(outbox(), key+".json"), run.Line(run.Fields("id", key, "status", "pending", "next_attempt", 0)))
	if err := Clear("acme"); err != nil {
		t.Fatal(err)
	}
	event, err := readEvent(key)
	if err != nil || event.Str("status") != "disabled" {
		t.Fatal("the old conversation's card can still go out", run.Line(event), err)
	}
	if after, _ := os.ReadFile(seatFile("card", "acme", "json")); string(after) != card {
		t.Fatal("a done card took an answer", string(after))
	}
}
