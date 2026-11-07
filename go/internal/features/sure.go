package features

import (
	"context"
	"encoding/json"
	"errors"
	"slices"

	"agentkit/internal/config"
	record "agentkit/internal/run"
)

// ErrPython is a switch list Go does not read as Python surely does, which Python is to judge.
var ErrPython = errors.New("a switch list Go does not read as Python surely does")

// List is the rows the checkout's `list` answers now (menu.switch_rows), nil for no list: a
// command that fails, or answers past its wait or ctx, answers none.  Go judges only plain JSON,
// each id a string or an integer, which it compares as Python's str() spells them; ErrPython for
// the rest, Python's to judge: an answer Go's reader refuses where Python's may read it (a lone
// surrogate, or a number or nesting Python's limits decide), one holding NaN or Infinity, which
// Python's json reads and JSON does not hold, or one with a row whose id is another kind of value.
func List(ctx context.Context, checkout string) ([]*record.Object, error) {
	env, err := config.ChildEnv()
	if err != nil {
		return nil, nil
	}
	out, _ := output(ctx, checkout, env, "list")
	answer, err := record.DecodeLimited(out)
	rows, _ := objects(answer)
	if errors.Is(err, record.ErrLoneSurrogate) || errors.Is(err, record.ErrLimit) || err == nil && !json.Valid(out) ||
		slices.ContainsFunc(rows, unspelled) {
		return nil, ErrPython
	}
	return rows, nil
}

// unspelled is a row whose id is neither a string nor an integer.
func unspelled(row *record.Object) bool {
	switch id := row.Get("id").(type) {
	case string:
		return false
	case record.Number:
		return !record.Integral(id)
	}
	return true
}
