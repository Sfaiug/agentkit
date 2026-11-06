//go:build unix

package seat

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

func questionRecoveryHome(t *testing.T) (string, Seat) {
	t.Helper()
	home := sandbox(t)
	for key, value := range map[string]string{"AGENTKIT_SESSION": "", "AK_RUN_ROLE": "", "AK_NOTIFY_SINK": "dry-run"} {
		t.Setenv(key, value)
	}
	record(t, home, "acme", map[string]any{"session_title": "acme"})
	if err := os.MkdirAll(filepath.Join(home, "work", "acme"), 0o700); err != nil {
		t.Fatal(err)
	}
	write(t, stateFile(home, "notify-acme.json"), `{"kind":"needs","text":"Which database?","time":100}`)
	write(t, stateFile(home, "seat-acme.json"), `{"word":"needs you","reason":"session closed: press 1 to reopen"}`)
	write(t, stateFile(home, "card-acme.json"), `{"word":"needs you","since":100,"began":100,"episode":"question","sent":true}`)
	fakeTmux(t, home, "acme", true)
	write(t, filepath.Join(home, "fake", "tmux"), `#!/bin/sh
case "$*" in '-L seat-test '*) ;; *) exit 1 ;; esac
case "$*" in
  *new-session*|*respawn-pane*) printf '%s\n' "$*" >> "$HOME/started"; [ "$RECOVERY_REFUSE" != 1 ] ;;
  *list-sessions*) [ "$RECOVERY_HELD" = 1 ] || exit 1; printf 'acme\t1\n' ;;
  *'#{pane_id} #{pane_dead}') printf '%%1 %s\n' "$RECOVERY_DEAD" ;;
  *list-panes*) printf 'acme\t%s\n' "$RECOVERY_DEAD" ;;
  *show-options*) echo '%1' ;;
  *session_activity*) printf '0\t1\n' ;;
  *session_attached*) echo 0 ;;
  *display-message*) echo acme ;;
esac
`)
	repo, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(home, "fake", "git"), fmt.Sprintf("#!/bin/sh\nprintf '%%s\\n' %q\n", repo))
	adapter := filepath.Join(home, "adapters", "claude.sh")
	write(t, adapter, "#!/bin/sh\necho /bin/true\n")
	for _, path := range []string{filepath.Join(home, "fake", "git"), adapter} {
		if err := os.Chmod(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", filepath.Dir(adapter))
	t.Setenv("RECOVERY_HELD", "0")
	t.Setenv("RECOVERY_DEAD", "1")
	t.Setenv("RECOVERY_REFUSE", "0")
	return home, Seat{Name: "acme", own: "claude"}
}

func TestQuestionRevivalKeepsItsConversationPaneAndContinuation(t *testing.T) {
	for _, held := range []bool{false, true} {
		t.Run(fmt.Sprint(held), func(t *testing.T) {
			home, seat := questionRecoveryHome(t)
			seat.held = held
			if held {
				t.Setenv("RECOVERY_HELD", "1")
			}
			_, record, _ := config.ResolveSession("acme")
			if held {
				chat, known := harness.Conversation("claude", record)
				if !known {
					t.Fatal("conversation not readable")
				}
				write(t, chat, "")
			}
			if carried, err := seat.reviveTurn(moment, QuestionContinue, func(string) {}, io.Discard); !carried || err != nil {
				t.Fatal(carried, err)
			}
			file := revivalFile("acme")
			if !run.Equal(file.Get("reopened_at"), []any{run.Float(seconds(moment))}) || !revivalLines(file) {
				t.Fatal(run.Line(file))
			}
			line := file.List("owed_lines")[0].(*run.Object)
			want := QuestionContinue + freshContinue
			verb := "new-session"
			if held {
				want, verb = QuestionContinue, "respawn-pane"
			}
			launched, _ := os.ReadFile(filepath.Join(home, "started"))
			if line.Str("line") != want || len(line.Str("id")) != 16 || !strings.Contains(string(launched), verb) {
				t.Fatalf("line=%s, launch=%s", run.Line(line), launched)
			}
			_, after, _ := config.ResolveSession("acme")
			if after["conversation"] != record["conversation"] || after["id_source"] != "launcher" || after["rulebook_sha"] == nil || after["launched"] == nil {
				t.Fatal(after)
			}
			if carried, err := seat.reviveTurn(moment.Add(time.Second), QuestionContinue, func(string) {}, io.Discard); !carried || err != nil {
				t.Fatal(carried, err)
			}
			second, _ := os.ReadFile(filepath.Join(home, "started"))
			if string(second) != string(launched) || !run.Equal(file.Get("owed_lines"), revivalFile("acme").Get("owed_lines")) {
				t.Fatal("a tick inside the backoff reopened or replaced its continuation")
			}
		})
	}
}

func TestQuestionRevivalBoundsDeathsAndAcceptsTheOldScalar(t *testing.T) {
	for _, deaths := range []any{
		run.Float(seconds(moment) - 1),
		[]any{run.Float(seconds(moment) - 1)},
		[]any{run.Float(1), run.Float(2), run.Float(3)},
	} {
		t.Run(fmt.Sprint(deaths), func(t *testing.T) {
			home, seat := questionRecoveryHome(t)
			if err := Write("acme", "reopened_at", deaths); err != nil {
				t.Fatal(err)
			}
			before := run.Line(revivalFile("acme"))
			if carried, err := seat.reviveTurn(moment, QuestionContinue, func(string) {}, io.Discard); !carried || err != nil {
				t.Fatal(carried, err)
			}
			if run.Line(revivalFile("acme")) != before {
				t.Fatal("the same death was recorded again")
			}
			if _, err := os.Stat(filepath.Join(home, "started")); !os.IsNotExist(err) {
				t.Fatal("a bounded death launched a harness")
			}
		})
	}
}

func TestAThirdQuestionDeathAsksOnceWithoutReopening(t *testing.T) {
	home, seat := questionRecoveryHome(t)
	if err := Write("acme", "reopened_at", []any{run.Float(seconds(moment) - 1800), run.Float(seconds(moment) - 600)}); err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if carried, err := seat.reviveTurn(moment, QuestionContinue, func(string) {}, io.Discard); !carried || err != nil {
			t.Fatal(carried, err)
		}
	}
	if len(revivalFile("acme").List("reopened_at")) != 3 {
		t.Fatal(run.Line(revivalFile("acme")))
	}
	notice, _ := run.ReadJSON(stateFile(home, "notify-acme.json"))
	if !strings.Contains(notice.Str("text"), "died again both times") || len(notice.List("questions")) != 2 {
		t.Fatal(run.Line(notice))
	}
	if _, err := os.Stat(filepath.Join(home, "started")); !os.IsNotExist(err) {
		t.Fatal("a third death launched a harness")
	}
}

func TestARefusedQuestionRevivalKeepsItsDeathAndReportsTheFailure(t *testing.T) {
	home, seat := questionRecoveryHome(t)
	t.Setenv("RECOVERY_REFUSE", "1")
	if carried, err := seat.reviveTurn(moment, QuestionContinue, func(string) {}, io.Discard); !carried || err != nil {
		t.Fatal(carried, err)
	}
	if len(revivalFile("acme").List("reopened_at")) != 1 || revivalFile("acme").Truthy("owed_lines") {
		t.Fatal(run.Line(revivalFile("acme")))
	}
	notice, _ := run.ReadJSON(stateFile(home, "notify-acme.json"))
	if !strings.Contains(notice.Str("text"), "could not:") || !strings.HasPrefix(notice.Str("source"), "revive:acme:turn:") {
		t.Fatal(run.Line(notice))
	}
	_, after, _ := config.ResolveSession("acme")
	if after["conversation"] != "conv-acme" || after["launched"] != nil {
		t.Fatal(after)
	}
}

func TestQuestionRevivalLeavesOwnerStoppedAndSleepingSeatsAlone(t *testing.T) {
	for _, kind := range []string{"stopped", "asleep"} {
		t.Run(kind, func(t *testing.T) {
			home, _ := questionRecoveryHome(t)
			if kind == "stopped" {
				write(t, stateFile(home, "seat-acme.json"), `{"stopped_at":1,"closed_by_owner":true}`)
			} else {
				record(t, home, "acme", map[string]any{"asleep": 1})
			}
			found, known := Looking(moment)
			if !known {
				t.Fatal("seat not readable")
			}
			if carried, err := found.ReviveTurns(moment, nil, func(string) {}, io.Discard); !carried || err != nil {
				t.Fatal(carried, err)
			}
			if _, err := os.Stat(filepath.Join(home, "started")); !os.IsNotExist(err) || revivalFile("acme").Truthy("reopened_at") {
				t.Fatal("an intentional close was revived")
			}
		})
	}
}

func TestOwedLinesHandOverLiveForeignOrPartlyTypedLinesAtTheirOwnTurn(t *testing.T) {
	for _, kind := range []string{"foreign", "typed"} {
		t.Run(kind, func(t *testing.T) {
			home, _ := questionRecoveryHome(t)
			t.Setenv("RECOVERY_HELD", "1")
			t.Setenv("RECOVERY_DEAD", "0")
			line := run.Fields("line", "other work", "id", "line")
			if kind == "typed" {
				line.Set("line", QuestionContinue)
				line.Set("typed", run.Fields("line", QuestionContinue, "seat", 1))
			}
			if err := Write("acme", "owed_lines", []any{line}); err != nil {
				t.Fatal(err)
			}
			before := run.Line(revivalFile("acme"))
			if carried, err := TellRevivalLines(func(string) {}); carried || err != nil {
				t.Fatal(carried, err)
			}
			if run.Line(revivalFile("acme")) != before {
				t.Fatal("handover changed the pending line")
			}
			if _, err := os.Stat(filepath.Join(home, "started")); !os.IsNotExist(err) {
				t.Fatal("delivering a line launched a harness")
			}
		})
	}
}

func TestRevivalLeavesLaterDeathsAndUnsupportedHarnessesToPython(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+gemini)
	cwd := filepath.Join(home, "work", "acme")
	if err := os.MkdirAll(cwd, 0o700); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(home, "bin")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *show-options*) echo %1 ;;
  *'#{pane_dead_time}'*) echo "$DIED" ;;
  *'#{session_name}'*) echo acme ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	// a later death is still reopened as its number opens it, by what it waited on ending
	for _, each := range []struct {
		model, own, death  string
		supported, canOpen bool
	}{
		{"opus", "claude", "1005", true, true},
		{"opus", "claude", "1010", false, true},
		{"opus", "claude", "unreadable", false, true},
		{"gemini", "antigravity", "1005", false, false},
	} {
		t.Run(each.own+"/"+each.death, func(t *testing.T) {
			t.Setenv("DIED", each.death)
			record(t, home, "acme", map[string]any{"orchestrator": each.model, "launched": 1000})
			home := Home{Seats: []Seat{{Name: "acme", own: each.own, held: true}}}
			if got := home.Revivals()[0]; got.Supported != each.supported || got.CanOpen != each.canOpen {
				t.Fatalf("supported=%v, can open=%v", got.Supported, got.CanOpen)
			}
		})
	}
}

func TestAGoingRunDecidesTheLiveSeatBeforeItsIdlePlan(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	show := drawn(t, home, "acme", prompting)
	write(t, stateFile(home, "plan-acme.md"), openLine)
	write(t, seatFile("acme"), `{"stop_said":"your plan owes a line"}`)
	runRecord(t, home, "r-build", map[string]any{"state": "running"})
	if _, known := Looking(time.Now()); !known {
		t.Fatal("a send-back not reached on the ladder hid a live seat")
	}
	show("")
	if _, known := Lives(time.Now()); !known {
		t.Fatal("a starting harness's blank screen hid its going run")
	}
}

func TestADeathDuringALiveLookKeepsTheLastScreenForRevival(t *testing.T) {
	home := sandbox(t)
	path := seatFile("acme")
	write(t, path, `{"state":"at_prompt","rule":"prompt.composer","stall":"overloaded","login":"expired"}`)
	previous, _ := run.ReadJSON(path)
	seat := Seat{Name: "acme", own: "claude"}
	if _, err := seat.keep(stateFile(home, ""), "", true, sight{state: "at_prompt", rule: "none"}, previous, 1000); err != nil {
		t.Fatal(err)
	}
	file, _ := run.ReadJSON(path)
	if file.Str("state") != "at_prompt" || file.Str("rule") != "prompt.composer" || file.Truthy("stall") || file.Truthy("login") {
		t.Fatal(run.Line(file))
	}
}

func TestAQueuedContinuationSurvivesTheNextReopen(t *testing.T) {
	home := sandbox(t)
	cwd := filepath.Join(home, "work", "acme")
	if err := os.MkdirAll(cwd, 0o700); err != nil {
		t.Fatal(err)
	}
	record(t, home, "acme", nil)
	for _, rule := range []string{"prompt.composer", "none"} {
		file := run.Fields("state", "at_prompt", "rule", rule, "owed_lines", []any{
			run.Fields("id", "old-death", "line", "your run r-build is still going"),
		})
		write(t, seatFile("acme"), run.Line(file))
		found, known := Looking(time.Now())
		if !known || len(found.Revivals()) != 1 || !found.Revivals()[0].CanOpen {
			t.Fatalf("a continuation at %s prevented reopening", rule)
		}
		after, _ := run.ReadJSON(seatFile("acme"))
		if !run.Equal(file, after) {
			t.Fatalf("reading reopening changed its queued line: %s", run.Line(after))
		}
	}
}

func TestADeathBetweenListingAndCaptureKeepsTheLastPrompt(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	write(t, seatFile("acme"), `{"state":"at_prompt","rule":"prompt.composer"}`)
	bin := filepath.Join(home, "bin")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-panes*) echo '%1 0' ;;
  *capture-pane*) echo 'Pane is dead (status 0)' ;;
  *display-message*) echo 1 ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	seat := Seat{Name: "acme", own: "claude"}
	if _, err := seat.look(stateFile(home, ""), 1000); err != nil {
		t.Fatal(err)
	}
	file, _ := run.ReadJSON(seatFile("acme"))
	if file.Str("rule") != "prompt.composer" {
		t.Fatalf("a dead pane replaced the last prompt: %s", run.Line(file))
	}
}

func TestADeathAfterListingLeavesLiveRowsForTheRevivalRow(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	runRecord(t, home, "r-build", map[string]any{"state": "running"})
	write(t, seatFile("acme"), `{"state":"at_prompt","rule":"prompt.composer"}`)
	bin := filepath.Join(home, "fake")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in *'-L seat-test '*) ;; *) exit 1 ;; esac
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*-a*) printf 'acme\t0\n' ;;
  *list-panes*) echo '%1 0' ;;
  *capture-pane*) echo 'Pane is dead (status 0)' ;;
  *display-message*'#{pane_dead}'*) echo 1 ;;
  *display-message*'#{session_attached}'*) printf '0\t%%1\t%s/work/acme\n' "$HOME" ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	if live, known := Lives(time.Now()); !known || len(live) != 0 {
		t.Fatalf("a known death prevented the live rows: known=%v, lives=%v", known, live)
	}
	carried, err := Health("acme", func(Live) bool {
		t.Fatal("a dead harness reached the live-screen health predicate")
		return false
	}, func(string) {})
	if !carried || err != nil {
		t.Fatal(carried, err)
	}
	file, _ := run.ReadJSON(seatFile("acme"))
	if file.Str("word") != "working" || file.Str("rule") != "prompt.composer" {
		t.Fatalf("a dead seat lost its run or its last screen: %s", run.Line(file))
	}
}
