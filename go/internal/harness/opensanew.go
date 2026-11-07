package harness

// OpensAnew is whether Go opens a new seat of that harness: every harness it opens (Opens), and
// one whose seats it opens only anew, leaving reopening them to Python.
func OpensAnew(name string) bool {
	_, known := Opens(name)
	return known || plugins[name].anew
}
