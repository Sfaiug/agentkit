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

// RefusalReport is the file in a turn's out directory an adapter writes the meters of a refusal to.
const RefusalReport = "quota.json"

// Faults are the words every harness's failures use, besides its manifest's `[stall] faults`, that
// say a turn never ran, Python's harness.STALL.
var Faults = []string{"command not found", "Argument list too long", "not installed", "unknown flag", "unknown flags",
	"unknown shorthand flag", "unknown shorthand flags", "unknown option", "unknown options", "unknown argument",
	"unknown arguments", "unknown command", "unknown commands", "unknown model", "unknown models", "unrecognized option",
	"unrecognized options", "unrecognized argument", "unrecognized arguments", "unexpected argument", "unexpected arguments",
	"invalid option", "invalid options", "invalid model", "invalid models", "model … not found", "model … not exist",
	"model … not supported", "model~not~found", "ModelNotFoundError", "not logged in", "please~log~in", "please~run~log~in",
	"unauthorized", "unauthorised", "authentication~failed", "authentication~required", "authentication~error",
	"invalid~api~key", "invalid~x~api~key"}
