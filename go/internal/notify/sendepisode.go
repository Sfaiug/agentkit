package notify

import (
	"io"
	"strings"

	"agentkit/internal/run"
)

// Both card kinds share the durable queue, send receipt and retry path.
func sendEpisode(name, kind string, card, notice *run.Object, completion any, errOut io.Writer) (int, error) {
	page, err := payload(name)
	if err != nil {
		return 0, err
	}
	title := "Needs you"
	if kind == "done" {
		title = "Done"
		page.Set("content", strings.Replace(page.Str("content"), "🙋 Needs you", "✅ Done", 1))
	}
	held, err := holdOutbox()
	if err != nil {
		return 0, err
	}
	defer held.Close()
	key := cardKey(card.Get("episode"))
	event, err := readEvent(key)
	if err != nil {
		return 0, err
	}
	text := notice.Str("text")
	fresh := event == nil
	if fresh {
		event = run.NewObject()
		for _, f := range []field{{"id", key}, {"source", "card:" + card.Str("episode")}, {"episode", card.Get("episode")},
			{"session", name}, {"kind", kind}, {"text", text}, {"files", []any{}}, {"payload", page},
			{"message", title + " · " + name + ": " + text}, {"created_at", run.Float(clock())},
			{"sink", sink() != ""}, {"status", "pending"}, {"attempts", 0}, {"next_attempt", 0}} {
			event.Set(f.key, f.value)
		}
		if completion != nil {
			event.Set("completion", completion)
		}
		if err := writeEvent(event); err != nil {
			return 0, err
		}
	}
	card.Set("sent", true)
	if completion != nil {
		card.Set("completed", completion)
	}
	if err := writeCard(name, card); err != nil {
		return 0, err
	}
	if fresh {
		terminalNotice(name, title+" · "+name+": "+text)
	}
	return attempt(event, errOut)
}
