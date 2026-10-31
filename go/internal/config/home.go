package config

import (
	"cmp"
	"os"
	"os/user"
	"runtime"
	"strconv"
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
