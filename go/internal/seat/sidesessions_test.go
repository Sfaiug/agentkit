package seat

import (
	"os"
	"os/exec"
	"testing"
	"time"

	"agentkit/internal/tmux"
)

func TestASideSessionOfALegacySeatStays(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	sandbox(t)
	for _, server := range []string{tmux.Default, tmux.Own()} {
		t.Cleanup(func() { tmux.Ask(server, "kill-server") })
	}
	if err := tmux.Spawn(tmux.Default, os.Getenv("PATH"), "new-session", "-d", "-s", "old-seat", "sleep 60", ";",
		"set-option", "-t", "=old-seat:", tmux.Mark, "1"); err != nil {
		t.Fatal(err)
	}
	if err := tmux.Spawn(tmux.Own(), os.Getenv("PATH"), "new-session", "-d", "-s", "serve", "sleep 60", ";",
		"set-environment", "-t", "=serve:", ownerTag, "old-seat"); err != nil {
		t.Fatal(err)
	}
	if carried, err := Sweep(time.Now(), func(line string) { t.Error(line) }); !carried || err != nil {
		t.Fatal(carried, err)
	}
	if tmux.Absent(tmux.Own(), "=serve") {
		t.Error("the sweep closed the work of a seat that lives on the default server")
	}
}
