package localtime

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

// Python's local time is the host C library's: each rule is read by a Python of its own, as a
// program reads TZ once, at every hour of 2026 and of the months changing summer time in 1990,
// 2006 and 2040.
func TestEachRuleReadsAsThisHostsCLibraryReadsIt(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("no python3")
	}
	var instants []int64
	for at := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC); at.Year() == 2026; at = at.Add(time.Hour) {
		instants = append(instants, at.Unix())
	}
	for _, year := range []int{1990, 2006, 2040} {
		for _, month := range []time.Month{3, 4, 10, 11} {
			for at := time.Date(year, month, 1, 0, 0, 0, 0, time.UTC); at.Month() == month; at = at.Add(time.Hour) {
				instants = append(instants, at.Unix())
			}
		}
	}
	var asked bytes.Buffer
	for _, at := range instants {
		fmt.Fprintln(&asked, at)
	}
	for _, rule := range []string{"AKT5AKDT", "AKT3AKDT", "AKT-5AKDT", "CET-1CEST", "AKT5AKDT4", "AKT5AKDT,",
		"<+0530>-5:30<+0630>", "AKT-5", "CET-1CEST,M3.5.0,M10.5.0/3", "EST5EDT,M3.2.0/2,M11.1.0/2"} {
		python := exec.Command("python3", "-c", "import sys, time\nfor line in sys.stdin:\n"+
			"    t = time.localtime(int(line))\n    print(t.tm_gmtoff, t.tm_zone)\n")
		python.Env, python.Stdin = append(os.Environ(), "TZ="+rule), bytes.NewReader(asked.Bytes())
		said, err := python.Output()
		if err != nil {
			t.Fatalf("%q: %v", rule, err)
		}
		local, err := time.LoadLocationFromTZData(rule, zone(rule))
		if err != nil {
			t.Fatalf("%q: %v", rule, err)
		}
		wrong := 0
		for i, line := range strings.Split(strings.TrimSpace(string(said)), "\n") {
			name, offset := time.Unix(instants[i], 0).In(local).Zone()
			if got := fmt.Sprint(offset, " ", name); got != line && wrong < 3 {
				wrong++
				t.Errorf("TZ=%q at %s: Go %s, the C library %s", rule, time.Unix(instants[i], 0).UTC(), got, line)
			}
		}
	}
}
