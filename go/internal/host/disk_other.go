//go:build !linux

package host

// diskReadings are none here: off Linux gc's plan, the disk's one reader, is Python's.
func diskReadings(string) Readings { return Readings{} }
