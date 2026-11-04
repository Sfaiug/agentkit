package harness

// An adapter without a plugin uses Python's default hooks: its record owns the
// launcher's conversation, and its manifest decides what the screen says.
func seatDefaults(name string) plugin {
	if own, named := plugins[name]; named || name == "" {
		return own
	}
	return plugin{seats: true, looks: true}
}
