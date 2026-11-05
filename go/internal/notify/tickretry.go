package notify

import (
	"strings"

	"agentkit/internal/run"
)

func retryCard(event *run.Object) bool {
	at, dated := finite(event.Get("created_at"))
	return event.Str("session") != "" && (event.Str("kind") == "needs" || event.Str("kind") == "done") && event.Truthy("episode") &&
		strings.HasPrefix(event.Str("source"), "card:") && dated && at >= installedAt() &&
		(event.Str("status") == "pending" || event.Str("status") == "blocked")
}
