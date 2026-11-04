package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestAdviceKeepsNewerSeatFieldsAndRoleEfforts(t *testing.T) {
	home := sandbox(t)
	t.Setenv("PATH", t.TempDir())
	path := filepath.Join(home, ".agentkit", "state", "session-acme.json")
	write(t, path, `{"orchestrator":"fable","workers":["fable"],"reviewers":["fable"]}`)
	selected, err := ConfigSelection("acme")
	if err != nil {
		t.Fatal(err)
	}
	write(t, path, `{"orchestrator":"fable","workers":["fable"],"reviewers":["astra"],"efforts":{"astra":{"effort":"low","exec_effort":"high","extra":17}},"conversation":"newer"}`)
	saved, err := SaveAdvice("acme", selected, []config.EffortStep{
		{Model: "astra", Key: "effort", Effort: "high"},
		{Model: "astra", Key: "exec_effort"},
	})
	if err != nil {
		t.Fatal(err)
	}
	want, _ := run.Decode([]byte(`{"effort":"low","extra":17}`))
	disk, err := run.ReadJSON(path)
	if err != nil || !run.Equal(disk, saved) || !run.Equal(disk.Dict("efforts").Get("astra"), want) ||
		disk.Str("orchestrator") != "fable" || disk.Str("conversation") != "newer" ||
		run.Line(disk.Get("workers")) != `["astra"]` || run.Line(disk.Get("reviewers")) != `["astra"]` {
		t.Fatalf("advice lost current fields or moved its orchestrator: %s, %v", run.Line(disk), err)
	}
	if selected.Dict("efforts") != nil || run.Line(selected.Get("workers")) != `["fable"]` {
		t.Fatal("saving mutated the displayed selection")
	}
}

func TestAdviceDefaultsKeepLegacySeatsAndFailedWritesLeaveThemAlone(t *testing.T) {
	for _, blocked := range []bool{true, false} {
		t.Run(map[bool]string{true: "blocked", false: "saved"}[blocked], func(t *testing.T) {
			home := sandbox(t)
			dir := filepath.Join(home, ".agentkit")
			path := filepath.Join(dir, "state", "session-acme.json")
			record := `{"orchestrator":"astra","workers":["astra"],"reviewers":["astra"]}`
			write(t, path, record)
			before, err := os.ReadFile(filepath.Join(dir, "config.toml"))
			if err != nil {
				t.Fatal(err)
			}
			if blocked {
				if err := os.Mkdir(filepath.Join(dir, "config.tmp"), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			selected := run.NewObject()
			selected.Set("orchestrator", "fable")
			selected.Set("workers", []any{"fable"})
			_, err = SaveAdvice("", selected, []config.EffortStep{
				{Model: "astra", Key: "effort", Effort: "medium"},
				{Model: "astra", Key: "exec_effort", Effort: "medium"},
				{Model: "astra", Key: "review_effort", Effort: "high"},
			})
			if blocked {
				after, _ := os.ReadFile(filepath.Join(dir, "config.toml"))
				seat, _ := os.ReadFile(path)
				if err == nil || string(before) != string(after) || string(seat) != record {
					t.Fatalf("failed save changed a file: %s, %s, %v", after, seat, err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			models, _ := config.Models()
			defaults, _ := config.Defaults()
			seat, _ := run.ReadJSON(path)
			if defaults.Orchestrator != "astra" || len(defaults.Reviewers) != 1 || defaults.Reviewers[0] != "astra" ||
				models["astra"].Efforts["effort"] != "medium" || models["astra"].Efforts["review_effort"] != "high" ||
				models["astra"].Efforts["exec_effort"] != "" || seat.Dict("efforts").Dict("astra").Str("effort") != "xhigh" {
				t.Fatalf("defaults or a legacy seat took the wrong efforts: %+v, %+v, %s", defaults, models["astra"], run.Line(seat))
			}
		})
	}
}
