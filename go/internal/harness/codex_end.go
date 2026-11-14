package harness

import (
	"cmp"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// codexThreadEnd is `codex delete`, which takes a thread's rollout and what Codex indexed of it at
// once, run on the home that indexes it: ~/.codex, or an open seat's own, never one reached
// through a link.  Nothing indexes a closed seat's thread, so its rollout goes alone (codex.py
// `end_conversation`).
func codexThreadEnd(path string) End {
	return func(ends func(...string) bool, safe func(string) bool) error {
		thread := rolloutFile.FindStringSubmatch(filepath.Base(path))
		if thread == nil {
			return nil
		}
		folder := filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(path)))))
		seat, home := filepath.Join(config.UserHome(), ".codex", "agentkit-seats", filepath.Base(folder)), ""
		if seat == folder {
			home = filepath.Join(config.Home(), "state", "codex-remote-"+filepath.Base(folder))
		}
		if !ends() {
			return nil
		}
		if home == "" || safe(home) {
			return codexDelete(cmp.Or(home, folder), home, thread[1])
		}
		if held, _ := there(home); held {
			return nil
		}
		if err := os.Remove(path); err != nil {
			return err
		}
		codexClosedSeat(seat, home, safe)
		return nil
	}
}

// codexDelete is `codex delete --force` on that home whatever home and database ak's own
// environment selects, an open seat's database named too.
func codexDelete(home, database, thread string) error {
	env, err := config.ChildEnv()
	if err != nil {
		return err
	}
	env = slices.DeleteFunc(env, func(pair string) bool {
		key, _, _ := strings.Cut(pair, "=")
		return key == "CODEX_HOME" || key == "CODEX_SQLITE_HOME"
	})
	argv := []string{cmp.Or(Binary("codex"), "codex")}
	if database != "" {
		argv = append(argv, "-c", "sqlite_home="+run.Line(database))
	}
	return ending(append(argv, "delete", "--force", thread), append(env, "CODEX_HOME="+home))
}

// codexClosedSeat takes every empty folder of the seat whose home is gone, bottom up, so its own
// goes once it holds no rollout: nothing indexes or reads it any more.  Never one reached through
// a link, whose folders are somebody else's (codex.py `drop_closed_seat`).
func codexClosedSeat(seat, home string, safe func(string) bool) {
	if held, _ := there(home); held || !safe(seat) {
		return
	}
	var folders []string
	filepath.WalkDir(seat, func(path string, entry fs.DirEntry, err error) error {
		if err == nil && entry.IsDir() {
			folders = append(folders, path)
		}
		return nil
	})
	for _, folder := range slices.Backward(folders) {
		syscall.Rmdir(folder) // one still holding something stays
	}
}
