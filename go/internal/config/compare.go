package config

// RememberCompare saves the marked release slugs, with no marks meaning every release.
// Like c, it prepares existing seats before atomically replacing the whole config.
func RememberCompare(marks []string, keep func() error) error {
	_, file, err := modelFile()
	if err != nil {
		return err
	}
	return saveConfig(file, func(root *table) error {
		if len(marks) == 0 {
			delete(root.values, "compare")
		} else {
			root.put("compare", listed(marks))
		}
		return nil
	}, keep)
}
