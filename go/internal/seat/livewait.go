package seat

import (
	"cmp"
	"strings"

	"agentkit/internal/config"
)

// waitingOnLive is rung 3a's answer over the seat's runs awaiting their live check: the title of the
// one merged last, and since the first of them merged.
func waitingOnLive(pending []ran) *answer {
	newest, since := pending[0], pending[0].record.Get("finished_at")
	for _, each := range pending[1:] {
		finished := each.record.Get("finished_at")
		if at(finished) > at(newest.record.Get("finished_at")) {
			newest = each
		}
		if at(finished) < at(since) {
			since = finished
		}
	}
	title := config.Fold(cmp.Or(newest.record.Str("title"), newest.record.Str("run_id")))
	return &answer{word: "working", reason: strings.TrimRight("waiting on the live check · "+title, " ·"), since: since}
}
