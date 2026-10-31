package usage

import "testing"

// Python's usage.probe_refused: a rate limit, a whole HTTP 5xx or a probe that never came back.
func TestRefusedIsTheEndpointNotTheLogin(t *testing.T) {
	for said, want := range map[string]bool{
		"unknown: HTTP 429 from api.example/usage": true, "unknown: http 503 Service Unavailable": true,
		"curl: timed out": true, "unknown: HTTP 5030": false, "unknown: XHTTP 503": false,
		"unknown: HTTP 401 from api.example/usage after 1.429 s; run acme login": false,
		"unknown: token expired": false,
	} {
		if refused(said) != want {
			t.Errorf("refused(%q) = %v", said, !want)
		}
	}
}
