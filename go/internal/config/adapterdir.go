package config

import "os"

// AdapterDir is the folder of adapters $AGENTKIT_ADAPTER_DIR names, "" where it names none, as
// every real home, where Go runs no turn (worker.Adapter).
func AdapterDir() string {
	if dir := os.Getenv(adapterDir); dir != "" {
		return Expand(dir)
	}
	return ""
}
