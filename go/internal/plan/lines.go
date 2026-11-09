package plan

// Lines is the seat's plan's lines, as Python's plan.lines reads them: none without a plan, and an
// error where it has one nothing can read.
func Lines(current string) ([]string, error) { return read(current) }
