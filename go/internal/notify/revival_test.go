package notify

import (
	"io"
	"os"
	"testing"
)

func TestAWorkerRevivalAsksNothing(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AK_RUN_ROLE", "worker")
	t.Setenv("AK_RUN_LOG", "")
	if carried, err := Needs("acme", "could not reopen", "revive:acme:turn:1", true, func(string) (string, any) {
		t.Fatal("a worker read a card")
		return "", nil
	}, io.Discard); !carried || err != nil {
		t.Fatal(carried, err)
	}
	if _, err := os.Stat(state()); !os.IsNotExist(err) {
		t.Fatal("a worker wrote a notice")
	}
}
