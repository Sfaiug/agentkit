// Package sqlite is Go's one SQLite: SQLite itself, compiled to WebAssembly, the one binding whose
// build fits in a landing piece.  ak opens history.db and a harness's own store through it, and
// reads the latter as Python's sqlite3 does, its write-ahead log included.
package sqlite

import (
	"os"
	"path/filepath"
	"sync"

	"github.com/ncruces/go-sqlite3"
	_ "github.com/ncruces/go-sqlite3/embed"
	"github.com/tetratelabs/wazero"
	"github.com/tetratelabs/wazero/api"
)

// Open is a connection to that file, opened with those flags.
func Open(path string, flags sqlite3.OpenFlag) (*sqlite3.Conn, error) {
	compiled.Do(cacheCompiles)
	return sqlite3.OpenFlags(path, flags)
}

var compiled sync.Once

// cacheCompiles keeps SQLite's compiled WebAssembly under the user's cache directory, so only the
// first open there pays for compiling it, under the limits the binding sets itself.
func cacheCompiles() {
	dir, err := os.UserCacheDir()
	if err != nil {
		return
	}
	cache, err := wazero.NewCompilationCacheWithDir(filepath.Join(dir, "agentkit", "sqlite"))
	if err != nil {
		return
	}
	sqlite3.RuntimeConfig = wazero.NewRuntimeConfig().WithMemoryLimitPages(4096).
		WithCoreFeatures(api.CoreFeaturesV2).WithCompilationCache(cache)
}
