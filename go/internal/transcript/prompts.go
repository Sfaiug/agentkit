package transcript

import (
	"bufio"
	"iter"
	"sort"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// A Prompt is one of the owner's messages: when it was written, in Unix seconds, and its words.
type Prompt = harness.Prompt

// Prompts is every dated message the owner wrote in the conversation read by those names
// (harness.EntriesBy), oldest first, as a harness's `user_messages` reads them; none where its
// harness has no `[transcript]` table or the file is gone.  The error where it is there and cannot
// be read, as `user_messages` raises, beside the messages read before it.
func Prompts(name string, names ...string) (found []Prompt, err error) {
	table, _ := config.Tree(name, "transcript")
	if table == nil {
		return nil, nil
	}
	skip, _ := table["skip"].(map[string]any)
	stamp, _ := table["at"].(string)
	answer, kinds := named(table["answer"]), promptKinds(table)
	err = harness.EntriesBy(names, func(entry *run.Object) {
		if skip != nil && fits(skip, entry) || len(answer.items(entry)) > 0 {
			return
		}
		if text, when := promptWords(name, kinds, entry), harness.Moment(first(at(entry, stamp))); text != "" && when != 0 {
			found = append(found, Prompt{At: when, Text: text})
		}
	})
	sort.SliceStable(found, func(i, j int) bool { return found[i].At < found[j].At })
	return found, err
}

// Entries is each JSON object a JSON lines file read by those names holds (harness.Open), first
// line first, as harness.entries reads a growing record: an unfinished last line can wait.  These
// are only read, so a lone surrogate in a cut tool output costs nothing (run.DecodeShown).
func Entries(names ...string) iter.Seq[*run.Object] {
	return func(yield func(*run.Object) bool) {
		file, err := harness.Open(names...)
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
