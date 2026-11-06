package pyre

import "strconv"

// Names are the pattern's named groups in the order Python's groupdict lists them: the engine
// numbers them after every unnumbered group, in the order they open.
func (r *Regexp) Names() []string {
	var names []string
	for _, name := range r.engine.GetGroupNames() {
		if _, numbered := strconv.Atoi(name); numbered != nil {
			names = append(names, name)
		}
	}
	return names
}
