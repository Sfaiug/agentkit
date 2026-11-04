package config

import (
	"cmp"
	"math/big"
)

// Longest is the fewest characters any harness's composer shows whole, or the byte limit
// when none names a fold. Every typed line and its compact notice use this same bound.
func Longest() int64 {
	var most int64
	manifests, _ := manifests()
	for _, root := range manifests {
		screen, _ := root.get("screen").(*table)
		if fold, ok := screen.get("folds_over").(*big.Int); ok && fold.Sign() != 0 && fold.IsInt64() && (most == 0 || fold.Int64() < most) {
			most = fold.Int64()
		}
	}
	return cmp.Or(most, maxBytes)
}
