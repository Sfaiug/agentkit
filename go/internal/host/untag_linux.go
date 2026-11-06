package host

import (
	"bytes"
	"os"
	"strconv"
)

// untag blanks the seat's tag's value in this process's start environment, all /proc shows a
// leftover sweep's look of its environment, Python's owner._untag: in place, as Go's runtime
// copied each variable out of it at the start and nothing else reads those bytes.  Where /proc
// cannot say, the tag stays, and a sweep may take this process for the seat's.
func untag() {
	fields := statFields("/proc", os.Getpid())
	if len(fields) < 49 { // env_start and env_end, the stat's fields 50 and 51
		return
	}
	start, failed := strconv.ParseInt(fields[47], 10, 64)
	end, unread := strconv.ParseInt(fields[48], 10, 64)
	if failed != nil || unread != nil || end < start {
		return
	}
	mem, err := os.OpenFile("/proc/self/mem", os.O_RDWR, 0)
	if err != nil {
		return
	}
	defer mem.Close()
	env := make([]byte, end-start)
	if _, err := mem.ReadAt(env, start); err != nil {
		return
	}
	key, at := []byte("AK_TMUX_OWNER="), start
	for _, entry := range bytes.Split(env, []byte{0}) {
		if bytes.HasPrefix(entry, key) {
			mem.WriteAt(make([]byte, len(entry)-len(key)), at+int64(len(key)))
		}
		at += int64(len(entry)) + 1
	}
}
