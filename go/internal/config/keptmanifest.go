package config

import (
	"os"
	"sync"

	"agentkit/internal/parsed"
)

// The manifests are read at every draw and every look, so each is parsed once while it stands, as
// Python's config.manifest keeps one by path and mtime: what parsing them again made was most of
// what an open screen ever allocated.

// shippedManifest is a manifest the binary ships, parsed once, as it never changes.
func shippedManifest(file string) (*table, error) {
	kept, _ := shippedManifests.LoadOrStore(file, sync.OnceValues(func() (*table, error) {
		return keptManifest(file, adapters.ReadFile)
	}))
	return kept.(func() (*table, error))()
}

var shippedManifests sync.Map

// adapterManifests is a manifest in $AGENTKIT_ADAPTER_DIR, parsed again only once it changed.
var adapterManifests = parsed.Of(func(file string) (*table, error) { return keptManifest(file, os.ReadFile) })

func keptManifest(file string, load func(string) ([]byte, error)) (*table, error) {
	data, err := load(file)
	if err != nil {
		return nil, err
	}
	return parseDocument(string(data))
}
