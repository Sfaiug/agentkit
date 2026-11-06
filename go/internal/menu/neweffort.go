package menu

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
)

// A draft's Models are its own copy of the config's, so an effort stepped on its models screen
// is the new seat's alone: the row, the picker and the seat opened (seat.Open) read it there,
// and config.toml keeps its bytes, as Python's born row does.

func (d *Draft) columns() []int { return matrix.Stops(d.marks(d.Names[d.At])) }

// move goes by one stop along the highlighted row, as c's ←/→ do.
func (d *Draft) move(by int) {
	columns := d.columns()
	d.Column = columns[max(0, min(len(columns)-1, slices.Index(columns, d.Column)+by))]
}

// keepColumn puts the cursor on its role's mark where the row now highlighted has no effort there.
func (d *Draft) keepColumn() {
	if !slices.Contains(d.columns(), d.Column) {
		d.Column -= 3
	}
}

// step takes the effort under the cursor one level on, from the highest round to the lowest,
// the row's other shown efforts staying where they stand.
func (d *Draft) step() {
	name, key := d.Names[d.At], config.RoleEfforts[d.Column-3]
	levels := d.Levels[name]
	if len(levels) == 0 {
		return
	}
	var hold []string
	for _, column := range d.columns() {
		if column >= 3 && column != d.Column {
			hold = append(hold, config.RoleEfforts[column-3])
		}
	}
	word := levels[(slices.Index(levels, d.effort(name, key))+1)%len(levels)]
	model := d.Models[name]
	model.Efforts = config.EffortStep{Model: name, Key: key, Effort: word, Hold: hold}.Apply(model.Efforts)
	d.Models[name] = model
}
