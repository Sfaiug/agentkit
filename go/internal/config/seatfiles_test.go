package config

import (
	"os"
	"regexp"
	"slices"
	"testing"
)

// While Python ak runs beside Go, its config.SEAT_FILES is where a seat's own files are named.
func TestSeatKindsArePythons(t *testing.T) {
	source, err := os.ReadFile("../../../agentkit/config.py")
	if err != nil {
		t.Fatal(err)
	}
	table := regexp.MustCompile(`(?s)\nSEAT_FILES = \{\n(.*?)\n\}\n`).FindSubmatch(source)
	if table == nil {
		t.Fatal("agentkit/config.py holds no SEAT_FILES table")
	}
	var kinds []string
	for _, key := range regexp.MustCompile(`(?m)^\s+"([^"]+)":`).FindAllSubmatch(table[1], -1) {
		kinds = append(kinds, string(key[1]))
	}
	if !slices.Equal(kinds, seatKinds) {
		t.Fatalf("Python's SEAT_FILES names %v, Go's seatKinds %v", kinds, seatKinds)
	}
}
