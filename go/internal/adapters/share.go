package adapters

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/task"
)

// share makes a named login read the usual one's conversations and settings, as the Python
// adapters' `share` does on each launch there: a change made in any session on any login is
// every session's, and a conversation begun on one login is resumed on the next.  Its login
// stays its own.  Paths are joined as spelled, as the adapters' shell joins them.
func share(login config.Login) error {
	kept := under(login.Usual, login.Conversations)
	if err := os.MkdirAll(kept, 0o777); err != nil {
		return err
	}
	if err := os.MkdirAll(login.Home, 0o777); err != nil {
		return err
	}
	own := under(login.Home, login.Conversations)
	if _, err := os.Stat(own); err != nil {
		if err := os.Symlink(kept, own); err != nil {
			return err
		}
	}
	// first launches on several logins at once take turns, as Python's share_settings does
	held, err := lock.Wait(context.Background(), login.Usual)
	if err != nil {
		return err
	}
	defer held.Close()
	for _, name := range login.Settings {
		if err := link(under(login.Usual, name), under(login.Home, name), login.Carry); err != nil {
			return err
		}
	}
	return nil
}

// link makes own a link to the usual login's file, unless own already leads to that file,
// through whatever links, there yet or not; a copy or a hard link would stop sharing at the
// usual file's next save.  Where carry is set, what own holds that the usual file lacks is
// carried into it first; elsewhere what only own held goes, since carrying it would rewrite a
// file another session may be saving.  The link is made under a name no other launch shares
// and moved into own's place at once.
func link(usual, own string, carry bool) error {
	if config.Resolve(own) == config.Resolve(usual) {
		return nil
	}
	if carry {
		if err := carryOver(usual, own); err != nil {
			return err
		}
	}
	dir, base := filepath.Split(own)
	temporary, err := os.CreateTemp(dir, base+".*")
	if err != nil {
		return err
	}
	temporary.Close()
	os.Remove(temporary.Name())
	if err := os.Symlink(usual, temporary.Name()); err != nil {
		return err
	}
	if err := os.Rename(temporary.Name(), own); err != nil {
		os.Remove(temporary.Name())
		return err
	}
	return nil
}

// carryOver puts what own's TOML holds that the usual file lacks into the file the usual one
// leads to, own's text as written where there is none, and leaves a file lacking nothing as it
// is.  Either one not TOML is an error, and both are kept.
func carryOver(usual, own string) error {
	theirs, err := os.ReadFile(own)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	} else if err != nil {
		return err
	}
	target := config.Resolve(usual)
	text := task.Text(theirs)
	if mine, err := os.ReadFile(target); err == nil {
		carried, changed, err := config.Carry(task.Text(mine), text)
		if err != nil || !changed {
			return err
		}
		text = carried
	} else if !errors.Is(err, fs.ErrNotExist) {
		return err
	} else if err := config.TOML(text); err != nil {
		return err
	}
	return replace(target, text)
}

// under is name in dir, joined as a shell joins "$dir/name".
func under(dir, name string) string {
	return dir + string(filepath.Separator) + name
}
