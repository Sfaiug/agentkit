package config

// HookEvents is each `[[hooks.event]]` entry of a harness's manifest, in its order, none where
// it has none: what the harness's lifecycle events mean is the lifecycle package's to read.
func HookEvents(harness string) ([]map[string]any, error) {
	manifests, err := manifests()
	hooks, _ := manifests[harness].get("hooks").(*table)
	rows, _ := hooks.get("event").(tableArray)
	entries := make([]map[string]any, len(rows))
	for i, row := range rows {
		entries[i] = row.values
	}
	return entries, err
}
