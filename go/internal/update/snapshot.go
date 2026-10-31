package update

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// A recipe is what a harness's manifest's `[snapshot]` says Go saves of it before an upgrade
// where nothing else puts it back: beside the links leading to the program its version command
// runs, and that program, the files there, each a name or a glob; and the lock its own
// installer holds while it writes them.
type recipe struct {
	files []string
	lock  string
}

// snapshotted is a harness's `[snapshot]`, nil where its manifest has none.
func snapshotted(name string) *recipe {
	facts, _ := config.Section(name, "snapshot")
	if facts == nil {
		return nil
	}
	files, _ := config.Words(name, "snapshot", "files")
	lock, _ := facts["lock"].(string)
	return &recipe{files, lock}
}

// A snapshot is a harness's install as it was before an upgrade, kept to put back byte for byte,
// modes included, as the snapshot of Python's harness plugin keeps one.
type snapshot struct {
	plan           plan
	identity, path string // the build saved, and the folder its copies are in
	env            []string
	dir            string  // the program's folder
	files          []saved // in the order they go back: the launch links last, outward
}

// A saved is one path of a snapshot: a link's target, or a file's mode, its bytes' digest and
// its copy's name in the snapshot's folder.
type saved struct {
	Path string      `json:"path"`
	Link string      `json:"link,omitempty"`
	Sum  string      `json:"sha256,omitempty"`
	Copy string      `json:"saved,omitempty"`
	Mode os.FileMode `json:"mode"`
}

// layout is where a harness's install is: the folder of the program its version command runs,
// and each path a snapshot of it takes, the files its recipe names there, then the program and
// the links that lead to it from PATH.  An error where Go cannot take one as Python does, or
// where the installer may be writing it.
func layout(each plan) (string, []string, error) {
	path := harness.Binary(each.version[0])
	if path == "" {
		return "", nil, fmt.Errorf("%s is not installed here", each.name)
	}
	path, _ = filepath.Abs(path)
	var chain []string
	for {
		if dir := filepath.Dir(path); config.Resolve(dir) != dir || slices.Contains(chain, path) {
			return "", nil, fmt.Errorf("%s is reached through a linked folder or a loop: %s", each.name, path)
		}
		info, err := os.Lstat(path)
		if err != nil {
			return "", nil, err
		}
		chain = append(chain, path)
		if info.Mode().IsRegular() {
			break
		}
		target, err := os.Readlink(path)
		if err != nil {
			return "", nil, err
		}
		path = under(filepath.Dir(path), target)
	}
	dir := filepath.Dir(path)
	if each.snapshot.lock != "" {
		if _, err := os.Lstat(filepath.Join(dir, each.snapshot.lock)); err == nil {
			return "", nil, fmt.Errorf("%s's installer holds %s", each.name, filepath.Join(dir, each.snapshot.lock))
		}
	}
	files, err := matching(dir, each.snapshot.files)
	if err != nil {
		return "", nil, err
	}
	files = slices.DeleteFunc(files, func(file string) bool { return slices.Contains(chain, file) })
	for _, file := range files {
		info, err := os.Lstat(file)
		if err != nil {
			return "", nil, err
		}
		if !info.Mode().IsRegular() && info.Mode()&os.ModeSymlink == 0 {
			return "", nil, fmt.Errorf("a snapshot takes a file or a link, not %s", file)
		}
	}
	slices.Reverse(chain)
	return dir, append(files, chain...), nil
}

// matching is each path in dir whose name one of patterns matches, in name order.
func matching(dir string, patterns []string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	var found []string
	for _, entry := range entries {
		if slices.ContainsFunc(patterns, func(pattern string) bool {
			matched, _ := filepath.Match(pattern, entry.Name())
			return matched
		}) {
			found = append(found, filepath.Join(dir, entry.Name()))
		}
	}
	return found, err
}

// take saves harness each's install, identity the build installed now, before an upgrade moves
// it: into a folder of its own under ak's tmp, with a manifest of what each copy is, for
// whoever puts one back by hand.
func take(each plan, identity string, env []string) (s *snapshot, err error) {
	s = &snapshot{plan: each, identity: identity, env: env}
	defer func() {
		if err != nil {
			if s.path != "" {
				os.RemoveAll(s.path)
			}
			s, err = nil, fmt.Errorf("cannot assure a complete %s snapshot and safe restore: %s", each.name, pyError(err))
		}
	}()
	var paths []string
	if s.dir, paths, err = layout(each); err != nil {
		return
	}
	if s.path, err = os.MkdirTemp(filepath.Join(config.Home(), "tmp"), each.name+"-snapshot-"); err != nil {
		return
	}
	for i, path := range paths {
		file := saved{Path: path}
		info, err := os.Lstat(path)
		if err != nil {
			return s, err
		}
		if file.Mode = info.Mode().Perm(); info.Mode().IsRegular() {
			file.Copy = strconv.Itoa(i)
			file.Sum, err = copied(path, filepath.Join(s.path, file.Copy))
		} else {
			file.Link, err = os.Readlink(path)
		}
		if err != nil {
			return s, err
		}
		s.files = append(s.files, file)
	}
	data, _ := json.MarshalIndent(map[string]any{"identity": identity, "files": s.files}, "", "  ")
	return s, os.WriteFile(filepath.Join(s.path, "manifest.json"), data, 0o600)
}

// restore puts the install back as the snapshot saved it, as that plugin snapshot's `restore`:
// each path by a rename of a whole copy whose bytes are checked, the launch links after the
// program they lead to, then what the recipe names that the snapshot did not save gone.  An
// error where any of that fails, or the build back is not the one saved, keeps the snapshot.
func (s *snapshot) restore() error {
	for _, file := range s.files {
		temporary, err := os.CreateTemp(filepath.Dir(file.Path), ".ak-restore-")
		if err != nil {
			return err
		}
		name := temporary.Name()
		temporary.Close()
		defer os.Remove(name) // gone once renamed in
		if file.Link != "" {
			os.Remove(name)
			err = os.Symlink(file.Link, name)
		} else {
			var sum string
			if sum, err = copied(filepath.Join(s.path, file.Copy), name); err == nil && sum != file.Sum {
				err = fmt.Errorf("the saved copy of %s changed", file.Path)
			}
			err = errors.Join(err, os.Chmod(name, file.Mode))
		}
		if err = errors.Join(err, os.Rename(name, file.Path)); err != nil {
			return err
		}
	}
	added, err := matching(s.dir, s.plan.snapshot.files)
	for _, path := range added {
		if !slices.ContainsFunc(s.files, func(file saved) bool { return file.Path == path }) {
			err = errors.Join(err, os.Remove(path))
		}
	}
	if err != nil {
		return err
	}
	if back, _ := version(s.plan, s.env); back != s.identity {
		return fmt.Errorf("restored %s failed its pinned version check", s.plan.name)
	}
	s.discard()
	return nil
}

// discard lets the snapshot go: once restored, or no longer needed.
func (s *snapshot) discard() {
	os.RemoveAll(s.path)
}

// copied copies the file at from to the one at to, synced, and is the digest of its bytes.
func copied(from, to string) (string, error) {
	source, err := os.Open(from)
	if err != nil {
		return "", err
	}
	defer source.Close()
	target, err := os.OpenFile(to, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return "", err
	}
	digest := sha256.New()
	_, err = io.Copy(io.MultiWriter(target, digest), source)
	return hex.EncodeToString(digest.Sum(nil)), errors.Join(err, target.Sync(), target.Close())
}
