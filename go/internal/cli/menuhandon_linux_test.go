package cli

import (
	"os"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/menu"
)

// handing sets this program's environment as an exec handed it data would.
func handing(t *testing.T, data []byte) {
	name, value, _ := strings.Cut(cross(menuRead, data)[0], "=")
	t.Setenv(name, value)
}

func TestAReadCrossesAnExecOnlyToTheSameCodeAndOnlyOnce(t *testing.T) {
	found := reading{seats: []menu.Seat{{Number: 1, Name: "acme", Word: "idle", Done: 1, Total: 2}},
		cells: []menu.Cell{{Label: "Claude", Left: 40}}, standing: "a token ends soon",
		past: []menu.PastSeat{{Seat: menu.Seat{Name: "fix-api"}, Closed: 1.5}}}
	handing(t, handOn(found))
	if got, ok := handedRead(); !ok || !reflect.DeepEqual(got, found) {
		t.Fatalf("handed %+v %v", got, ok)
	}
	if _, set := os.LookupEnv(menuRead); set {
		t.Fatal("the variable stayed for what this program starts")
	}
	if _, ok := handedRead(); ok {
		t.Fatal("a read crossed twice")
	}
	for _, made := range [][]byte{pickled("python's code", []byte("{}")), []byte("\x80\x04garbage"), handOn(found)[:9]} {
		handing(t, made)
		if _, ok := handedRead(); ok {
			t.Fatalf("took %q", made)
		}
	}
	other, _, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv(menuRead, strconv.Itoa(int(other.Fd())))
	if crossed(menuRead); other.Close() != nil {
		t.Fatal("a descriptor no cross made was closed")
	}
}
