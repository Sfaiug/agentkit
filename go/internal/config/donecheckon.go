package config

// DoneCheckOn is `[done_check] on`, true unless written false (done_check.on): read alone, so a
// `model` the config no longer has never holds a seat the check is off for.  An error where the
// config cannot be read.
func DoneCheckOn() (bool, error) {
	root, err := load()
	if err != nil {
		return true, err
	}
	check, _ := root.get("done_check").(*table)
	return check.get("on") != false, nil
}
