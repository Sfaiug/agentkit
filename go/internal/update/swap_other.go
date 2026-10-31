//go:build !(linux && (amd64 || arm64))

package update

// exchange is nil where Go reaches no call that swaps two directories in one step: Python's
// versions.exchange takes macOS's renamex_np, outside Go's standard library, so Main leaves each
// move of ~/agentkit there to Python.
var exchange func(one, other string) error
