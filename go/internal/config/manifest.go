package config

import (
	"cmp"
	"math/big"
	"unicode/utf8"
)

// Pairs is one of Section's inline tables as KEY=value words, in the order written: none where
// value is no table, false where one of its values is not a string.
func Pairs(value any) ([]string, bool) {
	block, _ := value.(*table)
	if block == nil {
		return nil, true
	}
	var pairs []string
	for _, key := range block.keys {
		word, ok := block.values[key].(string)
		if !ok {
			return nil, false
		}
		pairs = append(pairs, key+"="+word)
	}
	return pairs, true
}

// maxBytes is the most a line typed into a seat may hold: tmux refuses one command past 16 KiB.
const maxBytes = 8000

// TooLong is whether line is more than a line typed into a seat may hold, as Python's
// watch.too_long: one every harness's composer shows whole, the fewest characters any manifest's
// `[screen] folds_over` names.
func TooLong(line string) bool {
	var most int64
	manifests, _ := manifests()
	for _, root := range manifests {
		screen, _ := root.get("screen").(*table)
		if fold, ok := screen.get("folds_over").(*big.Int); ok && fold.Sign() != 0 && fold.IsInt64() && (most == 0 || fold.Int64() < most) {
			most = fold.Int64()
		}
	}
	return int64(utf8.RuneCountInString(line)) > cmp.Or(most, maxBytes) || len(line) > maxBytes
}
