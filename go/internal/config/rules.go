package config

// ScreenRules is each `[[rule]]` entry of a harness's manifest, in its order, none where it has
// none: what they mean is the screen package's to read.
func ScreenRules(harness string) ([]map[string]any, error) {
	manifests, err := manifests()
	rows, _ := manifests[harness].get("rule").(tableArray)
	entries := make([]map[string]any, len(rows))
	for i, row := range rows {
		entries[i] = row.values
	}
	return entries, err
}
