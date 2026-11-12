package seat

import "regexp"

// owedWrite is whether a seat's file of that kind and suffix is a write of whether its plan owes a
// done check on its way to owed-<seat>.json, named by the process and the thread writing it
// (done_check.owed), which no word reads.
func owedWrite(kind, suffix string) bool { return kind == "owed" && owedWriting.MatchString(suffix) }

var owedWriting = regexp.MustCompile(`^json\.[0-9]+\.[0-9]+$`)
