package host

// held is whether another process holds that turn file's lock now: no suite takes one here.
func held(string) bool {
	return false
}
