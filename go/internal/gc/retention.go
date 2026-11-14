package gc

import (
	"bytes"
	"compress/gzip"
	"errors"
	"io"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// What retention.py proves before anything is taken: whose a path is, what a record says, who
// holds it.

// stat is what a path is, as Python's os.lstat tells it.
type stat struct {
	dev, ino     uint64
	mode         uint32
	uid          uint32
	nlink        uint64
	size         int64
	mtime, ctime int64 // nanoseconds
}

func lstat(path string) (fs.FileInfo, stat, bool) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, stat{}, false
	}
	st, ok := statOf(info)
	return info, st, ok
}

// below is whether root is among the path's parents.
func below(path, root string) bool {
	return strings.HasPrefix(config.Pure(path), strings.TrimSuffix(config.Pure(root), "/")+"/")
}

func climbs(path string) bool {
	return slices.Contains(strings.Split(path, "/"), "..")
}

// present is existence without following a link (retention.present).
func present(path string) bool {
	_, err := os.Lstat(path)
	return err == nil
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func isFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

func isLink(path string) bool {
	info, err := os.Lstat(path)
	return err == nil && info.Mode()&fs.ModeSymlink != 0
}

// safe is no link on the way, and the path a folder or a file with one name, this user's
// (retention.safe).
func safe(path string) bool {
	return safeNamed(path, 1)
}

// safeNamed is safe for a file that may have up to `names` names (retention.safe's `names`).
func safeNamed(path string, names int) bool {
	path = config.Pure(path)
	if !strings.HasPrefix(path, "/") || climbs(path) {
		return false
	}
	for at := path; ; at = filepath.Dir(at) {
		if isLink(at) || !present(at) {
			return false
		}
		if filepath.Dir(at) == at {
			break
		}
	}
	info, st, ok := lstat(path)
	return ok && st.uid == uint32(os.Getuid()) && (info.IsDir() || info.Mode().IsRegular() && st.nlink <= uint64(names))
}

// listdir is a folder's names in order, its access time left alone where it can be
// (gc.tmp_listdir).
func listdir(path string) ([]string, error) {
	var names []string
	file, err := open(path, true)
	if err == nil {
		names, err = file.Readdirnames(-1)
		file.Close()
	} else {
		var entries []fs.DirEntry
		entries, err = os.ReadDir(path)
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
	}
	sort.Strings(names)
	return names, err
}

// children is a safe folder's entries in name order, none where it is not
// (retention.children).
func children(path string) []string {
	if !safe(path) {
		return nil
	}
	file, err := open(path, true)
	if err != nil {
		return nil
	}
	defer file.Close()
	names, err := file.Readdirnames(-1)
	if err != nil {
		return nil
	}
	sort.Strings(names)
	for i, name := range names {
		names[i] = filepath.Join(path, name)
	}
	return names
}

// readBytes is a safe file's bytes (retention.read_bytes).
func readBytes(path string) ([]byte, error) {
	if !safe(path) {
		return nil, errors.New("cannot read without changing metadata")
	}
	file, err := open(path, false)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return io.ReadAll(file)
}

// json is the object a safe file holds, as retention.read_json reads it; nil for none.  A
// record Go does not read as Python does makes the plan Python's: Python reads the bytes in
// UTF-16 or UTF-32 too, which a NUL byte marks where no BOM does, and lone surrogates, where Go
// reads UTF-8 alone.
func (r *reads) json(path string) *run.Object {
	data, err := readBytes(path)
	if err != nil {
		return nil
	}
	data = bytes.TrimPrefix(data, []byte("\xef\xbb\xbf"))
	value, err := run.DecodeLimited(data)
	if !utf8.Valid(data) || bytes.IndexByte(data, 0) >= 0 || errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		r.python = true
	}
	object, _ := value.(*run.Object)
	return object
}

// entry is one path of a tree and what it was when read.
type entry struct {
	path string
	stat
}

// tree is every path of a tree this user owns alone, links unfollowed, in Python's order; false
// where ownership is not established (retention.tree).  A socket is one only where `sockets`
// names the live ones, and none of them; permitted, where given, must pass each path.
func tree(path string, sockets []string, permitted func(string) bool) ([]entry, bool) {
	if permitted != nil && !permitted(path) || !safe(path) {
		return nil, false
	}
	info, st, ok := lstat(path)
	if !ok {
		return nil, false
	}
	found := []entry{{path, st}}
	if !info.IsDir() {
		return found, true
	}
	file, err := open(path, true)
	if err != nil {
		return nil, false
	}
	names, err := file.Readdirnames(-1)
	file.Close()
	if err != nil {
		return nil, false
	}
	sort.Strings(names)
	for _, name := range names {
		child := filepath.Join(path, name)
		if permitted != nil && !permitted(child) {
			return nil, false
		}
		info, st, ok := lstat(child)
		switch {
		case !ok:
			return nil, false
		case info.Mode()&fs.ModeSymlink != 0:
			if st.uid != uint32(os.Getuid()) {
				return nil, false
			}
			found = append(found, entry{child, st})
		case info.Mode()&fs.ModeSocket != 0:
			if sockets == nil || st.uid != uint32(os.Getuid()) || socketActive(child, sockets) {
				return nil, false
			}
			found = append(found, entry{child, st})
		default:
			sub, ok := tree(child, sockets, permitted)
			if !ok {
				return nil, false
			}
			found = append(found, sub...)
		}
	}
	return found, true
}

// unixSockets is every filesystem socket the kernel still holds, nil where that is unknown.
func unixSockets() []string {
	data, err := os.ReadFile("/proc/net/unix")
	lines := strings.Split(string(data), "\n")
	if err != nil || !strings.HasPrefix(lines[0], "Num") {
		return nil
	}
	sockets := []string{}
	for _, line := range lines[1:] {
		if found := socketPath.FindStringSubmatch(line); found != nil && !strings.HasPrefix(found[1], "@") {
			sockets = append(sockets, found[1])
		}
	}
	return sockets
}

// socketPath is a /proc/net/unix line's eighth field and all after it: its path.
var socketPath = regexp.MustCompile(`^\s*(?:\S+\s+){7}(\S.*)$`)

// socketActive: a relative bind name has no recorded folder, so any of the same name counts.
func socketActive(path string, sockets []string) bool {
	return slices.ContainsFunc(sockets, func(name string) bool {
		return name == path || !strings.HasPrefix(name, "/") && filepath.Base(name) == filepath.Base(path)
	})
}

// busy is whether a process holds that path or anything under it; unknown holders hold all.
func busy(path string, paths []string) bool {
	return paths == nil || slices.ContainsFunc(paths, func(held string) bool {
		return held == path || strings.HasPrefix(held, path+"/")
	})
}

// expired is a time, a record's or a file's, at least `age` before now (retention.expired).
func expired(value any, now, age float64) bool {
	at, ok := value.(float64)
	if !ok {
		at, ok = run.Num(value)
	}
	return ok && !math.IsInf(at, 0) && !math.IsNaN(at) && 0 < at && at <= now-age
}

// processPaths is every path a process of this user names: its working directory, what it
// holds open and each absolute word of its command line; nil where /proc cannot be listed
// (retention.process_paths).
func processPaths() []string {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil
	}
	paths := []string{}
	for _, entry := range entries {
		if _, err := strconv.Atoi(entry.Name()); err != nil {
			continue
		}
		proc := "/proc/" + entry.Name()
		info, err := os.Stat(proc)
		if err != nil {
			continue // it exited
		}
		if st, ok := statOf(info); !ok || st.uid != uint32(os.Getuid()) {
			continue
		}
		links := []string{proc + "/cwd"}
		if fds, err := os.ReadDir(proc + "/fd"); err == nil {
			for _, fd := range fds {
				links = append(links, proc+"/fd/"+fd.Name())
			}
		}
		for _, link := range links {
			if target, err := os.Readlink(link); err == nil {
				if target = strings.TrimSuffix(target, " (deleted)"); strings.HasPrefix(target, "/") {
					paths = append(paths, target)
				}
			}
		}
		if command, err := os.ReadFile(proc + "/cmdline"); err == nil {
			for _, arg := range strings.Split(string(command), "\x00") {
				if strings.HasPrefix(arg, "/") {
					paths = append(paths, arg)
				}
			}
		}
	}
	return paths
}

// writerActive is whether a record's writer may still run: a malformed identity is no proof it
// exited (retention.writer_active).
func writerActive(record *run.Object) bool {
	return run.WriterActive(record)
}

// provablyFinal is a run ended and its loop gone (worktrees.provably_final).
func provablyFinal(record *run.Object) bool {
	return record != nil && run.Ended(record) && pidGone(record)
}

func pidGone(record *run.Object) bool {
	if pid, ok := record.Int("pid"); ok && pid == os.Getpid() {
		return true
	}
	return !writerActive(record)
}

// marker is where an artifact's receipt is kept (retention.marker).
func marker(path string) string {
	if isDir(path) {
		return filepath.Join(path, ".agentkit-ephemeral.json")
	}
	return path + ".agentkit-ephemeral.json"
}

// sameArchive is whether a log's .gz holds exactly the log (retention.same_archive).
func sameArchive(path string) bool {
	plain, err := readBytes(path)
	if err != nil {
		return false
	}
	packed, err := readBytes(path + ".gz")
	if err != nil {
		return false
	}
	reader, err := gzip.NewReader(bytes.NewReader(packed))
	if err != nil {
		return false
	}
	unpacked, err := io.ReadAll(reader)
	return err == nil && bytes.Equal(plain, unpacked)
}
