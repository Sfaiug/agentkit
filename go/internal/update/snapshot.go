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
	dir            string                 // the program's folder
	files          []saved                // in the order they go back: the launch links last, outward
	parents        map[string]os.FileInfo // each folder a saved path is in, as it was
}

// A saved is one path of a snapshot: a link's target, or a file's mode, its bytes' digest and
// its copy's name in the snapshot's folder.
type saved struct {
	Path string `json:"path"`
	Link string `json:"link,omitempty"`
	Sum  string `json:"sha256,omitempty"`
	Copy string `json:"saved,omitempty"`
	Mode mode   `json:"mode"`
}

// A mode is a file's permission bits with its setuid, setgid and sticky ones, which the manifest
// shows as `ls` does.
type mode os.FileMode

func (m mode) MarshalText() ([]byte, error) { return []byte(os.FileMode(m).String()), nil }

// layout is where a harness's install is: the folder of the program its version command runs,
// and each path a snapshot of it takes, the files its recipe names there and those their links
// lead to there, then the program and the links that lead to it from PATH.  An error where Go
// cannot take one as Python does, or where the installer may be writing it.
func layout(each plan) (string, []string, error) {
	entry := harness.Binary(each.version[0])
	if entry == "" {
		return "", nil, fmt.Errorf("%s is not installed here", each.name)
	}
	entry, _ = filepath.Abs(entry)
	chain, err := follow(entry)
	if err != nil {
		return "", nil, err
	}
	dir := filepath.Dir(chain[len(chain)-1])
	if each.snapshot.lock != "" {
		if _, err := os.Lstat(filepath.Join(dir, each.snapshot.lock)); err == nil {
			return "", nil, fmt.Errorf("%s's installer holds %s", each.name, filepath.Join(dir, each.snapshot.lock))
		}
	}
	named, err := matching(dir, each.snapshot.files)
	if err != nil {
		return "", nil, err
	}
	var files []string
	for _, file := range named {
		links, err := follow(file)
		if err != nil {
			return "", nil, err
		}
		for _, path := range links {
			if filepath.Dir(path) != dir {
				return "", nil, fmt.Errorf("%s leads out of %s", file, dir)
			}
			if !slices.Contains(files, path) && !slices.Contains(chain, path) {
				files = append(files, path)
			}
		}
	}
	slices.Reverse(chain)
	return dir, append(files, chain...), nil
}

// follow is path and each path its links lead through to the file at their end, as Python's
// launch_paths: none in a linked folder, none twice.
func follow(path string) ([]string, error) {
	var chain []string
	for {
		if dir := filepath.Dir(path); config.Resolve(dir) != dir || slices.Contains(chain, path) {
			return nil, fmt.Errorf("%s is reached through a linked folder or a loop", path)
		}
		info, err := os.Lstat(path)
		if err != nil {
			return nil, err
		}
		chain = append(chain, path)
		if info.Mode().IsRegular() {
			return chain, nil
		}
		if info.Mode()&os.ModeSymlink == 0 {
			return nil, fmt.Errorf("a snapshot takes a file or a link, not %s", path)
		}
		target, err := os.Readlink(path)
		if err != nil {
			return nil, err
		}
		path = under(filepath.Dir(path), target)
	}
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
	s = &snapshot{plan: each, identity: identity, env: env, parents: map[string]os.FileInfo{}}
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
		parent, err := os.Lstat(filepath.Dir(path))
		if err != nil {
			return s, err
		}
		info, err := os.Lstat(path)
		if err != nil {
			return s, err
		}
		s.parents[filepath.Dir(path)] = parent
		file := saved{Path: path, Mode: mode(info.Mode() & (os.ModePerm | os.ModeSetuid | os.ModeSetgid | os.ModeSticky))}
		if info.Mode().IsRegular() {
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

// restore puts the install back as the snapshot saved it, as that plugin snapshot's `restore`,
// and lets the snapshot go.  Only into the folders it was taken from, and only once every saved
// path is staged beside where it goes, its bytes checked: then each goes in by a rename, over
// whatever is there, the launch links after the program they lead to, and what the recipe names
// that the snapshot did not save goes.  An error where any of that fails, or the build back is
// not the one saved, keeps the snapshot.
func (s *snapshot) restore() error {
	for parent, was := range s.parents {
		if now, err := os.Lstat(parent); err != nil || !os.SameFile(was, now) || config.Resolve(parent) != parent {
			return fmt.Errorf("%s is not the folder the snapshot was taken from; nothing was put back", parent)
		}
	}
	var staged []string
	defer func() {
		for _, name := range staged {
			os.Remove(name) // gone already once renamed in
		}
	}()
	for _, file := range s.files {
		name, err := file.stage(s.path)
		staged = append(staged, name)
		if err != nil {
			return err
		}
	}
	for i, file := range s.files {
		// a folder the upgrade left where a saved path goes, which no rename replaces
		if info, err := os.Lstat(file.Path); err == nil && info.IsDir() {
			if err := os.RemoveAll(file.Path); err != nil {
				return err
			}
		}
		if err := os.Rename(staged[i], file.Path); err != nil {
			return err
		}
	}
	added, err := matching(s.dir, s.plan.snapshot.files)
	for _, path := range added {
		if !slices.ContainsFunc(s.files, func(file saved) bool { return file.Path == path }) {
			err = errors.Join(err, os.RemoveAll(path))
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

// stage writes what file saved beside where it goes, under a temporary name it returns: the link,
// or a copy of its bytes, checked against their digest, with its mode.
func (file saved) stage(snapshot string) (string, error) {
	temporary, err := os.CreateTemp(filepath.Dir(file.Path), ".ak-restore-")
	if err != nil {
		return "", err
	}
	name := temporary.Name()
	temporary.Close()
	if file.Link != "" {
		os.Remove(name)
		return name, os.Symlink(file.Link, name)
	}
	sum, err := copied(filepath.Join(snapshot, file.Copy), name)
	if err == nil && sum != file.Sum {
		err = fmt.Errorf("the saved copy of %s changed", file.Path)
	}
	return name, errors.Join(err, os.Chmod(name, os.FileMode(file.Mode)))
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
