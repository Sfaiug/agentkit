package transcript

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// Prompted is the owner's prompt that entry holds, as its harness's conversation records it, with no
// words where it holds none (a harness's `prompt`).
func Prompted(name string, entry *run.Object) Prompt {
	table, _ := config.Tree(name, "transcript")
	if table == nil {
		return Prompt{}
	}
	stamp, _ := table["at"].(string)
	return Prompt{At: harness.Moment(first(at(entry, stamp))), Text: promptWords(name, promptKinds(table), entry)}
}
