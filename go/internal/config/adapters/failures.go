// Package adapters holds, beside the manifests, the one list of failure words no manifest carries.
package adapters

// Failures are the `[stall]` keys a seat's error is read by, strongest first, the first a spent
// window, each with the words every harness's failures use besides its manifest's (Python's
// harness.STALL), but for the ones that say a turn never ran, which a seat's error line never is.
var Failures = []struct {
	Key   string
	Words []string
}{
	{"quotas", []string{"402", "billing_error", "payment required"}},
	{"refusals", []string{"API Error", "529", "unexpected status"}},
	{"outages", []string{"overloaded", "at capacity", "Internal server error", "Bad Gateway", "Gateway Timeout",
		"Service unavailable", "The service is busy", "idle timeout", "Can't reach the API server", "HTTP~5##", "status~5##", "API Error~5##"}},
}
