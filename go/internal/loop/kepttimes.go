package loop

import (
	"bufio"
	"os"
	"regexp"
	"strconv"

	"agentkit/internal/suitetimes"
)

// passedLine is the line a piece prints for a test that passed in its seconds, Python's
// suite_times.PASSED: `PASS  <file> (<s>s)`, or `PASS  <file>::<part> (<s>s)` for a part.
var passedLine = regexp.MustCompile(`^PASS  (\S+) \((\d+(?:\.\d+)?)s\)\n?$`)

// lineRead is the most bytes read at a time, Python's suite_times.LINE: a check can print one
// line longer than memory holds.
const lineRead = 4096

// keepTimes keeps the seconds the check whose whole output is the file at log printed for each
// test in the record of cwd, the checkout it ran on, as Python's suite_times.keep does once the
// check ends: only a line read whole, from its start, is one a piece printed.
func keepTimes(cwd, log string) {
	file, err := os.Open(log)
	if err != nil {
		return
	}
	defer file.Close()
	found := map[string]float64{}
	lines := bufio.NewReaderSize(file, lineRead)
	for start := true; ; {
		part, err := lines.ReadSlice('\n')
		if len(part) == 0 {
			break
		}
		whole := part[len(part)-1] == '\n' || len(part) < lineRead
		if start && whole {
			if match := passedLine.FindStringSubmatch(decoded(part)); match != nil {
				found[match[1]], _ = strconv.ParseFloat(match[2], 64) // past its range: infinite, as to Python
			}
		}
		start = whole
		if err != nil && err != bufio.ErrBufferFull {
			break
		}
	}
	suitetimes.Keep(cwd, found)
}
