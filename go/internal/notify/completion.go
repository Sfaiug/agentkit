package notify

import (
	"cmp"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A completion keeps the union of this seat incarnation's verified work and all
// earlier receipts, so plan cleanup and a lost card cannot page the same work again.
func doneCompletion(name string, created any, work []any, card *run.Object) (*run.Object, bool, error) {
	seen := map[[2]string]bool{}
	add := func(outcomes []any) error {
		for _, outcome := range outcomes {
			pair, ok := outcome.([]any)
			if !ok || len(pair) != 2 {
				return errNotObject
			}
			project, first := pair[0].(string)
			what, second := pair[1].(string)
			if !first || !second {
				return errNotObject
			}
			seen[[2]string{project, what}] = true
		}
		return nil
	}
	if err := add(work); err != nil {
		return nil, false, err
	}
	receipts := []*run.Object{card.Dict("completed")}
	var events []*run.Object
	entries, err := os.ReadDir(outbox())
	if err != nil && !os.IsNotExist(err) {
		return nil, false, err
	}
	for _, entry := range entries {
		if !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		event, err := run.ReadJSON(filepath.Join(outbox(), entry.Name()))
		if err != nil || event == nil || event.Str("kind") != "done" {
			continue
		}
		current, _, err := config.ResolveSession(event.Str("session"))
		if err == nil && current == name {
			events = append(events, event)
			receipts = append(receipts, event.Dict("completion"))
		}
	}
	for _, receipt := range receipts {
		if receipt != nil && run.Equal(receipt.Get("created"), created) {
			if err := add(receipt.List("outcomes")); err != nil {
				return nil, false, err
			}
		}
	}
	var keys [][2]string
	for pair := range seen {
		keys = append(keys, pair)
	}
	slices.SortFunc(keys, func(a, b [2]string) int { return cmp.Or(strings.Compare(a[0], b[0]), strings.Compare(a[1], b[1])) })
	outcomes := []any{}
	for _, pair := range keys {
		outcomes = append(outcomes, []any{pair[0], pair[1]})
	}
	completion := run.Fields("created", created, "outcomes", outcomes)
	return completion, slices.ContainsFunc(events, func(event *run.Object) bool {
		return run.Equal(event.Get("completion"), completion)
	}), nil
}
