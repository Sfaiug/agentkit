// Package parsed is a file parsed again only once its stat says it changed (Python's parsed): ak
// writes its files whole, so a file whose stat reads as it did when it was parsed still holds
// what was parsed from it, and a screen open all day reads only the files that moved.  A file
// changed within the second before it is read is parsed again next time: a filesystem's clock
// can give two writes in one tick the same times.  A directory is a file too, its listing its
// parse.  What comes back is every caller's: read it, never change it in place.
package parsed

import (
	"os"
	"sync"
	"time"
)

// fresh is since a file's last write in which its stat vouches for no parse (Python's
// parsed.FRESH).
const fresh = time.Second

// A Parse is what one way of parsing a file made of each file it read, kept with its stat.
type Parse[T any] struct {
	parse func(path string) (T, error)
	mu    sync.Mutex
	kept  map[string]kept[T]
}

type kept[T any] struct {
	info  os.FileInfo
	value T
}

// Of is that way of parsing a file, each file parsed again only once its stat changed.
func Of[T any](parse func(path string) (T, error)) *Parse[T] {
	return &Parse[T]{parse: parse, kept: map[string]kept[T]{}}
}

// Read is what the parse made of the file while its stat is unchanged, every caller's, so only
// read it; what stat or the parse returns where either fails, fs.ErrNotExist for no file.
func (p *Parse[T]) Read(path string) (T, error) {
	info, err := os.Stat(path)
	p.mu.Lock()
	was, ok := p.kept[path]
	if err != nil {
		delete(p.kept, path)
	}
	p.mu.Unlock()
	if err != nil {
		var none T
		return none, err
	}
	if ok && Same(was.info, info) {
		return was.value, nil
	}
	value, err := p.parse(path) // after the stat: a write meanwhile is read again, never missed
	if vouched := Vouching(info, time.Now()); err == nil && vouched != nil {
		p.mu.Lock()
		p.kept[path] = kept[T]{vouched, value}
		p.mu.Unlock()
	}
	return value, err
}

// Vouching is that stat where what was read under it holds while the stat does, else nil: by its
// last change, its ctime, which no `touch` sets back, or its mtime where that is later or the
// system keeps no ctime.
func Vouching(info os.FileInfo, now time.Time) os.FileInfo {
	if info == nil || now.Sub(info.ModTime()) < fresh || now.Sub(changed(info)) < fresh {
		return nil
	}
	return info
}

// Same is whether a file's stat reads as it did: the same file, written and changed last at the
// same times, the same size.
func Same(was, now os.FileInfo) bool {
	return os.SameFile(was, now) && was.ModTime().Equal(now.ModTime()) && changed(was).Equal(changed(now)) &&
		was.Size() == now.Size()
}
