package notify

import "agentkit/internal/run"

func cardHistory(card *run.Object) bool {
	began := card.Get("began")
	if !card.Has("began") {
		began = card.Get("since")
	}
	at, _ := finite(began)
	return at < installedAt()
}

// An absent seat's first card starts with the word just published, bounded by
// when it went. Its notice can be older than that first observation.
func questionEpisode(name string, card *run.Object, asked float64, since any, gone bool) *run.Object {
	if !gone {
		return episode(card, "needs you", run.Float(asked), run.Float(asked))
	}
	at, dated := finite(since)
	if !dated {
		at = clock()
	}
	at = max(at, asked)
	began := at
	if record, _ := run.ReadJSON(seatFile("session", name, "json")); record != nil {
		for _, bound := range []struct {
			key  string
			late float64
		}{{"exited_since", 0}, {"seen", 600}} {
			if went, dated := finite(record.Get(bound.key)); dated {
				began = min(began, went+bound.late)
				break
			}
		}
	}
	return episode(card, "needs you", run.Float(at), run.Float(began))
}

func retryHistory(event *run.Object) bool {
	return event.Str("session") != "" && number(event, "created_at") < installedAt()
}

// Called with the seat and outbox locks held, before consulting the webhook.
func dropHistory(event *run.Object) error {
	run.SetAll(event, "status", "disabled", "error", "queued before the agentkit running now was installed", "next_attempt", nil)
	return writeEvent(event)
}
