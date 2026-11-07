package features

import (
	"encoding/json"
	"testing"
)

// An integer id is shown in its digits, as Python spells it; one with a fraction or an exponent
// as the float it is, as the switches screen showed it before numbers were read as written.
func TestAnIdIsShownInItsDigitsOrAsTheFloatItIs(t *testing.T) {
	for id, want := range map[string]string{"1000000": "1000000", "-0": "0", "1e-7": "1e-07", "100000000000000000.0": "1e+17"} {
		if got, _ := spell(json.Number(id)); got != want {
			t.Errorf("%s shows as %q, not %q", id, got, want)
		}
	}
}
