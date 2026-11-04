package harness

import (
	"agentkit/internal/hookfact"
	"agentkit/internal/run"
)

// grokRecord leaves the default plugin's reconciliation of unissued conversations and all
// hook facts to Python. A hook arriving after this boundary belongs to the next listing.
func grokRecord(name string, record *run.Object) (plugin, bool) {
	own := plugins["grokbuild"]
	fact := hookfact.Standing(name)
	ready := (!record.Truthy("conversation") || record.Get("id_source") == "launcher") &&
		fact.Event == "" && fact.At == 0 && len(fact.Holds) == 0
	own.heard = func(string) hookfact.Fact { return fact }
	return own, ready
}
