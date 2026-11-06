package seat

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hookfact"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

func accountAdapter(t *testing.T, home, body string) {
	t.Helper()
	dir := filepath.Join(home, "adapters")
	path := filepath.Join(dir, "claude.sh")
	write(t, path, "#!/bin/sh\n"+body)
	if err := os.Chmod(path, 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", dir)
	repo, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(home, "fake")
	write(t, filepath.Join(bin, "git"), "#!/bin/sh\nprintf '%s\\n' "+commandhelp.ShellJoin([]string{repo})+"\n")
	if err := os.Chmod(filepath.Join(bin, "git"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func TestAccountLaunchFreezesItsLastLookThroughRespawnAndAlwaysThaws(t *testing.T) {
	for _, outcome := range []string{"started", "declined", "refused", "expired"} {
		t.Run(outcome, func(t *testing.T) {
			home := accountHome(t)
			drawn(t, home, "acme", prompting)
			real, err := exec.LookPath("tmux")
			if err != nil {
				t.Fatal(err)
			}
			bin := filepath.Join(home, "fake")
			write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in *respawn-pane*)
  `+commandhelp.ShellJoin([]string{real})+` -L seat-test display-message -p -t =acme: '#{pane_input_off}' > "$HOME/frozen-at-respawn"
  [ "$REFUSE_RESPAWN" != 1 ] || exit 1 ;;
esac
exec `+commandhelp.ShellJoin([]string{real})+` "$@"
`)
			if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
			t.Setenv("REFUSE_RESPAWN", "0")
			if outcome == "refused" {
				t.Setenv("REFUSE_RESPAWN", "1")
			}
			before, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
			fact := `{"event":"Stop","holds":["shell"],"at":1}`
			write(t, stateFile(home, "hook-acme.json"), fact)
			rulebook := stateFile(home, "rulebook-acme.md")
			write(t, rulebook, "rules\n")
			back := reopening{name: "acme", held: true, model: config.Model{Harness: "claude"}, still: func(string) bool {
				off, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "=acme:", "#{pane_input_off}")
				if err != nil || off != "1" {
					t.Fatal("the final look accepted input", off, err)
				}
				if outcome == "expired" {
					tmux.Ask(tmux.Own(), "set-option", "-pu", "-t", "=acme:", frozenOption)
				}
				return outcome != "declined"
			}}
			_, err = back.launch(filepath.Join(home, ".agentkit", "state"), rulebook, []string{"sleep", "600"}, "conv-acme")
			if (err == nil) != (outcome == "started") {
				t.Fatal(outcome, err)
			}
			if outcome == "declined" && !errors.Is(err, errAccountChanged) {
				t.Fatal(err)
			}
			off, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "=acme:", "#{pane_input_off}")
			if err != nil || off != "0" {
				t.Fatal("pane stayed frozen", off, err)
			}
			if outcome != "declined" {
				read, _ := os.ReadFile(filepath.Join(home, "frozen-at-respawn"))
				if string(read) != "1\n" {
					t.Fatal("respawn was not protected", string(read))
				}
			}
			if outcome != "started" {
				after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
				read, _ := os.ReadFile(stateFile(home, "hook-acme.json"))
				if !run.Equal(before, after) || string(read) != fact {
					t.Fatal("a refused move changed the old harness's record or facts")
				}
			}
		})
	}
}

func TestSpentAccountDefersWhenAdapterPreparationChangesHeldWork(t *testing.T) {
	home := accountHome(t)
	accountMeters(t, home, 100, 10)
	drawn(t, home, "acme", prompting)
	accountAdapter(t, home, `case "$1" in
  auth) exit 0 ;;
  interactive) printf '%s\n' '{"event":"Stop","holds":["monitor"],"at":1}' > "$HOME/.agentkit/state/hook-acme.json"; echo 'sleep 600' ;;
esac
`)
	lives, known := Lives(time.Now())
	if !known || len(lives) != 1 {
		t.Fatal("seat unread")
	}
	before := lives[0].Record
	if carried, err := MoveAccount(lives[0], func(string) {}); carried || err != nil {
		t.Fatal(carried, err)
	}
	after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	work := hookfact.Standing("acme").Holds
	if !run.Equal(before, after) || len(work) != 1 || work[0] != "monitor" {
		t.Fatal("the late Stop was lost", after, work)
	}
}

func TestFreshReopenKeepsItsAccount(t *testing.T) {
	home := accountHome(t)
	accountAdapter(t, home, "printf '%s' \"$AGENTKIT_ACCOUNT\" > \"$HOME/adapter-account\"\necho 'sleep 600'\n")
	back := reopening{name: "acme", account: "second", model: config.Model{Harness: "claude"}}
	cmd, conversation, known := back.command(nil)
	account, _ := os.ReadFile(filepath.Join(home, "adapter-account"))
	if !known || conversation == "" || string(account) != "second" || cmd[1] != "AGENTKIT_ACCOUNT=second" {
		t.Fatal(cmd, conversation, string(account), known)
	}
}

func TestAnAccountMoveDoesNotNudgeTheNewHarnessFromTheOldStop(t *testing.T) {
	home := accountHome(t)
	accountMeters(t, home, 100, 10)
	write(t, stateFile(home, "plan-acme.md"), openLine)
	drawn(t, home, "acme", "Work remains.\n"+prompting)
	_, record, _ := config.ResolveSession("acme")
	chat, _ := harness.Conversation("claude", record)
	write(t, chat, `{"type":"user","message":{"role":"user","content":"hello"}}`+"\n")
	line := commandhelp.ShellJoin([]string{"sh", "-c", "cat " + commandhelp.ShellJoin([]string{filepath.Join(home, "screen-acme")}) + "; sleep 600"})
	accountAdapter(t, home, "case \"$1\" in auth) exit 0 ;; interactive) "+commandhelp.ShellJoin([]string{"printf", "%s\n", line})+" ;; esac\n")
	if carried, err := Health("acme", func(Live) bool { return true }, func(string) {}); !carried || err != nil {
		t.Fatal(carried, err)
	}
	after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	if after.Str("account") != "second" {
		t.Fatal("seat did not move", after)
	}
	if input, err := os.ReadFile(stateFile(home, "input-acme.jsonl")); err == nil {
		t.Fatalf("the old Stop prompted the new harness: %s", input)
	}
}
