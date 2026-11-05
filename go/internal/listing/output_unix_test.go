//go:build linux || darwin

package listing

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"syscall"
	"testing"
	"time"
)

func TestAnExitedAdaptersHelperKeepsItsOfferedEfforts(t *testing.T) {
	adapter(t, `printf 'acme-1\tAcme One\tlow\n'
(sleep 2; : > "$HOME/helper-finished") &
exit 0`, "[catalog]\nacme-1={label='Acme One',efforts=['low','medium','high']}\n")
	finished := filepath.Join(os.Getenv("HOME"), "helper-finished")
	t.Cleanup(func() { awaitCatalogFile(t, finished) })
	choices, err := Choices("acme")
	want := []Choice{{"acme-1", "Acme One", []string{"low"}}}
	if err != nil || !reflect.DeepEqual(choices, want) {
		t.Fatalf("discarded the adapter's own efforts: %+v, %v", choices, err)
	}
	if _, err := os.Stat(finished); err != nil {
		t.Fatalf("returned before the helper finished: %v", err)
	}
}

func TestCancelStopsAListingWithInheritedOutput(t *testing.T) {
	adapter(t, `printf 'acme-1\tAcme One\tlow\n'
(: > "$HOME/helper-started"; read token < "$HOME/release"; : > "$HOME/helper-finished") &
exit 0`, table)
	release, finished := filepath.Join(os.Getenv("HOME"), "release"), filepath.Join(os.Getenv("HOME"), "helper-finished")
	if err := syscall.Mkfifo(release, 0o600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ended := make(chan struct{})
	var err error
	go func() { defer close(ended); _, err = ChoicesContext(ctx, "acme") }()
	t.Cleanup(func() { cancel(); releaseCatalogHelper(t, release, finished); <-ended })
	awaitCatalogFile(t, filepath.Join(os.Getenv("HOME"), "helper-started"))
	cancel()
	select {
	case <-ended:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("canceled listing: %v", err)
		}
		if releaseCatalogHelper(t, release, finished) {
			t.Fatal("cancellation left the inherited-output helper running")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("canceled listing kept waiting for its helper's output")
	}
}

func releaseCatalogHelper(t *testing.T, fifo, finished string) bool {
	t.Helper()
	fd, err := syscall.Open(fifo, syscall.O_WRONLY|syscall.O_NONBLOCK, 0)
	if err == syscall.ENXIO {
		return false
	}
	if err != nil {
		t.Fatal(err)
	}
	syscall.Write(fd, []byte("go\n"))
	syscall.Close(fd)
	awaitCatalogFile(t, finished)
	return true
}

func awaitCatalogFile(t *testing.T, path string) {
	t.Helper()
	deadline := time.NewTimer(10 * time.Second)
	defer deadline.Stop()
	tick := time.NewTicker(10 * time.Millisecond)
	defer tick.Stop()
	for {
		if _, err := os.Stat(path); err == nil {
			return
		}
		select {
		case <-deadline.C:
			t.Fatalf("adapter helper never wrote %s", path)
		case <-tick.C:
		}
	}
}
