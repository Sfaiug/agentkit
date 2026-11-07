package features

import (
	"cmp"
	"slices"
	"time"
)

// Heads is the switches' columns, each the word `set` is told: a switch is only ever you or
// everyone, never a user picked by id.
var Heads = []string{"you", "everyone"}

// Flip flips the checkout's feature's mark under Heads[column] through the project's own `set`
// (menu.features_flip), and the row it answers with stands in its reading; what to say under the
// rows, or "".  A failed `set` changes no mark and says why in one line, and one of a feature
// flipped again before it answered, from its screen opened again after Esc, is not drawn: the
// later one is.  The checkout was Read.
func Flip(checkout, feature string, column int) string {
	held.Lock()
	found := known[checkout]
	at := slices.IndexFunc(found.Rows, func(row Switch) bool { return row.ID == feature })
	if at < 0 || column == 0 && found.Rows[at].Fixed {
		held.Unlock()
		return ""
	}
	value := "on"
	if row := found.Rows[at]; row.Everyone || column == 0 && row.You {
		value = "off"
	}
	if found.flips == nil {
		found.flips = map[string]int{}
	}
	found.flips[feature]++
	asked := found.flips[feature]
	held.Unlock()
	answer, why := run(checkout, "set", feature, Heads[column], value)
	answered, _ := switches([]any{answer})
	if len(answered) == 0 || answered[0].ID != feature {
		return cmp.Or(why, "set answered no row")
	}
	held.Lock()
	if found.flips[feature] != asked {
		held.Unlock()
		return ""
	}
	rows := slices.Clone(found.Rows) // never the old rows changed: a reading keeps its own
	for i, row := range rows {
		if row.ID == feature {
			rows[i] = answered[0]
		}
	}
	found.Rows, found.set = rows, time.Now()
	held.Unlock()
	land()
	return ""
}
