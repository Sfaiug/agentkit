package matrix

import "agentkit/internal/run"

func runners(row *run.Object) [][2]string {
	var found [][2]string
	for _, value := range row.List("yours") {
		if entry, ok := value.(*run.Object); ok {
			found = append(found, [2]string{entry.Str("harness"), entry.Str("model")})
		}
	}
	return found
}

// Stored is the last complete lineup while the boards are being read again.
func Stored() *Matrix {
	held := stored()
	fetched, _ := held.Num("fetched_at")
	return &Matrix{Rows: rowsOf(held.List("lineup")), Fetched: fetched}
}
