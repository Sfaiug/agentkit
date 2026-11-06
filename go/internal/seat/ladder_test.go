package seat

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// hookWrote is a fact as hooks/seat-state.sh leaves it, heard a moment ago.
func hookWrote(t *testing.T, home, event, kind string) {
	t.Helper()
	write(t, stateFile(home, "hook-acme.json"), fmt.Sprintf(`{"session": "acme", "event": %q, "kind": %q, "text": "", "at": %f}`+"\n", event, kind, seconds(time.Now())))
}

// The facts tests/test_key_hook_words.py fires, beside the screens it shows.
func TestAHookFactSpeaksBesideTheScreen(t *testing.T) {
	for name, each := range map[string]struct {
		screen, event, kind, word, reason, authority string
	}{
		"a turn that ended at the prompt":  {prompting, "Stop", "", "idle", "-", "hook  rule: Stop"},
		"a permission on screen":           {asked, "PermissionRequest", "Bash", "needs you", "PermissionRequest", "hook  rule: PermissionRequest/Bash"},
		"a permission answered":            {prompting, "PermissionRequest", "Bash", "working", "-", "screen  rule: prompt.composer"},
		"its notice answered":              {prompting, "Notification", "permission_prompt", "working", "-", "screen  rule: prompt.composer"},
		"a prompt under a composer":        {prompting, "UserPromptSubmit", "", "working", "-", "screen  rule: prompt.composer"},
		"a compaction under a composer":    {prompting, "PreCompact", "manual", "working", "-", "screen  rule: prompt.composer"},
		"a turn running after its prompt":  {spinning, "UserPromptSubmit", "", "working", "-", "hook  rule: UserPromptSubmit"},
		"a stop on background work":        {prompting, "Stop", "background", "working", "-", "screen  rule: prompt.composer"},
		"a stop going back on a held turn": {prompting, "Stop", "held", "working", "-", "screen  rule: prompt.composer"},
		"a stop with a turn on screen":     {spinning, "Stop", "", "working", "-", "screen  rule: working.spinner"},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			drawn(t, home, "acme", each.screen)
			hookWrote(t, home, each.event, each.kind)
			lines := explained(t, "acme")
			if lines[0] != "acme  "+each.word || lines[1] != "  reason:    "+each.reason || lines[2] != "  authority: "+each.authority {
				t.Fatal(lines)
			}
		})
	}
}

// What a hook said goes in the seat file as Python keeps it, and a draft under a turn is no one's yet.
func TestTheSeatFileKeepsWhatTheHookSaid(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	show := drawn(t, home, "acme", drafted)
	hookWrote(t, home, "UserPromptSubmit", "")
	explained(t, "acme")
	file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if file.Str("hooked") != "working" || file.Str("hooked_event") != "UserPromptSubmit" || file.Str("word") != "working" || file.Str("unsent") != "" {
		t.Fatal(run.Line(file))
	}
	if at, dated := file.Num("hooked_at"); !dated || at == 0 {
		t.Fatal(run.Line(file))
	}
	hookWrote(t, home, "Stop", "")
	explained(t, "acme")
	if file, _ = run.ReadJSON(stateFile(home, "seat-acme.json")); file.Str("unsent") != "fix the build" || file.Str("word") != "idle" {
		t.Fatal(run.Line(file))
	}
	show(prompting)
}

// The owner's Esc ends a turn with no Stop: their interruption recorded, or their prompt put back.
func TestAnEscEndsTheTurnItsHookBegan(t *testing.T) {
	say := func(text string) string {
		return fmt.Sprintf(`{"type": "user", "timestamp": %q, "message": {"role": "user", "content": %q}}`+"\n",
			time.Now().Add(time.Minute).UTC().Format(time.RFC3339), text)
	}
	for name, each := range map[string]struct{ entries, screen string }{
		"recorded": {say("[Request interrupted by user]"), prompting},
		"tool use": {say("[Request interrupted by user for tool use]"), prompting},
		"put back": {say("fix the build"), drafted},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			transcript(t, home, "acme", each.entries)
			drawn(t, home, "acme", each.screen)
			hookWrote(t, home, "UserPromptSubmit", "")
			if lines := explained(t, "acme"); lines[0] != "acme  idle" {
				t.Fatal(lines)
			}
			if file, _ := run.ReadJSON(stateFile(home, "seat-acme.json")); file.Get("interrupted") != true {
				t.Fatal(run.Line(file))
			}
		})
	}
	t.Run("a prompt with another draft", func(t *testing.T) {
		home := sandbox(t)
		record(t, home, "acme", nil)
		transcript(t, home, "acme", say("something else"))
		drawn(t, home, "acme", drafted)
		hookWrote(t, home, "UserPromptSubmit", "")
		if lines := explained(t, "acme"); lines[0] != "acme  working" {
			t.Fatal(lines)
		}
	})
}

func TestAQuestionKeepsItsSeatUntilItIsAnswered(t *testing.T) {
	notice := `{"session": "acme", "kind": "needs", "text": "Which  colour?", "time": 5}`
	for name, each := range map[string]struct{ notice, screen, word, reason string }{
		"at its prompt":       {notice, prompting, "needs you", "Which colour?"},
		"its turn running":    {notice, spinning, "working", "-"},
		"a screen's own asks": {notice, asked, "needs you", "Enter to select · ↑/↓ to navigate · Esc to cancel"},
		"answered":            {strings.Replace(notice, `"time": 5`, `"time": 5, "answered_at": 6`, 1), prompting, "idle", "-"},
		"seen":                {strings.Replace(notice, `"time": 5`, `"time": 5, "seen": true`, 1), prompting, "idle", "-"},
		"a watcher's at rest": {strings.Replace(notice, `"time": 5`, `"time": 5, "watcher": true`, 1), prompting, "needs you", "Which colour?"},
		"a watcher's at work": {strings.Replace(notice, `"time": 5`, `"time": 5, "watcher": true`, 1), spinning, "working", "-"},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			drawn(t, home, "acme", each.screen)
			write(t, stateFile(home, "notify-acme.json"), each.notice)
			if lines := explained(t, "acme"); lines[0] != "acme  "+each.word || lines[1] != "  reason:    "+each.reason {
				t.Fatal(lines)
			}
		})
	}
}

// A look that finds a turn over asks what it kept back, dated at its end and said when it was said.
func TestALookAsksWhatTheSeatKeptBack(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	show := drawn(t, home, "acme", spinning)
	write(t, stateFile(home, "notify-acme.json"), `{"session": "acme", "kind": "needs", "text": "Older?", "time": 3, "asked_at": {"older?": 3}, "question_times": {"older?": 2}, "question_ids": {"older?": "card"}}`)
	if err := Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	if lines := explained(t, "acme"); lines[0] != "acme  working" {
		t.Fatal(lines)
	}
	if !Kept("acme") {
		t.Fatal("a turn still going asked what it kept")
	}
	show(prompting)
	if lines := explained(t, "acme"); lines[0] != "acme  needs you" || lines[1] != "  reason:    Older? Also: Which port?" {
		t.Fatal(lines)
	}
	if Kept("acme") {
		t.Fatal("what it asked is still kept back")
	}
	got, _ := run.ReadJSON(stateFile(home, "notify-acme.json"))
	keys := "session kind text time source watcher questions asked_at question_times question_ids said_at"
	if strings.Join(got.Keys(), " ") != keys || got.Str("text") != "Older? Also: Which port?" {
		t.Fatal(run.Line(got))
	}
	said, _ := got.Num("said_at")
	at, _ := got.Dict("question_times").Num("which port?")
	if ended, _ := got.Num("time"); said != at || ended < at || got.Dict("question_ids").Str("older?") != "card" {
		t.Fatal(run.Line(got))
	}
}

// The notice lock held by a typer: the look asks nothing, and what it kept is still the owner's.
func TestAKeptQuestionWhoseLockIsTakenStaysTheOwners(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	if err := Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	held, err := lock.Try(stateFile(home, "notify-acme.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	if lines := explained(t, "acme"); lines[0] != "acme  needs you" || lines[1] != "  reason:    stopped with work open" {
		t.Fatal(lines)
	}
	if _, err := os.Stat(stateFile(home, "notify-acme.json")); err == nil {
		t.Fatal("it asked under another's lock")
	}
}

// A seat's prompt answers the question it stood under, read from its conversation, once.
func TestThePromptInItsConversationAnswersTheQuestion(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "=acme:", "#{pane_id}")
	if err != nil {
		t.Fatal(err)
	}
	since := seconds(time.Now()) - 60
	write(t, stateFile(home, "notify-acme.json"), fmt.Sprintf(`{"session": "acme", "kind": "needs", "text": "Which?", "time": %f}`, since))
	write(t, stateFile(home, "card-acme.json"), fmt.Sprintf(`{"word": "needs you", "since": %f, "began": %f, "episode": "e", "sent": false}`, since, since))
	// the words of a prompt heard but not written yet answer nothing, past the time given them
	state := stateFile(home, "")
	if done, known, err := answerWritten(state, "acme", seconds(time.Now()), 0, false); done || !known || err != nil {
		t.Fatal(done, known, err)
	}
	transcript(t, home, "acme", fmt.Sprintf(`{"type": "user", "timestamp": %q, "message": {"role": "user", "content": "this one"}}`+"\n", time.Now().UTC().Format(time.RFC3339Nano)))
	looked(t, pane, "acme")
	got, _ := run.ReadJSON(stateFile(home, "notify-acme.json"))
	if at, _ := got.Num("answered_at"); at <= since {
		t.Fatal(run.Line(got))
	}
	if file, _ := run.ReadJSON(stateFile(home, "seat-acme.json")); file.Str("word") != "idle" {
		t.Fatal(run.Line(file))
	}
	if saved, _ := run.ReadJSON(stateFile(home, "watch.json")); saved == nil || saved.Dict("seen_at").Get("acme") == nil {
		t.Fatal("the answer let go of nothing")
	}
}

// A record as a real seat keeps it, and what its looks read of it: whose login holds its conversation.
func TestARealRecordIsReadWhereItsLookReadsIt(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"account": "second", "home_account": "second", "launched": 3, "asleep": 9, "seen": 4, "exited_since": nil,
		"reviewers": []string{"opus"}, "efforts": map[string]any{"opus": map[string]any{"effort": "xhigh"}},
		"rulebook_sha": "x", "rulebook_read": map[string]any{"conversation": "c", "sha": "x"}, "rulebook_told": nil, "filed": true, "unnamed": nil, "id_source": "claude-hook"})
	before, _ := os.ReadFile(stateFile(home, "session-acme.json"))
	// the login's own folder: filed under the usual one it would be nobody's error
	folder := regexp.MustCompile("[^A-Za-z0-9]").ReplaceAllString(filepath.Join(home, "work", "acme"), "-")
	write(t, filepath.Join(home, ".claude-second", "projects", folder, "conv-acme.jsonl"),
		`{"type": "assistant", "isApiErrorMessage": true, "message": {"content": [{"type": "text", "text": "API Error: 529 Overloaded"}]}}`+"\n")
	drawn(t, home, "acme", prompting)
	if lines := explained(t, "acme"); lines[0] != "acme  working" || lines[1] != "  reason:    retrying: overloaded" {
		t.Fatal(lines)
	}
	if after, _ := os.ReadFile(stateFile(home, "session-acme.json")); !strings.Contains(string(after), `"account": "second"`) || !strings.Contains(string(after), `"rulebook_sha": "x"`) || len(after) < len(before)-1 {
		t.Fatalf("its record became %s", after)
	}
}

// A file the look writes while another reader lists the home is no stranger to it.
func TestAWriteInFlightBesideALiveSeatIsNoRefusal(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	for _, file := range []string{"seat-acme.tmp", "notify-acme.tmp", "hook-acme.tmp", "card-acme.tmp", "session-acme.tmp", "stop-acme.json.tmp.123", ".hook-acme.lock", "input-acme.jsonl"} {
		write(t, stateFile(home, file), "")
	}
	if lines := explained(t, "acme"); lines[0] != "acme  idle" {
		t.Fatal(lines)
	}
}

// A reopened seat's mark is null, and keys Go does not read keep what the look found them holding.
func TestALookKeepsWhatItDoesNotRead(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	write(t, stateFile(home, "seat-acme.json"), `{"stopped_at": null, "closed_by_owner": null, "wait": null, "switched": 7, "stop_nudged": "e", "reopened_at": [1]}`)
	if lines := explained(t, "acme"); lines[0] != "acme  idle" {
		t.Fatal(lines)
	}
	file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if at, _ := file.Num("switched"); at != 7 || file.Str("stop_nudged") != "e" || len(file.List("reopened_at")) != 1 {
		t.Fatal(run.Line(file))
	}
}

func TestAWaitWorksUntilItIsOverAndToldUntilItIsTold(t *testing.T) {
	for name, each := range map[string]struct{ wait, word, reason string }{
		"going": {`{"kind": "pr", "on": "acme/1", "at": 5}`, "working", "waiting on acme/1"},
		"over":  {`{"kind": "pr", "on": "acme/1", "at": 5, "over": true}`, "working", "telling it its wait on acme/1 is over"},
		"told":  {`{"kind": "pr", "on": "acme/1", "at": 5, "over": true, "told": true}`, "idle", "-"},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			drawn(t, home, "acme", prompting)
			write(t, stateFile(home, "seat-acme.json"), `{"wait": `+each.wait+`}`)
			if lines := explained(t, "acme"); lines[0] != "acme  "+each.word || lines[1] != "  reason:    "+each.reason {
				t.Fatal(lines)
			}
		})
	}
}
