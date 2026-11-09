package harness

// Untitled is whether that harness takes no title, Python's plugin having no `title_command`,
// `sync_title` or `session_title`: known only where Go opens its seats, whose plugin says so.
func Untitled(name string) bool {
	own, plugged := plugins[name]
	return (!plugged || own.opens || own.anew) && !own.titled && own.title == nil
}
