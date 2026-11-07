package config

// SaveDoneCheck writes config.toml as Python's config.save does with `[done_check]`'s `key` set to
// `value`, or taken out for nil (saveSetting), refused where DoneCheck cannot read what it leaves.
func SaveDoneCheck(key string, value any, keep func() error) error {
	return saveSetting("done_check", key, value, func(root *table) error {
		_, _, err := doneCheck(root)
		return err
	}, keep)
}
