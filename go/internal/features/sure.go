package features

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"slices"
	"strings"
	"unicode/utf8"
)

// ErrPython is a switch list Go does not read as Python surely does, which Python is to judge.
var ErrPython = errors.New("a switch list Go does not read as Python surely does")

// List is the checkout's switches as its `list` answers now, nil for no list (a command that
// fails or answers past its wait is none); ErrPython where Python may read the answer otherwise
// (decode) or spell a row's id otherwise (spell).
func List(ctx context.Context, checkout string) ([]Switch, error) {
	out, _ := output(ctx, checkout, "list")
	answer, err := decode(out)
	listed, _ := answer.([]any)
	if err == ErrPython || slices.ContainsFunc(listed, unspelled) {
		return nil, ErrPython
	}
	rows, _ := switches(answer)
	return rows, nil
}

// decode is a command's JSON answer, each number as written, where Python's json.loads surely
// reads it so; ErrPython where it may not: an answer Go's reader refuses holding NaN or Infinity,
// which Python's reads, or one holding more digits in a row than 640, the fewest Python's int can
// be held to reading (int_max_str_digits, 4300 unless set), past which it refuses the answer.
func decode(out []byte) (any, error) {
	var answer any
	reader := json.NewDecoder(bytes.NewReader(out))
	reader.UseNumber()
	if reader.Decode(&answer) != nil || reader.Decode(new(any)) != io.EOF {
		if bytes.Contains(out, []byte("NaN")) || bytes.Contains(out, []byte("Infinity")) {
			return nil, ErrPython
		}
		return nil, errors.New("no JSON")
	}
	digits := bytes.FieldsFunc(out, func(r rune) bool { return r < '0' || r > '9' })
	if slices.ContainsFunc(digits, func(run []byte) bool { return len(run) > 640 }) {
		return nil, ErrPython
	}
	return answer, nil
}

// spell is a switch's id as Python's str() spells it, and whether Go knows that spelling: a string
// as it is and an integer in its digits, whole however large.  A string holding U+FFFD is not
// known, as Go's reader writes that for what Python's keeps (a lone surrogate) or replaces
// otherwise (bytes not UTF-8); nor is another kind of value, which Go prints as it does, a number
// with a fraction or an exponent as the float it is, as the switches screen has always shown it.
func spell(id any) (string, bool) {
	switch id := id.(type) {
	case string:
		return id, !strings.ContainsRune(id, utf8.RuneError)
	case json.Number:
		if id == "-0" {
			return "0", true // json.loads reads it as the int 0
		}
		if !strings.ContainsAny(string(id), ".eE") {
			return string(id), true
		}
		float, _ := id.Float64()
		return fmt.Sprint(float), false
	}
	return fmt.Sprint(id), false
}

// unspelled is a row of a list, as switch_rows takes one, whose id Go does not spell as Python.
func unspelled(each any) bool {
	row, _ := each.(map[string]any)
	id, named := row["id"]
	_, spelled := spell(id)
	return named && !spelled
}
