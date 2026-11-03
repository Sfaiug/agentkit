package usage

import "strings"

// Owns is whether a state file is the usage read's own, which says nothing of any seat: its cache,
// the lock it is written under and a write on its way there, an adapter's own probe cache
// (`usage-meta-probe.json`), and each provider's probe moment and when to ask it again.
func Owns(name string) bool {
	return strings.HasPrefix(name, "usage.") || strings.HasPrefix(name, "usage-") ||
		strings.HasSuffix(name, "-probe.lock") || strings.HasSuffix(name, "-probe.retry")
}
