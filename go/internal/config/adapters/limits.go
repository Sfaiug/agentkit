package adapters

// ClaudeLimits is the event type every `claude -p` turn prints its login's limits in and the field
// of it holding them, claude.py's `turn_meters`: `rate_limit_event`s carrying `rate_limit_info`.
var ClaudeLimits = struct{ Event, Info string }{"rate_limit_event", "rate_limit_info"}
