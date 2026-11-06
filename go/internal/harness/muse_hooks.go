package harness

import (
	"context"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

var museQuestionRunning = regexp.MustCompile(`Request user input .* — running `)

func museHookEvent(event *run.Object) *run.Object {
	// the session this launch opened goes into its receipt, and is no state of the seat's
	if event.Str("hook_event_name") == "SessionStart" {
		museStarted(os.Getenv(museReceiptEnv), event)
		return nil
	}
	if _, err := config.SessionPath(os.Getenv("AGENTKIT_SESSION")); err != nil || os.Getenv("AK_RUN_ROLE") == "worker" {
		return nil
	}
	if tool := event.Get("tool_name"); tool == nil || tool == false {
		if calls := event.List("tool_calls"); len(calls) > 0 {
			if call, ok := calls[0].(*run.Object); ok {
				event.Set("tool_name", call.Get("tool_name"))
			}
		}
	}
	// a Stop hands over the work its session's log has running, as Claude's does; a log it cannot
	// read hands over nothing
	if event.Str("hook_event_name") == "Stop" {
		if held, read := museHeld(event.Str("session_id")); read {
			event.Set("background_tasks", held)
		}
	}
	if pane := os.Getenv("TMUX_PANE"); pane != "" && event.Str("notification_type") == "question_prompt" {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		data, _ := exec.CommandContext(ctx, "tmux", "capture-pane", "-p", "-J", "-t", pane).Output()
		if asked := museQuestion(string(data)); asked != "" {
			event.Set("message", asked)
		}
	}
	return event
}

// A notice names only the folder. The last running question on this pane supplies its words.
func museQuestion(pane string) string {
	question, under := "", false
	for _, row := range strings.Split(pane, "\n") {
		if museQuestionRunning.MatchString(row) {
			question, under = "", true
		} else if text := strings.TrimSpace(row); under && text != "" {
			question, under = text, false
		}
	}
	return question
}
