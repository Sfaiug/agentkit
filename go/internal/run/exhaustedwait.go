package run

import "strings"

// ExhaustedWait is what the tick brings an `exhausted` run back on, Python's
// transitions.exhausted_wait: "window" for a provider that refused it, "reviewer" for a reviewer
// that died on its transport, which spent no window.  Any other waits on nobody but a resume by
// hand, and so does one a later merged run replaced, its work done elsewhere: "".
func ExhaustedWait(record *Object) string {
	switch {
	case record.Str("state") != "exhausted" || record.Truthy("replaced"):
		return ""
	case record.Truthy("quota_dry"):
		return "window"
	case strings.Contains(record.Str("error"), "API/transport errors"):
		return "reviewer"
	}
	return ""
}
