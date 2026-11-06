package seat

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

func TestAdviceFailurePreservesEveryLegacyRecord(t *testing.T) {
	for _, failure := range []string{"later record", "config rename", "busy record"} {
		t.Run(failure, func(t *testing.T) {
			home := sandbox(t)
			dir := filepath.Join(home, ".agentkit")
			state := filepath.Join(dir, "state")
			record := "{\n  \"orchestrator\":\"astra\", \"workers\":[\"astra\"], \"reviewers\":[\"astra\"]\n}\n"
			for _, name := range []string{"alpha", "zulu"} {
				write(t, filepath.Join(state, "session-"+name+".json"), record)
			}
			before, err := os.ReadFile(filepath.Join(dir, "config.toml"))
			if err != nil {
				t.Fatal(err)
			}
			if failure == "later record" {
				if err := os.Mkdir(filepath.Join(state, "session-zulu.tmp"), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			if failure == "busy record" {
				held, err := lock.Try(filepath.Join(state, ".session-zulu.lock"))
				if err != nil {
					t.Fatal(err)
				}
				defer held.Close()
			}
			selected, err := ConfigSelection("alpha")
			if err != nil {
				t.Fatal(err)
			}
			steps := []config.EffortStep{{Model: "astra", Key: "effort", Effort: "medium"}}
			if failure == "config rename" {
				models, _ := config.Models()
				bound, _ := config.Bind()
				offered, _ := config.Offered()
				err = savingEfforts(bound.Models, models, offered, tryLocks, func(keep func() error) error {
					return config.RememberDefaults("astra", []string{"astra"}, []string{"astra"}, func() error {
						if err := keep(); err != nil {
							return err
						}
						for _, name := range []string{"alpha", "zulu"} {
							file, err := lock.Try(filepath.Join(state, ".session-"+name+".lock"))
							if file != nil {
								file.Close()
							}
							if !errors.Is(err, lock.ErrHeld) {
								t.Fatalf("%s's record lock was released before config saved: %v", name, err)
							}
						}
						return os.Remove(filepath.Join(dir, "config.tmp"))
					}, steps...)
				})
			} else {
				_, err = SaveAdvice("", selected, steps)
			}
			after, _ := os.ReadFile(filepath.Join(dir, "config.toml"))
			if err == nil || string(after) != string(before) || selected.Dict("efforts") != nil {
				t.Fatalf("failed save changed config or the displayed selection: %s, %s, %v", after, run.Line(selected), err)
			}
			for _, name := range []string{"alpha", "zulu"} {
				path := filepath.Join(state, "session-"+name+".json")
				after, err := os.ReadFile(path)
				info, statErr := os.Stat(path)
				if err != nil || statErr != nil || string(after) != record || info.Mode().Perm() != 0o600 {
					t.Fatalf("%s changed after a failed save: %s, %v, %v", name, after, err, statErr)
				}
			}
		})
	}
}

func TestAdviceRefusesAReviewerThatLoadsTheBranchRules(t *testing.T) {
	for _, scope := range []string{"", "acme"} {
		t.Run("scope="+scope, func(t *testing.T) {
			home := sandbox(t)
			t.Setenv("PATH", t.TempDir())
			dir := filepath.Join(home, ".agentkit")
			configPath := filepath.Join(dir, "config.toml")
			text := testConfig + "\n[models.bolt]\nharness='grokbuild'\nmodel='bolt-3'\neffort='low'\nprovider='test'\n"
			write(t, configPath, text)
			path := filepath.Join(dir, "state", "session-acme.json")
			record := `{"orchestrator":"fable","workers":["fable"],"reviewers":["fable"]}`
			write(t, path, record)
			selected, err := ConfigSelection("acme")
			if err != nil {
				t.Fatal(err)
			}
			_, err = SaveAdvice(scope, selected, []config.EffortStep{{Model: "bolt", Key: "review_effort", Effort: "medium"}})
			configAfter, _ := os.ReadFile(configPath)
			seatAfter, _ := os.ReadFile(path)
			if err == nil || err.Error() != "no allowed executor/reviewer pair" || string(configAfter) != text || string(seatAfter) != record || selected.Dict("efforts") != nil {
				t.Fatalf("prohibited reviewer was admitted or changed state: %s, %s, %v", configAfter, seatAfter, err)
			}
		})
	}
}
