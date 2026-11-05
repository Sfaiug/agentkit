package harness

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Forgetting is what forgetting a seat of that harness drops of what the harness kept for it, as
// Python's plugin `forget` does, to run once the seat's own files are gone; false where Go does
// not carry that harness's forget.
func Forgetting(name string, record *run.Object) (func(), bool) {
	if hook := plugins[name].forget; hook != nil {
		return hook(record)
	}
	return func() {}, true
}

// receiptGone is a forget that removes that launch's receipt folder (opencode.py and muse.py
// `forget`), moved aside first: a write the harness has in flight then finds no folder to land
// in, and cannot leave one half removed.
func receiptGone(harness string) func(*run.Object) (func(), bool) {
	return func(record *run.Object) (func(), bool) {
		return func() {
			token := record.Str(harness + "_launch")
			if !launchToken.MatchString(token) {
				return
			}
			path := filepath.Join(config.Home(), "state", harness+"-launch-"+token)
			if os.Rename(path, path+".gone") == nil {
				os.RemoveAll(path + ".gone")
			}
		}, true
	}
}

// codexForget retires the launch the record names (codex.py `forget`).  A remote enrollment, the
// seat's or one an earlier forget could not delete, goes by a request to chatgpt.com that Go
// does not make.
func codexForget(record *run.Object) (func(), bool) {
	if receipt := codexReceipt(record); receipt != nil && launchToken.MatchString(receipt.Str("remote")) {
		return nil, false
	}
	if left := config.Glob(filepath.Join(config.Home(), "state"), "codex-remote-*.forgotten"); len(left) > 0 {
		return nil, false
	}
	return func() { codexRetire(record) }, true
}
