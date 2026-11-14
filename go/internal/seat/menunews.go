package seat

// The menu reads these between frames, and notices stays there emptied; none changes a seat's word.
func menuNewsState(name string) bool {
	return name == "update-result" || name == "notices" || name == "installed-at"
}
