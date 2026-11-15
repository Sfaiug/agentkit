package loop

import "testing"

// The worker's receipts are bookkeeping, even a login named like a refusal.
func TestATurnsReceiptsAreNeverWhatItsHarnessSaid(t *testing.T) {
	out := saidIn(t, map[string]string{"harness": "codex", "account": "402", "model": "rate-limited", "stderr.log": "fine\n"})
	if said := harnessSaid(out, "", "", false); said != "fine" {
		t.Fatalf("said %q", said)
	}
}
