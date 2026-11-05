//go:build linux || darwin

package cli

import (
	"io"
	"os"
	"strconv"
	"syscall"
)

// cross is what to add to the environment for crossed to find data past an exec, as Python's
// warm.cross: a file no name reaches, on a descriptor the exec keeps.  Nothing for no data, nor
// where it cannot be made: what crosses only spares a wait.
func cross(variable string, data []byte) []string {
	if data == nil {
		return nil
	}
	file, err := os.CreateTemp("", "")
	if err != nil {
		return nil
	}
	defer file.Close()
	os.Remove(file.Name())
	kept := -1
	if _, err = file.Write(data); err == nil {
		if _, err = file.Seek(0, io.SeekStart); err == nil {
			kept, err = syscall.Dup(int(file.Fd())) // file's own closes on exec
		}
	}
	if err != nil {
		return nil
	}
	return []string{variable + "=" + strconv.Itoa(kept)}
}

// crossed is the bytes cross left under variable, else nil.  The variable and the descriptor go
// either way, so nothing this program starts meets them; a descriptor that is no file cross made
// is this program's for something else, and stays.
func crossed(variable string) []byte {
	fd, err := strconv.Atoi(os.Getenv(variable))
	os.Unsetenv(variable)
	var info syscall.Stat_t
	if err != nil || syscall.Fstat(fd, &info) != nil || info.Mode&syscall.S_IFMT != syscall.S_IFREG {
		return nil
	}
	file := os.NewFile(uintptr(fd), variable)
	defer file.Close()
	data, err := io.ReadAll(file)
	if err != nil {
		return nil
	}
	return data
}
