package harness

import (
	"cmp"
	"errors"
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// grokEnd is `grok sessions delete`, which takes the session's folder and its
// session_search.sqlite row, run on the home that keeps it.  It reports a session it cannot read
// missing and exits 0, so a folder still there is a failure too (grokbuild.py `end_conversation`).
func grokEnd(folder string) End {
	return func(ends func(...string) bool, _ func(string) bool) error {
		if !ends() {
			return nil
		}
		env, err := config.ChildEnv()
		if err != nil {
			return err
		}
		argv := []string{cmp.Or(Binary("grok"), "grok"), "sessions", "delete", filepath.Base(folder)}
		if err := ending(argv, append(env, "GROK_HOME="+filepath.Dir(filepath.Dir(filepath.Dir(folder))))); err != nil {
			return err
		}
		if _, err := os.Stat(folder); err == nil {
			return errors.New("grok sessions delete left " + folder)
		}
		return nil
	}
}
