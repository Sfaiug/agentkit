package loop

import (
	"bufio"
	"io"
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
// check ends.
func keepTimes(cwd, log string) {
	suitetimes.Keep(cwd, measured(log, 0))
}

// measured is the seconds the output in the file at log from offset printed for each test,
// Python's suite_times.measured: only a line read whole, from its start, is one a piece printed.
func measured(log string, offset int64) map[string]float64 {
	found := map[string]float64{}
	file, err := os.Open(log)
	if err != nil {
		return found
	}
	defer file.Close()
	lines := bufio.NewReaderSize(io.NewSectionReader(file, offset, 1<<62), lineRead)
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
	return found
}
