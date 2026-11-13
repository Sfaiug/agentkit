package seat

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

// A save that fails leaves every legacy record as it was: one record that cannot be staged, config.toml
// that cannot land, or a record whose lock is held.
func TestAFailedSavePreservesEveryLegacyRecord(t *testing.T) {
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
			models, _ := config.Models()
			bound, _ := config.Bind()
			offered, _ := config.Offered()
			err = savingEfforts(bound.Models, models, offered, tryLocks, func(keep func() error) error {
				return config.RememberDefaults("astra", []string{"astra"}, []string{"astra"}, func() error {
					if err := keep(); err != nil || failure != "config rename" {
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
				})
			})
			after, _ := os.ReadFile(filepath.Join(dir, "config.toml"))
			if err == nil || string(after) != string(before) {
				t.Fatalf("failed save changed config: %s, %v", after, err)
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
