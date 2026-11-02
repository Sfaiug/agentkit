package config

import (
	"maps"
	"os"
	"regexp"
	"testing"
)

// While Python ak runs beside Go, its config.SEAT_FILES is where a seat's own files are named.
func TestSeatFilesArePythons(t *testing.T) {
	source, err := os.ReadFile("../../../agentkit/config.py")
	if err != nil {
		t.Fatal(err)
	}
	table := regexp.MustCompile(`(?s)\nSEAT_FILES = \{\n(.*?)\n\}\n`).FindSubmatch(source)
	if table == nil {
		t.Fatal("agentkit/config.py holds no SEAT_FILES table")
	}
	kinds := map[string]string{}
	for _, key := range regexp.MustCompile(`(?m)^\s+"([^"]+)":\s*"([^"]+)"`).FindAllSubmatch(table[1], -1) {
		kinds[string(key[1])] = string(key[2])
	}
	if !maps.Equal(kinds, seatFiles) {
		t.Fatalf("Python's SEAT_FILES names %v, Go's seatFiles %v", kinds, seatFiles)
	}
}
