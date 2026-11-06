package transcript

import (
	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Moment is a time in Unix seconds as a harness records one, 0 for none (harness.moment).
func Moment(value any) float64 { return moment(value) }

// Prompted is the owner's prompt that entry holds, as its harness's conversation records it, with no
// words where it holds none (a harness's `prompt`).
func Prompted(name string, entry *run.Object) Prompt {
	table, _ := config.Tree(name, "transcript")
	if table == nil {
		return Prompt{}
	}
	stamp, _ := table["at"].(string)
	return Prompt{At: moment(first(at(entry, stamp))), Text: promptWords(name, promptKinds(table), entry)}
}
