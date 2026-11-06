//go:build !linux

package host

// untag leaves the tag where no /proc shows it, and where no leftover sweep looks for it.
func untag() {}
