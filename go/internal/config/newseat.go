package config

// DefaultOrchestrator is the last creation's orchestrator, kept to the models still offered.
func DefaultOrchestrator() (string, error) {
	root, err := load()
	if err != nil {
		return "", err
	}
	name, _ := root.values["defaults"].(*table).get("orchestrator").(string)
	for _, offered := range offered(root) {
		if offered == name {
			return name, nil
		}
	}
	return offered(root)[0], nil
}

// HarnessName is the manifest's screen name, else the harness's own name.
func HarnessName(harness string) string {
	found, _ := manifests()
	if name, ok := found[harness].get("name").(string); ok && name != "" {
		return name
	}
	return harness
}
