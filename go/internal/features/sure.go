package features

import (
	"context"
	"errors"
	"slices"

	"agentkit/internal/config"
	record "agentkit/internal/run"
)

// ErrPython is a switch list Go does not read as Python surely does, which Python is to judge.
var ErrPython = errors.New("a switch list Go does not read as Python surely does")

// List is the rows the checkout's `list` answers now (menu.switch_rows), nil for no list: a
// command that fails, or answers past its wait or ctx, answers none.  ErrPython where Go's reader
// refuses what Python's may read (a lone surrogate, or a number or nesting Python's limits decide),
// or where a row's id is neither a string nor an integer: only those Go compares as Python's str()
// spells them.
func List(ctx context.Context, checkout string) ([]*record.Object, error) {
	env, err := config.ChildEnv()
	if err != nil {
		return nil, nil
	}
	out, _ := output(ctx, checkout, env, "list")
	answer, err := record.DecodeLimited(out)
	rows, _ := objects(answer)
	if errors.Is(err, record.ErrLoneSurrogate) || errors.Is(err, record.ErrLimit) || slices.ContainsFunc(rows, unspelled) {
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
