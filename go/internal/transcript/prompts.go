package transcript

import (
	"bufio"
	"iter"
	"os"
	"sort"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// A Prompt is one of the owner's messages: when it was written, in Unix seconds, and its words.
type Prompt = harness.Prompt

// Prompts is every dated message the owner wrote in the conversation at path, oldest first, as a
// harness's `user_messages` reads them; none where its harness has no `[transcript]` table or the
// file cannot be read.
func Prompts(name, path string) (found []Prompt) {
	table, _ := config.Tree(name, "transcript")
	if table == nil {
		return nil
	}
	skip, _ := table["skip"].(map[string]any)
	stamp, _ := table["at"].(string)
	answer, kinds := named(table["answer"]), promptKinds(table)
	for entry := range Entries(path) {
		if skip != nil && fits(skip, entry) || len(answer.items(entry)) > 0 {
			continue
		}
		if text, when := promptWords(name, kinds, entry), moment(first(at(entry, stamp))); text != "" && when != 0 {
			found = append(found, Prompt{At: when, Text: text})
		}
	}
	sort.SliceStable(found, func(i, j int) bool { return found[i].At < found[j].At })
	return found
}

// Entries is each JSON object a JSON lines file holds, first line first, as harness.entries reads
// a growing record: an unfinished last line can wait.  These are only read, so a lone surrogate
// in a cut tool output costs nothing (run.DecodeShown).
func Entries(path string) iter.Seq[*run.Object] {
	return func(yield func(*run.Object) bool) {
		file, err := os.Open(path)
		if err != nil {
			return
		}
		defer file.Close()
		for reader := bufio.NewReader(file); ; {
			line, err := reader.ReadBytes('\n')
			value, _ := run.DecodeShown(line)
			if entry, ok := value.(*run.Object); ok && !yield(entry) || err != nil {
				return
			}
		}
	}
}
