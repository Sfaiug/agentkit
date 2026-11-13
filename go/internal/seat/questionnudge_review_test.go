package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/screen"
)

func TestReviewQuestionNudgeCompletesStartedLine(t *testing.T) {
	for _, own := range []string{"muse", "opencode"} {
		for _, display := range []string{"whole", "owner_added", "tall", "output_scrolled", "retry_owner_added", "after_enter_owner"} {
			t.Run(own+"/"+display, func(t *testing.T) {
				home := sandbox(t)
				t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
				write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+
					"[models.vela]\nharness='"+own+"'\nmodel='vela'\neffort='high'\nprovider='test'\n")
				token := strings.Repeat("a", 32)
				session := "session_1"
				if own == "opencode" {
					session = "ses_Free"
					db, err := os.ReadFile(filepath.Join("..", "harness", "testdata", "opencode.db"))
					if err != nil {
						t.Fatal(err)
					}
					t.Setenv("OPENCODE_DB", filepath.Join(home, "share", "opencode", "opencode.db"))
					write(t, os.Getenv("OPENCODE_DB"), string(db))
				}
				record(t, home, "acme", map[string]any{"orchestrator": "vela", "workers": []string{"vela"}, own + "_launch": token})
				write(t, filepath.Join(stateFile(home, own+"-launch-"+token), "session"), session)
				if own == "muse" {
					var events []string
					for _, event := range []*run.Object{run.Fields("kind", "started", "prompt", "Build acme."), run.Fields("kind", "assistant_message_committed", "text", "Ready")} {
						events = append(events, run.Line(run.Fields("record_type", "event", "recorded_at", int(time.Now().Add(-time.Minute).UnixMicro()), "payload", run.Fields("kind", "run", "event", event))))
					}
					write(t, filepath.Join(home, "share", "muse", "sessions", "2026", "11", "13", session, "session.jsonl"), strings.Join(events, "\n")+"\n")
				}
				data, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", own+"-prompt-pane.txt"))
				if err != nil {
					t.Fatal(err)
				}
				prompt := "Ready\n" + string(data)
				question := "Which colour should the acme preview use?"
				if display == "tall" {
					question += " Options: " + strings.Repeat("blue, green, amber, violet; ", 30)
				}
				line := keyed(Reminder("Ready", []string{question}))
				visible := line
				if display == "owner_added" {
					visible += " and the owner's own words"
				}
				typed := strings.Replace(prompt, "\n❯\n", "\n❯ "+visible+"\n", 1)
				if display == "tall" && own == "muse" {
					var rows []string
					for rest := line; rest != ""; {
						at := min(32, len(rest))
						rows = append(rows, rest[:at])
						rest = rest[at:]
					}
					typed = strings.Replace(prompt, "\n❯\n", "\n❯ "+strings.Join(rows, "\n  ")+"\n", 1)
				}
				cursor := 0
				if own == "opencode" {
					typed = strings.Replace(prompt, "Ask anything… \"What is the tech stack of this project?\"", visible, 1)
					for at, row := range strings.Split(prompt, "\n") {
						if strings.Contains(row, "Ask anything") {
							cursor = at
						}
					}
				}
				if display == "output_scrolled" {
					typed = strings.TrimPrefix(typed, "Ready\n")
				}
				typedCursor := cursor
				if own == "opencode" {
					for at, row := range strings.Split(typed, "\n") {
						if strings.Contains(row, visible) {
							typedCursor = at
						}
					}
				}
				write(t, filepath.Join(home, "cursor"), encoded(t, cursor))
				write(t, filepath.Join(home, "prompt-cursor"), encoded(t, cursor))
				write(t, filepath.Join(home, "typed-cursor"), encoded(t, typedCursor))
				write(t, filepath.Join(home, "prompt"), prompt)
				after := prompt
				if display == "retry_owner_added" {
					if own == "muse" {
						after = strings.Replace(prompt, "\n❯\n", "\n❯ "+line+" and the owner's own words\n", 1)
					} else {
						after = strings.Replace(prompt, "Ask anything… \"What is the tech stack of this project?\"", line+" and the owner's own words", 1)
					}
				}
				if display == "after_enter_owner" {
					if own == "muse" {
						after = strings.Replace(prompt, "\n❯\n", "\n❯ My next draft\n", 1)
					} else {
						after = strings.Replace(prompt, "Ask anything… \"What is the tech stack of this project?\"", "My next draft", 1)
					}
				}
				write(t, filepath.Join(home, "after"), after)
				write(t, filepath.Join(home, "typed"), typed)
				write(t, filepath.Join(home, "shown"), prompt)
				write(t, filepath.Join(home, "bin", "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) echo '0 1 %1 0' ;;
  *'#{cursor_y}'*) cat "$HOME/cursor" ;;
  *'#{pane_id}'*) printf '%%1\t1000\t4242\n' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then
      if [ -e "$HOME/entered" ]; then cp "$HOME/prompt" "$HOME/shown"
      else cp "$HOME/after" "$HOME/shown"; touch "$HOME/entered"; fi
      cp "$HOME/prompt-cursor" "$HOME/cursor"
    else cp "$HOME/typed" "$HOME/shown"; cp "$HOME/typed-cursor" "$HOME/cursor"; fi ;;
esac
`)
				if err := os.Chmod(filepath.Join(home, "bin", "tmux"), 0o700); err != nil {
					t.Fatal(err)
				}
				t.Setenv("PATH", filepath.Join(home, "bin")+string(os.PathListSeparator)+os.Getenv("PATH"))
				state := filepath.Join(home, ".agentkit", "state")
				write(t, stateFile(home, "seat-acme.json"), run.Line(run.Fields("state", "at_prompt", "stop_said", stopWords(eyeOf(own).rules, screen.Tail(prompt)), "stop_said_at", 1, "turn_began", 1)))
				write(t, stateFile(home, "notify-acme.json"), run.Line(run.Fields("session", "acme", "kind", "needs", "text", question, "time", int(time.Now().Unix()))))
				seat := Seat{Name: "acme", own: own, reader: harness.For(own)}
				found := (seatAt{"acme", own, "=acme:"}).sight(prompt)
				if found.state != "at_prompt" {
					t.Fatalf("bad setup: %+v", found)
				}
				if _, err := seat.nudgeQuestion(state, found, func(string) {}); err != nil {
					t.Fatal(err)
				}
				keys, _ := os.ReadFile(filepath.Join(home, "keys"))
				expectedKeys := line + "\nEnter\n"
				if display == "retry_owner_added" {
					expectedKeys += "Enter\n"
				}
				if string(keys) != expectedKeys {
					t.Fatalf("reminder must get its completing Enter(s): text went in=%v, Enter count=%d", strings.HasPrefix(string(keys), line+"\n"), strings.Count(string(keys), "Enter\n"))
				}
				if display == "after_enter_owner" || display == "whole" {
					// Clearing a draft begins no new turn and leaves the same stop owed.
					write(t, filepath.Join(home, "shown"), prompt)
					if _, err := seat.nudgeQuestion(state, found, func(string) {}); err != nil {
						t.Fatal(err)
					}
					keys, _ = os.ReadFile(filepath.Join(home, "keys"))
					if string(keys) != line+"\nEnter\n" {
						t.Fatalf("same stop must receive only one reminder: Enter count=%d", strings.Count(string(keys), "Enter\n"))
					}
				}
			})
		}
	}
}
