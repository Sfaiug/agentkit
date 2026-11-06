//go:build !linux

package localtime

// zone is the zone file the C library reads rule as, which outside glibc dates an undated rule by
// POSIX's default, as Go does.
func zone(rule string) []byte { return posix(rule) }
