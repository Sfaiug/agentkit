package harness

import (
	"fmt"
	"slices"
	"strings"

	"agentkit/internal/run"
)

// CanHandOver settles the history and cleanup boundary before confirmation,
// without reading a conversation the owner may choose to keep running.
func CanHandOver(name string) bool {
	own, plugged := plugins[name]
	return (!plugged || own.handed != nil) && (own.moveReady == nil || own.moveReady())
}

// Handover is orch.handover, including an empty conversation that adds nothing.
// False leaves a harness whose history or cleanup Go cannot carry to Python.
func Handover(name string, record map[string]any) (string, bool) {
	data := run.NewObject()
	for key, value := range record {
		data.Set(key, value)
	}
	text := "It cannot be read here.\n\n"
	if hook := plugins[name].handed; hook != nil {
		var known bool
		if text, known = hook(data); !known || text == "" {
			return "", known
		}
	} else if _, plugged := plugins[name]; plugged {
		return "", false
	}
	return fmt.Sprintf("## Its conversation on %s\n\n%s", data.Str("orchestrator"), text), true
}

func handedMessages(path, model string, read func(*run.Object) (string, string)) (string, bool) {
	var text strings.Builder
	err := entries(path, func(entry *run.Object) {
		if who, said := read(entry); said != "" {
			if who != "user" {
				who = model
			}
			fmt.Fprintf(&text, "**%s:** %s\n\n", who, said)
		}
	})
	return text.String(), err == nil
}

func handedText(content any, kinds ...string) string {
	if text, ok := content.(string); ok {
		return text
	}
	parts, _ := content.([]any)
	var lines []string
	for _, value := range parts {
		if part, ok := value.(*run.Object); ok && slices.Contains(kinds, part.Str("type")) {
			if text, ok := part.Get("text").(string); ok {
				lines = append(lines, text)
			}
		}
	}
	return strings.Join(lines, "\n")
}
