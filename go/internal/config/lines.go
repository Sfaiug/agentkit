package config

// noLimit is how config.toml and a project's front matter say a line limit has none.
const noLimit = "no limit"

// Lines is a line limit: at most so many added lines, or "no limit", a value of its own that no
// number stands for.
type Lines struct {
	most int
	none bool
}

// NoLimit is the line limit that has none.
var NoLimit = Lines{none: true}

// AtMost is a limit of n added lines.
func AtMost(n int) Lines { return Lines{most: n} }

// Most is the limit, and false where there is none.
func (l Lines) Most() (int, bool) { return l.most, !l.none }

// Said is the limit as Python's records and words hold it: its number, or "no limit".
func (l Lines) Said() any {
	if l.none {
		return noLimit
	}
	return l.most
}
