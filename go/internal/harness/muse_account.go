package harness

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// An account other than the usual login keeps its auth.json in a config home of its own,
// ~/.muse-<name>, where `XDG_CONFIG_HOME=~/.muse-<name> muse login` puts it: Muse reads its login
// from $XDG_CONFIG_HOME/muse and has no other switch for where (muse.sh).  Its sessions stay under
// XDG_DATA_HOME, so a conversation begun on one login resumes on the next.  A seat on an account
// hands its config home to everything it starts, so a call naming no account drops one.

// museConfig is the config home of that account's login, the usual one's for "".
func museConfig(account string) string {
	home, _ := os.UserHomeDir()
	if account != "" {
		return filepath.Join(home, ".muse-"+account)
	}
	if usual := os.Getenv("XDG_CONFIG_HOME"); usual != "" && !strings.HasPrefix(usual, home+"/.muse-") {
		return usual
	}
	return filepath.Join(home, ".config")
}

// museAuth is muse.sh `auth`: a login is its auth.json holding anything, as Muse records a key
// and no expiry; another provider needs none, and a META_API_KEY set is the usual login's own.
func museAuth(_ config.Login, _ bool) Answer {
	account := os.Getenv("AGENTKIT_ACCOUNT")
	if provider := os.Getenv("AGENTKIT_MUSE_PROVIDER"); provider != "" && provider != "meta" {
		return Answer{Yes: true, Line: "muse: the " + provider + " provider needs no login"}
	}
	if account == "" && os.Getenv("META_API_KEY") != "" {
		return Answer{Yes: true, Line: "muse: META_API_KEY is set"}
	}
	auth := filepath.Join(museConfig(account), "muse", "auth.json")
	if data, _ := os.ReadFile(auth); blank(string(data)) {
		login := "muse login"
		if account != "" {
			login = "XDG_CONFIG_HOME=" + museConfig(account) + " " + login
		}
		return Answer{Line: "muse: no " + auth + "; run `" + login + "`"}
	}
	return Answer{Yes: true, Line: "muse: the login in " + auth + " is saved"}
}

// museHome readies an account's config home, as muse.sh `home` does: Muse writes its
// settings.json through a link and keeps it, so this login's settings go into the usual login's
// once, the usual login's winning even within an object, and its own becomes a link to them, all
// under Muse's own lock; and every other program's config of the usual home is linked in, so gh or
// git read on.
func museHome(account string) error {
	own, usual := museConfig(account), museConfig("")
	for _, dir := range []string{filepath.Join(own, "muse"), filepath.Join(usual, "muse")} {
		if err := os.MkdirAll(dir, 0o777); err != nil {
			return err
		}
	}
	shared := filepath.Join(usual, "muse", ".settings.json.lock")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	held, err := lock.Wait(ctx, shared)
	if err != nil {
		return err
	}
	settings, theirs := filepath.Join(own, "muse", "settings.json"), filepath.Join(usual, "muse", "settings.json")
	link, _ := os.Lstat(settings)
	if link == nil || link.Mode()&fs.ModeSymlink == 0 || !sameFile(settings, theirs) {
		if err = museMergeSettings(settings, theirs); err == nil {
			err = relink(theirs, settings)
		}
	}
	if err == nil {
		err = relink(shared, filepath.Join(own, "muse", ".settings.json.lock"))
	}
	held.Close()
	if err != nil {
		return err
	}
	entries, _ := os.ReadDir(usual)
	for _, entry := range entries {
		name := entry.Name()
		if name == "muse" || strings.HasPrefix(name, "..") || !exists(filepath.Join(usual, name)) {
			continue
		}
		if _, err := os.Lstat(filepath.Join(own, name)); errors.Is(err, fs.ErrNotExist) {
			os.Symlink(filepath.Join(usual, name), filepath.Join(own, name))
		}
	}
	return nil
}

// museMergeSettings writes into the usual login's settings this login's merged under them, over
// `{"schema_version": 1}`, unless they already hold that.
func museMergeSettings(settings, usual string) error {
	merged := run.Fields("schema_version", run.Number("1"))
	for _, path := range []string{settings, usual} {
		data, err := os.ReadFile(path)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		read, _ := run.Decode(data)
		values, ok := read.(*run.Object)
		if err != nil || !ok {
			return errors.New("muse: " + path + " holds no settings object")
		}
		merged = museMerged(merged, values)
	}
	data, _ := os.ReadFile(usual)
	read, _ := run.Decode(data)
	if read != nil && run.Equal(read, merged) {
		return nil
	}
	return os.WriteFile(usual, []byte(run.EncodeText(merged)+"\n"), 0o666)
}

// museMerged is jq's `a * b`: b's values over a's, objects merged all the way down.
func museMerged(a, b *run.Object) *run.Object {
	merged := a.Copy()
	for _, key := range b.Keys() {
		inner, under := merged.Get(key).(*run.Object)
		over, isObject := b.Get(key).(*run.Object)
		if under && isObject {
			merged.Set(key, museMerged(inner, over))
		} else {
			merged.Set(key, b.Get(key))
		}
	}
	return merged
}

// relink is `ln -sfn target link`.
func relink(target, link string) error {
	if err := os.Remove(link); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	return os.Symlink(target, link)
}

// sameFile is `[ a -ef b ]`: both there, through links, and one file.
func sameFile(a, b string) bool {
	first, err := os.Stat(a)
	second, other := os.Stat(b)
	return err == nil && other == nil && os.SameFile(first, second)
}
