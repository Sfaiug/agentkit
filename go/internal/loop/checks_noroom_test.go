//go:build linux

package loop

import (
	"errors"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

// A check the host has no room to start says nothing of the work: its error reaches the run's end,
// which leaves the run to the tick (noroom.go), where a failed check would start a fixer.
func TestACheckWithNoRoomToStartLeavesTheRunToTheTick(t *testing.T) {
	if !inChild(t) {
		return
	}
	l := rig(t, time.Minute)
	fillTable(t)
	if ok, text, err := l.checks([]string{"true"}, filepath.Join(l.roundDir(), "donewhen.log")); !errors.Is(err, syscall.EAGAIN) {
		t.Fatalf("no room to start a check read as its result: ok=%v err=%v\n%s", ok, err, text)
	}
}
