//go:build linux

package gc

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
	"unicode/utf16"
)

// reportHome is a home whose state holds one report of a conversation no seat names yet.
func reportHome(t *testing.T) (state, report string) {
	t.Setenv("HOME", t.TempDir())
	state = filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	report = filepath.Join(state, "model-conv-held.json")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(report, []byte(`{"model": "acme-model"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	return state, report
}

// A seat launched on the conversation after the plan keeps its report, its record read as
// Python reads it or not.
func TestASeatRecordedSinceThePlanKeepsItsReport(t *testing.T) {
	plain := `{"orchestrator": "gemini", "conversation": "conv-held"`
	wide := []byte{0xff, 0xfe}
	for _, unit := range utf16.Encode([]rune(plain + "}")) {
		wide = binary.LittleEndian.AppendUint16(wide, unit)
	}
	for name, record := range map[string][]byte{
		"utf-8":          []byte(plain + "}"),
		"utf-16":         wide,
		"lone surrogate": []byte(plain + `, "title": "\ud800"}`),
	} {
		t.Run(name, func(t *testing.T) {
			state, report := reportHome(t)
			plan := (&reads{}).modelReports()
			if len(plan) != 1 {
				t.Fatalf("planned %v", plan)
			}
			if err := os.WriteFile(filepath.Join(state, "session-acme.json"), record, 0o600); err != nil {
				t.Fatal(err)
			}
			if newCollection(func(string) {}).take(plan[0]) || !present(report) {
				t.Fatal("the report went")
			}
		})
	}
}

// Weighing a report against the seats leaves the state folder's access time as it was.
func TestWeighingAReportKeepsTheStateFoldersAccessTime(t *testing.T) {
	state, _ := reportHome(t)
	if err := os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(`{"conversation": "conv-held"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(state, time.Unix(1, 0), time.Unix(1, 0)); err != nil {
		t.Fatal(err)
	}
	if plan := (&reads{}).modelReports(); len(plan) != 0 {
		t.Fatalf("planned %v", plan)
	}
	info, _ := os.Stat(state)
	if at := info.Sys().(*syscall.Stat_t).Atim; at.Sec != 1 {
		t.Fatalf("the state folder was read at %v", at)
	}
}
