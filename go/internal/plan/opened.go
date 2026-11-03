package plan

// Opened is whether the seat's plan, under the name it goes by now, has an open line `ak plan`
// wrote, as Python's open_lines finds any: a line kept by hand counts for nothing.
func Opened(current string) (bool, error) {
	lines, err := read(current)
	for _, line := range lines {
		if _, written := parse(line); written && open(line) {
			return true, nil
		}
	}
	return false, err
}
