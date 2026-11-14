package loop

import "agentkit/internal/run"

// GitHubMerged is whether GitHub merged the run's pull request as its delivery, which `ak run
// merge` only records (redeliver): nothing runs a turn for it.
func GitHubMerged(dir string, record *run.Object) bool {
	current, err := prHead(dir, record.Str("pr"))
	return err == nil && current.Truthy("merged") && isDelivery(record, current, repoFrom(record).upstream())
}
