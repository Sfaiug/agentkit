package config

// AuditOff is whether config.toml says `[audit] on = false`: the audit runs until written off.
func AuditOff() bool {
	value, _, err := topLevel("audit")
	audit, _ := value.(*table)
	return err == nil && audit != nil && audit.values["on"] == false
}

// MayRent is whether `[google_cloud]` lets ak rent machines, or is not one Go can read.
func MayRent() bool {
	value, _, err := topLevel("google_cloud")
	if err != nil {
		return true
	}
	if value == nil {
		return false
	}
	rented, ok := value.(*table)
	return !ok || rented.values["active"] == true
}
