package config

import (
	"os"
	"os/user"
	"runtime"
	"strconv"
	"testing"
)

// ~ is HOME, the account's home where HOME is unset, and the root where it is empty.
func TestUserHomeIsPythonsExpanduser(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows reads USERPROFILE")
	}
	t.Setenv("HOME", "")
	if got := UserHome(); got != "/" {
		t.Errorf("empty HOME: %q", got)
	}
	os.Unsetenv("HOME")
	account, err := user.LookupId(strconv.Itoa(os.Getuid()))
	if err != nil {
		t.Skip("no account to read:", err)
	}
	if got := UserHome(); got != account.HomeDir {
		t.Errorf("HOME unset: %q, want %q", got, account.HomeDir)
	}
}
