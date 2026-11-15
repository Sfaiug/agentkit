//go:build linux

package gc

import (
	"cmp"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"

	"golang.org/x/sys/unix"

	"agentkit/internal/run"
)

// clearScratch removes a folder leftScratch named, its mark last, and puts the mark back where
// the folder itself cannot go, for the next collection to try again (gc.clear_scratch).  Each
// folder is opened through the one holding it, never through a link, and opened to its owner, as
// a command may have closed it: a name a link took meanwhile fails the removal.  Only the folder
// at hand stays open, so no depth meets a limit on open files: it climbs back through `..`, and
// one moved meanwhile, whose `..` is no longer the folder it came down from, fails the removal
// rather than lose that folder's names elsewhere.
func clearScratch(folder string) error {
	holder, err := reading(filepath.Dir(folder), true)
	if err != nil {
		return err
	}
	defer holder.Close()
	parent, name := int(holder.Fd()), filepath.Base(folder)
	fd, err := opened(parent, name)
	if err != nil {
		return err
	}
	defer func() { unix.Close(fd) }()
	names, err := listed(fd)
	if err != nil {
		return err
	}
	names = slices.DeleteFunc(names, func(name string) bool { return name == run.ScratchMark })
	type level struct {
		name  string
		names []string // what is left of the folder above
		from  unix.Stat_t
	}
	var above []level
	for len(names) > 0 || len(above) > 0 {
		if len(names) == 0 {
			up := above[len(above)-1]
			above, names = above[:len(above)-1], up.names
			outer, err := unix.Openat(fd, "..", unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
			if err != nil {
				return named("..", err)
			}
			unix.Close(fd)
			fd = outer
			var now unix.Stat_t
			if err := unix.Fstat(fd, &now); err != nil {
				return err
			}
			if now.Dev != up.from.Dev || now.Ino != up.from.Ino {
				return fmt.Errorf("%s moved while it was removed", up.name)
			}
			if err := unix.Unlinkat(fd, up.name, unix.AT_REMOVEDIR); err != nil {
				return named(up.name, err)
			}
			continue
		}
		child := names[len(names)-1]
		names = names[:len(names)-1]
		if err := unix.Unlinkat(fd, child, 0); err != unix.EISDIR {
			if err != nil {
				return named(child, err)
			}
			continue
		}
		down := level{name: child, names: names}
		if err := unix.Fstat(fd, &down.from); err != nil {
			return err
		}
		inner, err := opened(fd, child)
		if err != nil {
			return err
		}
		unix.Close(fd)
		fd = inner
		above = append(above, down)
		if names, err = listed(fd); err != nil {
			return err
		}
	}
	maker, err := readAt(fd, run.ScratchMark)
	if err != nil {
		return err
	}
	if err := unix.Unlinkat(fd, run.ScratchMark, 0); err != nil {
		return named(run.ScratchMark, err)
	}
	if err := unix.Unlinkat(parent, name, unix.AT_REMOVEDIR); err != nil {
		back, made := unix.Openat(fd, run.ScratchMark, unix.O_WRONLY|unix.O_CREAT|unix.O_EXCL|unix.O_CLOEXEC, 0o600)
		if made != nil {
			return named(run.ScratchMark, made)
		}
		mark := os.NewFile(uintptr(back), run.ScratchMark)
		_, wrote := mark.Write(maker)
		return cmp.Or(wrote, mark.Close(), named(name, err))
	}
	return nil
}

// opened is the folder `name` in the one open as dir, open to its owner: its mode is set through
// a handle that reads nothing (O_PATH), as one closed to reading opens no other (gc._opened).
func opened(dir int, name string) (int, error) {
	held, err := unix.Openat(dir, name, unix.O_PATH|unix.O_DIRECTORY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return -1, named(name, err)
	}
	defer unix.Close(held)
	if err := os.Chmod("/proc/self/fd/"+strconv.Itoa(held), 0o700); err != nil {
		return -1, err
	}
	fd, err := unix.Openat(held, ".", unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
	return fd, named(".", err)
}

// listed is the names in the folder open as fd, read through a copy of it.
func listed(fd int) ([]string, error) {
	copied, err := unix.FcntlInt(uintptr(fd), unix.F_DUPFD_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	folder := os.NewFile(uintptr(copied), ".")
	defer folder.Close()
	return folder.Readdirnames(-1)
}

// readAt is the bytes of the file `name` in the folder open as dir, a link to it unfollowed.
func readAt(dir int, name string) ([]byte, error) {
	fd, err := unix.Openat(dir, name, unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, named(name, err)
	}
	file := os.NewFile(uintptr(fd), name)
	defer file.Close()
	return io.ReadAll(file)
}

// named is a failed call on the name as Python's OSError names it; nil for none.
func named(name string, err error) error {
	if err == nil {
		return nil
	}
	return &os.PathError{Path: name, Err: err}
}
