//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestAFailedRevivalPagesAtOnceInItsExistingEpisode(t *testing.T) {
	for _, justLeft := range []bool{false, true} {
		t.Run(run.Text(justLeft), func(t *testing.T) {
			_, write := questionHome(t)
			write(filepath.Join(os.Getenv("PATH"), "tmux"), "#!/bin/sh\nexit 1\n")
			asked := run.Float(clock() - 30)
			write(seatFile("notify", "acme", "json"), run.Line(run.Fields(
				"kind", "needs", "text", "Which database?", "time", asked)))
			write(seatFile("seat", "acme", "json"), `{"word":"needs you","reason":"session closed: press 1 to reopen"}`)
			card := run.Fields("word", "needs you", "since", asked, "began", asked, "episode", "question", "sent", false)
			if justLeft {
				card.Set("left", asked)
			}
			write(seatFile("card", "acme", "json"), run.Line(card))
			word := func(string, *run.Object, time.Time) (string, any, bool) { return "needs you", nil, false }
			for range 2 {
				if carried, err := Failed("acme", "The seat could not reopen; say continue.", "revive:acme:turn:1", true, word, io.Discard); !carried || err != nil {
					t.Fatal(carried, err)
				}
			}
			after, err := readObject(seatFile("card", "acme", "json"))
			if err != nil || after.Truthy("sent") == justLeft || after.Str("episode") != "question" || !run.Equal(after.Get("began"), asked) {
				t.Fatalf("the failed revival did not keep its episode and paging policy: %v %s", err, run.Line(after))
			}
			event, err := readEvent(cardKey("question"))
			if err != nil || (event == nil) != justLeft {
				t.Fatal("the failed revival did not queue its page", event, err)
			}
			if event != nil {
				// a failure is no question: its page says what failed, not what the seat published
				if notice, _ := readObject(seatFile("notify", "acme", "json")); event.Str("text") != notice.Str("text") {
					t.Fatal("the failed revival paged another text", run.Line(event))
				}
				attempts, _ := event.Int("attempts")
				if attempts != 1 {
					t.Fatal("a repeated failure attempted its page again", run.Line(event))
				}
			}
		})
	}
}
