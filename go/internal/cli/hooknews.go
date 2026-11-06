package cli

import (
	"fmt"
	"io"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// tellPrompt prints what the seat's prompt carries as its context, nothing where it carries none.
func tellPrompt(launched string, event *run.Object, out io.Writer) {
	news := rulebooks.PromptNews(launched, event.Str("session_id"), ownersWords(event))
	if news == "" {
		return
	}
	said := run.NewObject()
	said.Set("hookEventName", "UserPromptSubmit")
	said.Set("additionalContext", news)
	answer := run.NewObject()
	answer.Set("hookSpecificOutput", said)
	fmt.Fprintln(out, run.Line(answer))
}

// ownersWords is what a prompt says where the owner is its speaker, nil for a slash command and
// a turn the harness begins on finished work, which answer nothing.
func ownersWords(event *run.Object) *string {
	words := ""
	spoken := false
	for _, key := range []string{"prompt", "message"} {
		text, ok := event.Get(key).(string)
		if !ok {
			continue
		}
		opening := strings.TrimLeftFunc(text, config.Space)
		if strings.Contains(text, "<task-notification") || slashCommand(opening) || strings.HasPrefix(opening, "<system-reminder>") {
			return nil
		}
		if !spoken {
			words, spoken = text, true
		}
	}
	id, _ := first(event, "promptId", "prompt_id").(string)
	if strings.HasPrefix(id, "task-completed-") || strings.HasPrefix(id, "subagent-completed-") {
		return nil
	}
	return &words
}

// slashCommand is whether words open on a slash command: a slash, then a word holding no other,
// where a path pasted at the start holds more.
func slashCommand(opening string) bool {
	word, slash := strings.CutPrefix(opening, "/")
	if end := strings.IndexFunc(word, config.Space); end >= 0 {
		word = word[:end]
	}
	return slash && word != "" && !strings.Contains(word, "/")
}

// compacted tells the seat's record a compaction dropped what its conversation read since it
// launched; a resume keeps what it was handed.
func compacted(launched string, event *run.Object) {
	if event.Str("source") == "compact" {
		rulebooks.RulebookCompacted(launched, event.Str("session_id"))
	}
}
