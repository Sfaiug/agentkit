package run

import (
	"errors"
	"math"
	"testing"
)

func decoded(t *testing.T, text string) *Object {
	t.Helper()
	value, err := Decode([]byte(text))
	record, _ := value.(*Object)
	if err != nil || record == nil {
		t.Fatalf("%q: %v", text, err)
	}
	return record
}

// A record goes out as Python's json.dumps(record, indent=2) writes what json.loads read.
func TestRecordGoesOutAsPythonWritesIt(t *testing.T) {
	record := decoded(t, `{"a": 1.50, "b": 1e400, "a": -0, "c": "café 😀", "n": NaN,
		"d": 1E2, "list": [1, [], {}], "nested": {"x": null, "y": true}, "tab": "a\tb\"\\"}`)
	want := `{
  "a": 0,
  "b": Infinity,
  "c": "caf\u00e9 \ud83d\ude00",
  "n": NaN,
  "d": 100.0,
  "list": [
    1,
    [],
    {}
  ],
  "nested": {
    "x": null,
    "y": true
  },
  "tab": "a\tb\"\\"
}`
	if got := Encode(record); got != want {
		t.Fatalf("got\n%s", got)
	}
	// and as json.dumps(record) writes it, on one line
	if got := Line(record); got != `{"a": 0, "b": Infinity, "c": "caf\u00e9 \ud83d\ude00", "n": NaN, "d": 100.0, "list": [1, [], {}], "nested": {"x": null, "y": true}, "tab": "a\tb\"\\"}` {
		t.Fatalf("got %s", got)
	}
	if got, _ := record.Num("n"); !math.IsNaN(got) {
		t.Fatalf("NaN read as %v", got)
	}
	// a byte of a path no UTF-8 holds is the surrogate os.fsdecode reads it as
	if got := Encode("/tmp/caf\xff"); got != `"/tmp/caf\udcff"` {
		t.Fatalf("got %s", got)
	}
}

func TestFloatIsPythonRepr(t *testing.T) {
	for value, want := range map[float64]Number{1e16: "1e+16", 0.0001: "0.0001", 1e-5: "1e-05", 3: "3.0",
		123456789012345.6: "123456789012345.6", math.Inf(-1): "-Infinity"} {
		if got := Float(value); got != want {
			t.Errorf("%v: got %s, want %s", value, got, want)
		}
	}
}

func TestUnreadableJSONIsRefused(t *testing.T) {
	long := make([]byte, maxDigits+1)
	for i := range long {
		long[i] = '1'
	}
	for _, text := range []string{`{"a":}`, `[1,]`, `{"a": 1} x`, "\"\xff\"", `'a'`, "\"a\x01\"", `01`, `{"a" 1}`, ``, string(long)} {
		if _, err := Decode([]byte(text)); err == nil {
			t.Errorf("%q read", text)
		}
	}
	for _, text := range []string{`"\ud800"`, `"\udcff"`, `{"\ud83d x": 1}`, `"\ude00\ud83d"`} {
		if _, err := Decode([]byte(text)); !errors.Is(err, ErrLoneSurrogate) {
			t.Errorf("%q: %v", text, err)
		}
	}
}
