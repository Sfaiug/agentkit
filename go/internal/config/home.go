package config

import (
	"cmp"
	"os"
	"os/user"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
)

// UserHome is ~ as Python's os.path.expanduser reads it: HOME, else the account's home, and
// the root where that is empty; "" where there is neither, where Python's Path.home() fails.
func UserHome() string {
	if runtime.GOOS == "windows" {
		home, _ := os.UserHomeDir() // USERPROFILE, as ntpath reads it
		return home
	}
	home, set := os.LookupEnv("HOME")
	if !set {
		account, err := user.LookupId(strconv.Itoa(os.Getuid()))
		if err != nil {
			return ""
		}
		home = account.HomeDir
	}
	return cmp.Or(home, "/")
}

// UnderHome is the path names make under ~, as Python's Path.home() joined with them: a `..` in
// HOME is the parent of the link before it, so such a HOME is resolved here, before this Join or
// a caller's cleans that `..` away.
func UnderHome(names ...string) string {
	home := UserHome()
	if slices.Contains(strings.Split(home, "/"), "..") {
		home = Resolve(home)
	}
	return filepath.Join(append([]string{home}, names...)...)
}
