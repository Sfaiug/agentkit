package seat

// The menu reads these between frames; neither changes a seat's word.
func menuNewsState(name string) bool {
	return name == "update-result" || name == "installed-at"
}
