package seat

import (
	"errors"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

const (
	prompting = "────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
	spinning  = "✻ Moonwalking… (10s · ↓ 207 tokens)\n────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
	asked     = "Which one?\nEnter to select · ↑/↓ to navigate · Esc to cancel\n"
	drafted   = "────────\n❯ fix the build\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
)

// drawn opens a live seat on the test's own server, showing that screen until it is told another.
func drawn(t *testing.T, home, name, text string) func(string) {
	t.Helper()
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	t.Cleanup(func() { tmux.Ask(tmux.Own(), "kill-server") })
	file := filepath.Join(home, "screen-"+name)
	show := func(text string) {
		t.Helper()
		write(t, file, text)
		tmux.Ask(tmux.Own(), "send-keys", "-t", "="+name+":", "Enter")
		for deadline := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
			shown, _ := tmux.Ask(tmux.Own(), "capture-pane", "-p", "-J", "-t", "="+name+":")
			if strings.TrimSpace(shown) == strings.TrimSpace(text) {
				return
			}
			if time.Now().After(deadline) {
				t.Fatalf("never drew %q: %q", text, shown)
			}
		}
	}
	write(t, file, text)
	draw := "while :; do clear; cat " + file + "; read _; done"
	if err := tmux.Spawn(tmux.Own(), os.Getenv("PATH"), "new-session", "-d", "-s", name, "-x", "80", "-y", "24", "sh", "-c", draw); err != nil {
		t.Fatal(err)
	}
	if _, err := tmux.Ask(tmux.Own(), "set-option", "-t", "="+name+":", tmux.Mark, "1"); err != nil {
		t.Fatal(err)
	}
	show(text)
	return show
}

func stateFile(home, file string) string { return filepath.Join(home, ".agentkit", "state", file) }

func explained(t *testing.T, name string) []string {
	t.Helper()
	home, known := Looking(time.Now())
	if !known {
		t.Fatal("Go does not read this home")
	}
	lines, found, err := home.Explain(name, time.Now())
	if err != nil || !found {
		t.Fatal(found, err)
	}
	return lines
}

func TestALiveSeatIsLeftToPythonWhereNothingAsksItsScreen(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	if _, known := Read(time.Now()); known {
		t.Fatal("Read took a live seat, which `ak orch list` does not read yet")
	}
}

func TestAHomePythonHasLookedAtIsStillRead(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	write(t, stateFile(home, "run-records.db"), "its cache of runs/")
	if lines := explained(t, "acme"); lines[0] != "acme  idle" {
		t.Fatal(lines)
	}
}

func TestTheWordComesOffTheScreen(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	show := drawn(t, home, "acme", prompting)
	for _, each := range []struct {
		screen, word, reason, authority, rule, evidence string
	}{
		{prompting, "idle", "-", "screen", "prompt.composer", "⏵⏵ bypass permissions on (shift+tab to cycle)"},
		{spinning, "working", "-", "screen", "working.spinner", "✻ Moonwalking… (10s · ↓ 207 tokens)"},
		{asked, "needs you", "Enter to select · ↑/↓ to navigate · Esc to cancel", "screen", "asking.question", "Enter to select · ↑/↓ to navigate · Esc to cancel"},
		{drafted, "idle", "-", "screen", "prompt.draft", "fix the build"},
	} {
		show(each.screen)
		lines := explained(t, "acme")
		want := []string{"acme  " + each.word, "  reason:    " + each.reason, "  authority: " + each.authority + "  rule: " + each.rule, "  evidence:  " + each.evidence}
		for at, line := range want {
			if lines[at] != line {
				t.Errorf("%s: line %d is %q, not %q", each.rule, at, lines[at], line)
			}
		}
		if !strings.HasPrefix(lines[4], "  since:     20") || !strings.HasSuffix(lines[4], "s ago)") {
			t.Errorf("%q", lines[4])
		}
	}
	file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if file.Str("unsent") != "fix the build" {
		t.Errorf("what nobody sent: %q", file.Str("unsent"))
	}
}

// harnessBesideSpare marks the seat's pane as its harness's, left on exit, and selects a spare window.
func harnessBesideSpare(t *testing.T, name string) (pane string) {
	t.Helper()
	target := "=" + name + ":"
	pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", target, "#{pane_id}")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := tmux.Ask(tmux.Own(), "set-option", "-t", target, tmux.HarnessPane, pane, ";", "set-option", "-t", target, "remain-on-exit", "on"); err != nil {
		t.Fatal(err)
	}
	if _, err := tmux.Ask(tmux.Own(), "new-window", "-t", target, "printf 'spare\\n'; sleep 600"); err != nil {
		t.Fatal(err)
	}
	return pane
}

// harnessExits kills what that pane runs, as a crash does, its last frame left on the screen.
func harnessExits(t *testing.T, pane string) {
	t.Helper()
	pid, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", pane, "#{pane_pid}")
	if err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command("kill", "-9", pid).CombinedOutput(); err != nil {
		t.Fatal(string(out), err)
	}
	for deadline := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		if dead, _ := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", pane, "#{pane_dead}"); dead == "1" {
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("the harness never exited")
		}
	}
}

// A spare window the owner selected is not the seat's screen, and its harness's last frame, once
// it has exited, is no turn in flight.
func TestALookReadsTheHarnessPaneWhicheverWindowIsActive(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	// a row above the spinner, as tmux scrolls one off the top to say the pane is dead
	drawn(t, home, "acme", "earlier output\n"+spinning)
	pane := harnessBesideSpare(t, "acme")
	if lines := explained(t, "acme"); lines[0] != "acme  working" {
		t.Fatal(lines)
	}
	harnessExits(t, pane)
	if lines := explained(t, "acme"); lines[0] != "acme  idle" {
		t.Fatal(lines)
	}
}

// A blank capture keeps the error a seat was retrying past; a harness that exited retries nothing,
// and the seat file says so too.
func TestAHarnessThatExitedRetriesNothing(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", "API Error: 529 Overloaded\n"+prompting)
	pane := harnessBesideSpare(t, "acme")
	if lines := explained(t, "acme"); lines[0] != "acme  working" {
		t.Fatal(lines)
	}
	harnessExits(t, pane)
	if lines := explained(t, "acme"); lines[0] != "acme  idle" {
		t.Fatal(lines)
	}
	if got, _ := run.ReadJSON(stateFile(home, "seat-acme.json")); got == nil || got.Get("stall") != nil {
		t.Fatal(run.Line(got))
	}
}

// A tick's environment may name no UTF-8 locale, where tmux would answer every format without its tabs.
func TestASeatIsReadOutsideAUTF8Locale(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", spinning)
	t.Setenv("LC_ALL", "C")
	if lines := explained(t, "acme"); lines[0] != "acme  working" {
		t.Fatal(lines)
	}
}

func TestTheSeatFileIsPythonsAndMovesOnlyWithTheWord(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	show := drawn(t, home, "acme", spinning)
	path := stateFile(home, "seat-acme.json")
	explained(t, "acme")
	first, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	file, _ := run.ReadJSON(path)
	keys := "state since began authority rule evidence hooked hooked_at hooked_event interrupted stall login turn_began session word reason unsent word_since word_from"
	if got := strings.Join(file.Keys(), " "); got != keys {
		t.Fatalf("%s\nnot %s", got, keys)
	}
	if !strings.HasPrefix(string(first), `{"state": "working", "since": `) || !strings.HasSuffix(string(first), "\"word_from\": [\"working\", \"working.spinner\", \"\"]}\n") ||
		strings.ContainsAny(string(first), "✻…") {
		t.Fatalf("%s", first)
	}
	explained(t, "acme")
	if again, _ := os.ReadFile(path); string(again) != string(first) {
		t.Fatalf("an unchanged screen wrote %s", again)
	}
	began := file.Get("word_since")
	show(strings.Replace(spinning, "10s", "11s", 1))
	explained(t, "acme")
	moved, _ := run.ReadJSON(path)
	if !run.Equal(moved.Get("word_since"), began) || !run.Equal(moved.Get("began"), began) {
		t.Fatal("the spinner's own timer moved when the word began")
	}
	show(prompting)
	explained(t, "acme")
	moved, _ = run.ReadJSON(path)
	if moved.Str("word") != "idle" || run.Equal(moved.Get("word_since"), began) {
		t.Fatalf("%s %v", moved.Str("word"), moved.Get("word_since"))
	}
}

func TestWhatItsConversationRecordedSpeaksForTheScreen(t *testing.T) {
	for name, each := range map[string]struct{ entries, word, reason, login string }{
		"a refusal is typed back past": {`{"type": "assistant", "isApiErrorMessage": true, "message": {"content": [{"type": "text", "text": "API Error: 529 Overloaded"}]}}`,
			"working", "retrying: overloaded", ""},
		"a login is the tick's": {`{"type": "assistant", "isApiErrorMessage": true, "message": {"content": [{"type": "text", "text": "Please run /login"}]}}`,
			"idle", "", "Please run /login"},
		"the conversation went on": {`{"type": "assistant", "isApiErrorMessage": true, "message": {"content": "API Error"}}` + "\n" + `{"type": "user", "message": {"role": "user", "content": "go on"}}`,
			"idle", "", ""},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			transcript(t, home, "acme", each.entries+"\n")
			drawn(t, home, "acme", prompting)
			explained(t, "acme")
			file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
			if file.Str("word") != each.word || file.Str("reason") != each.reason || file.Str("login") != each.login {
				t.Fatalf("%q %q %q", file.Str("word"), file.Str("reason"), file.Str("login"))
			}
		})
	}
}

func TestWhatTheLookDoesNotReadYetWritesNothing(t *testing.T) {
	for name, setup := range map[string]func(t *testing.T, home string){
		"a run parked on its login": func(t *testing.T, home string) {
			runRecord(t, home, "going", map[string]any{"state": "waiting_login", "started_at": 1, "finished_at": nil})
		},
		"a usage refusal kept with no wait": func(t *testing.T, home string) {
			write(t, stateFile(home, "seat-acme.json"), `{"usage_refusal": {"line": "spent", "at": 1}}`)
		},
		"a stall the tick keeps": func(t *testing.T, home string) {
			write(t, stateFile(home, "watch.json"), `{"stalls": {"acme": {"kind": "login", "at": 1}}}`)
		},
		"a harness whose screen Go does not read": func(t *testing.T, home string) {
			// A synthetic harness stays unread as real harnesses gain screen support.
			write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+"[models.vela]\nharness='no-such-harness'\nmodel='vela'\neffort='high'\nprovider='test'\n")
			record(t, home, "acme", map[string]any{"orchestrator": "vela"})
		},
		"the owner's stop mark": func(t *testing.T, home string) {
			write(t, stateFile(home, "seat-acme.json"), `{"stopped_at": 1, "closed_by_owner": true}`)
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			drawn(t, home, "acme", prompting)
			waited, known := Looking(time.Now()) // as a look reads the home before it waits for its lock
			if !known {
				t.Fatal("Go did not read the seat")
			}
			setup(t, home)
			before := stateFiles(t, home)
			if _, known := Looking(time.Now()); known {
				t.Fatal("Go took it")
			}
			if _, _, err := waited.Explain("acme", time.Now()); !errors.Is(err, ErrUnread) {
				t.Fatalf("what came during the wait was looked past: %v", err)
			}
			after := stateFiles(t, home)
			delete(after, "seat-acme.announce") // the lock it waited on, which holds nothing
			if !maps.Equal(before, after) {
				t.Fatalf("refusing wrote: %v, then %v", before, after)
			}
		})
	}
}

func stateFiles(t *testing.T, home string) map[string]string {
	t.Helper()
	entries, err := os.ReadDir(stateFile(home, ""))
	if err != nil {
		t.Fatal(err)
	}
	files := map[string]string{}
	for _, entry := range entries {
		data, err := os.ReadFile(stateFile(home, entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		files[entry.Name()] = string(data)
	}
	return files
}

func TestARuleGoCannotSayLeavesTheHarnessToPython(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	adapters := filepath.Join(home, "adapters")
	write(t, filepath.Join(adapters, "claude.toml"), "[[rule]]\nid = \"x\"\nstate = \"working\"\nnewest = '[^\\S]'\n")
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	eyes.Delete("claude")
	t.Cleanup(func() { eyes.Delete("claude") })
	if _, known := Looking(time.Now()); known {
		t.Fatal("Go took a harness whose rule it cannot say")
	}
	if _, err := os.Stat(stateFile(home, "seat-acme.json")); err == nil {
		t.Fatal("refusing wrote the seat file")
	}
}
