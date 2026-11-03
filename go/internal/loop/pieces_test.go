//go:build linux

package loop

import (
	"testing"
	"time"
)

// Green, red and flaky pieces share one piecesCap: 40 loud pieces, half red or each red then green
// on its re-run, hand on their 256 KB with the pieces' headers and record lines, under 300 KB.
func TestPiecesShareOneBound(t *testing.T) {
	loud := `head -c 30000 /dev/zero | tr '\0' X | fold -w 1500`
	cases := []struct {
		name, command string
		pass          bool
	}{
		{"half red", loud + `; test "${AK_SHARD%/*}" -le 20 # AK_SHARD`, false},
		{"all flaky", `p="ran-${AK_SHARD%/*}"; test -e "$p" && { ` + loud + `; exit 0; }; : >"$p"; ` + loud + ` | tr X Y; exit 1 # AK_SHARD`, true},
	}
	for _, each := range cases {
		t.Run(each.name, func(t *testing.T) {
			l := rig(t, 30*time.Second)
			t.Setenv("AK_HOST_READINGS", `{"cpus":64,"free_mb":16400,"mem_total_mb":65536}`)
			ok, text := l.checked(t, each.command)
			if ok != each.pass || len(text) < piecesCap/2 || len(text) > 300*1024 {
				t.Fatalf("passed %v, handed on %d bytes", ok, len(text))
			}
		})
	}
}
