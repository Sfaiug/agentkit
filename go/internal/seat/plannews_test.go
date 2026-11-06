//go:build unix

package seat

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"agentkit/internal/commandhelp"
	"agentkit/internal/run"
)

func TestQueuedNewsKeepsAnOpenPlansPrompt(t *testing.T) {
	for _, kind := range []string{"wait", "run"} {
		for _, arrival := range []string{"before health", "before typing"} {
			t.Run(kind+"/"+arrival, func(t *testing.T) {
				home := sandbox(t)
				record(t, home, "acme", nil)
				state := stateFile(home, "")
				write(t, stateFile(home, "plan-acme.md"), openLine)
				stopped := run.Fields("stop_said", "The patch is ready.")
				write(t, stateFile(home, "seat-acme.json"), run.Encode(stopped))
				drawn(t, home, "acme", "The patch is ready.\n"+prompting)
				seat := Seat{Name: "acme", own: "claude"}
				at := seatAt{seat.Name, seat.own, "=" + seat.Name + ":"}
				found := at.sight(at.capture())
				path, news := stateFile(home, "seat-acme.json"), stopped
				if kind == "wait" {
					news.Set("wait", run.Fields("kind", "pr", "on", "https://github.com/acme/api/pull/7", "over", "PR #7 merged"))
				} else {
					path = filepath.Join(home, ".agentkit", "runs", "fix-api", "run.json")
					news = run.Fields("run_id", "fix-api", "state", "pass", "merged", false,
						"launched_session", "acme", "started_at", 1, "finished_at", 2)
				}
				incoming := filepath.Join(home, "news.json")
				if arrival == "before health" {
					write(t, path, run.Encode(news))
				} else {
					write(t, incoming, run.Encode(news))
					if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
						t.Fatal(err)
					}
					real, err := exec.LookPath("tmux")
					if err != nil {
						t.Fatal(err)
					}
					fake := filepath.Join(home, "bin", "tmux")
					// The pane lookup follows the first news check and precedes the typing lock.
					write(t, fake, "#!/bin/sh\nfor arg do\n  if [ \"$arg\" = display-message ] && "+
						commandhelp.ShellJoin([]string{"test", "-f", incoming})+"; then\n    "+
						commandhelp.ShellJoin([]string{"mv", incoming, path})+"\n  fi\ndone\nexec "+
						commandhelp.ShellJoin([]string{real})+" \"$@\"\n")
					if err := os.Chmod(fake, 0o700); err != nil {
						t.Fatal(err)
					}
					t.Setenv("PATH", filepath.Dir(fake)+string(os.PathListSeparator)+os.Getenv("PATH"))
				}
				if _, err := seat.nudgeOpenWork(state, found, func(line string) { t.Log(line) }); err != nil {
					t.Fatal(err)
				}
				if arrival == "before typing" {
					if _, err := os.Stat(incoming); !os.IsNotExist(err) {
						t.Fatal("news did not arrive before the typing lock", err)
					}
				}
				if sent, err := os.ReadFile(ownFile("input", seat.Name)); !os.IsNotExist(err) {
					t.Fatalf("news lost its prompt: input %s, error %v", sent, err)
				}
				file, err := run.ReadJSON(stateFile(home, "seat-acme.json"))
				if err != nil || file.Truthy("stop_nudged") {
					t.Fatalf("the stop was marked sent back: %v, error %v", file, err)
				}
			})
		}
	}
}
