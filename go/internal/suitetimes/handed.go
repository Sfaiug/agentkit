package suitetimes

import "os"

// Handed is the record of checkout's repository as AK_TIMES hands it to each piece of a suite,
// Python's suite_times.handed: "" before any.
func Handed(checkout string) string {
	data, _ := os.ReadFile(path(checkout))
	return string(data)
}
