package run

import "agentkit/internal/parsed"

// shared is ReadJSON kept while a file's stat is unchanged (Python's config._read_json with
// `shared`).
var shared = parsed.Of(ReadJSON)

// Shared is ReadJSON as it read that file while its stat is unchanged, every reader's, so only
// read it: a writer reads what it changes with ReadJSON, into an object of its own.  Never a run's
// record, which a Reader holds once.
func Shared(path string) (*Object, error) { return shared.Read(path) }
