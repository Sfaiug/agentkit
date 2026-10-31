package harness

import "testing"

// The cases tests/test_path_is_not_a_rate_limit.py and test_quota_words_bounded.py hold.
func TestLimitedReadsTheStatusNotAPath(t *testing.T) {
	paths := []string{"/tmp/acme-429/run/log.txt", "~/.agentkit/wt/20261004-0726-review-pr-acme-429/round-1/log.txt",
		"./acme-429/run.log", "acme-429/log.txt", "/tmp/429", "/tmp/acme(429)/run.log", "20261004-0726-review-pr-acme-429",
		"log-429.txt", `C:\tmp\acme-429\log.txt`, `\\acme\429\log.txt`, "/tmp/acme:429", "agentkit/run.py:429:7",
		`File "/tmp/acme/run.py", line 429, in main`, "20261004-0726-run.log.429", "20261004-0726-run.log-429",
		"run.log.429", "run.log-429", "~/.agentkit/wt/20261005-0626-fix-agentkit-quota-wait/round-1/log.txt",
		"/home/acme/.agentkit/runs/20261005-0626-fix-agentkit-rate-limit-wait/log.txt"}
	for _, path := range paths {
		for _, gap := range []string{" ", "\n", "\t"} {
			if said := "Stopped at" + gap + path; Limited(said) {
				t.Errorf("%q read as a rate limit", said)
			}
		}
	}
	for _, refusal := range []string{"API Error:429", "429 Too Many Requests", "429", `{"error":{"status":429}}`, "(code 429)"} {
		for _, said := range []string{refusal, paths[0] + ": " + refusal, refusal + "; log: " + paths[0]} {
			if !Limited(said) {
				t.Errorf("%q not read as a rate limit", said)
			}
		}
	}
	for _, said := range []string{"HTTP/1.1 429 Too Many Requests", "429.", "rate limited", "ratelimited", "Rate-Limit error", "unknown: HTTP 429 from api.example/usage"} {
		if !Limited(said) {
			t.Errorf("%q not read as a rate limit", said)
		}
	}
	for _, said := range []string{"unknown: HTTP 401 from api.example/usage after 1.429 s; run acme login", "4290", "v1.429"} {
		if Limited(said) {
			t.Errorf("%q read as a rate limit", said)
		}
	}
}
