package seat

import (
	"slices"
	"strings"
)

// Recommendation caches and temporary originals do not affect seat listings. Matrix cannot be imported here:
// its refresh reads the build through update, whose harness updates use seats.
func recommendationState(name string) bool {
	stem, suffix, _ := strings.Cut(name, ".")
	return strings.HasPrefix(name, adviceBackupPrefix) ||
		(stem == "boards" || stem == "matrix") && slices.Contains([]string{"json", "lock", "tmp"}, suffix)
}
