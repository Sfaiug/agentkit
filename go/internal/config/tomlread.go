package config

// ReadTOML is what text holds as Python's tomllib.loads reads it, each table a map and each array
// of tables a list of them, or why it is no TOML.
func ReadTOML(text string) (map[string]any, error) {
	root, err := parseDocument(text)
	if err != nil {
		return nil, err
	}
	return plain(root).(map[string]any), nil
}
