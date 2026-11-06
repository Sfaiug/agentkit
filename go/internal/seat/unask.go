package seat

import (
	"slices"
	"strings"

	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// Unask retires the seat's questions that begin with prefix, standing or kept back, every other
// question keeping its words and dates (notify.clear with a prefix and no wait).
func Unask(name, prefix string) error { return notify.Unask(name, prefix, unkeep) }

// unkeep takes the questions that begin with prefix from those the seat kept back, under its lock:
// with none left, it keeps none.
func unkeep(name, prefix string) error {
	path := seatFile(name)
	return put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, false, func(data *run.Object) bool {
		kept := questionsKept(data.Dict("unasked"), nil)
		left := slices.DeleteFunc(slices.Clone(kept), func(q *run.Object) bool { return strings.HasPrefix(q.Str("text"), prefix) })
		if len(left) == len(kept) {
			return false
		}
		var unasked any
		if len(left) > 0 {
			unasked = keptRecord(left)
		}
		return set([]field{{"unasked", unasked}}, field{"session", name})(data)
	})
}
