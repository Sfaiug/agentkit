package gc

import (
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// The owner's words are what a job is measured against, and ak keeps no copy of them: a copy
// handed on breeds false findings and carries any key the owner pasted.  An older install's
// receipts saved what the owner typed into the seat since its last job, and the cursor after it,
// which the seat's record kept too.  Every pass takes them out, as Python's
// jobs.forget_owner_words does: a job of that install still running saves its copy again.

const cursor = "owner_words_cursor"

// forgetOwnerWords takes the saved words and their cursor out of every receipt, naming each, and
// the cursor out of every seat record.  One not ours where it stands, or that cannot be written,
// stays as it is for the next pass.
func (c *collection) forgetOwnerWords() {
	for _, dir := range children(job.Jobs()) {
		if forgetReceipt(dir) {
			c.report("gc: removed the owner's saved words from job " + filepath.Base(dir))
		}
		if c.failed != nil {
			return
		}
	}
	for _, path := range config.SeatFiles() {
		name, named := config.SeatFileOwner(filepath.Base(path))
		stem := strings.TrimSuffix(path, ".json")
		if record := (&reads{}).json(path); named && record != nil && record.Has(cursor) &&
			ours(path, filepath.Join(filepath.Dir(path), "."+filepath.Base(stem)+".lock"), stem+".tmp") {
			seat.Update(name, func(record *run.Object) bool {
				held := record.Has(cursor)
				record.Delete(cursor)
				return held
			})
		}
	}
}

// forgetReceipt takes the words and cursor out of the receipt of the job at dir, read again under
// its recovery lock: whether it took any out.
func forgetReceipt(dir string) bool {
	path := job.ReceiptPath(filepath.Base(dir))
	if !ours(path, filepath.Join(dir, run.RecoveryLock), filepath.Join(dir, "job.tmp")) {
		return false
	}
	release, err := run.Hold(dir)
	if err != nil {
		return false
	}
	defer release()
	receipt := (&reads{}).json(path)
	if receipt == nil || !receipt.Has("owner_words") && !receipt.Has(cursor) {
		return false
	}
	receipt.Delete("owner_words")
	receipt.Delete(cursor)
	return job.Write(dir, receipt) == nil
}

// cursorsPython is a seat record Go does not read as Python does, whose cursor Python's pass may
// take out where Go's cannot.  Every receipt is already read by the plan, which such a one makes
// Python's.
func cursorsPython() bool {
	r := &reads{}
	return slices.ContainsFunc(config.SeatFiles(), func(path string) bool {
		r.json(path)
		return r.python
	})
}

// ours is retention's proof that a record, and whatever already stands beside it, is ours (job._ours).
func ours(path string, beside ...string) bool {
	return safe(path) && !slices.ContainsFunc(beside, unsafe)
}
