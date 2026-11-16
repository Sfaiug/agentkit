package adapters

// ClaudeLimits is the event type every `claude -p` turn prints its login's limits in and the field
// of it holding them, claude.py's `turn_meters`: `rate_limit_event`s carrying `rate_limit_info`;
// and the field of a seat's status render holding them, Claude Code 2.1.322's `rate_limits`.
var ClaudeLimits = struct{ Event, Info, Render string }{"rate_limit_event", "rate_limit_info", "rate_limits"}
