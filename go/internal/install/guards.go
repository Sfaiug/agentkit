package install

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// guards links each seat guard, tools/<name>-shim of the checkout whose bin/ holds this program,
// as ~/.agentkit/bin/<name>, the folder first on a seat's PATH, as Python's guard.install_shim
// does.  Every install, which every update runs, links them all, so a guard an update adds covers
// the seats already open and a link left elsewhere, an older checkout's, is pointed here again.
func guards() error {
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	// go/tools holds Go's guards, each a link to the shim body the seat package embeds, beside
	// `ak`, a link to this checkout's program: the body asks the `ak` beside the link it is run
	// through, so each is linked as it lies there.  Beside them are links to the Python tools Go
	// runs from config.Repo(), which is go/ in a copied tree with no git.
	tools := filepath.Join(filepath.Dir(filepath.Dir(config.Resolve(executable))), "tools")
	bin := filepath.Join(config.Home(), "bin")
	if err := os.MkdirAll(bin, 0o777); err != nil {
		return err
	}
	for _, guard := range config.Glob(tools, "*-shim") {
		link := filepath.Join(bin, strings.TrimSuffix(filepath.Base(guard), "-shim"))
		if at, _ := os.Readlink(link); at == guard {
			continue
		}
		// made aside and moved in whole, so a seat's call never finds the guard missing
		tmp := filepath.Join(bin, fmt.Sprintf(".%s.%d", filepath.Base(link), os.Getpid()))
		if err := os.Symlink(guard, tmp); err != nil {
			return err
		}
		if err := os.Rename(tmp, link); err != nil {
			return err
		}
	}
	return nil
}
