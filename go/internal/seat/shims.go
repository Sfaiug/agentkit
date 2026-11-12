package seat

import (
	_ "embed"
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// shimBody is the sh every shim runs, carried in the program so one with no checkout beside it
// still has its shims.  It asks the program it finds beside its own resolved path as `ak`.
//
//go:embed shim
var shimBody []byte

// shimmed are the tools a seat's call reaches through a shim, which guard.Decide may refuse.
var shimmed = []string{"tmux", "gh", "git", "scp", "rsync", "sftp", "ssh"}

// shims puts ak's shims in ~/.agentkit/bin, and returns that folder: in a folder of its own the
// body with a link beside it to the program a seat runs (config.Live), which a later opening
// points at its own, and in bin one link to the body for each tool.  A link an older install left
// at a checkout since moved, or one at another tool, is replaced, as Python's guard.install_shim
// replaces it.
func shims() (string, error) {
	dir, own := filepath.Join(config.Home(), "bin"), filepath.Join(config.Home(), "shim")
	body := filepath.Join(own, "shim")
	program, err := config.Live()
	if err != nil {
		return "", err
	}
	for _, folder := range []string{dir, own} {
		if err := os.MkdirAll(folder, 0o777); err != nil {
			return "", err
		}
	}
	tmp := aside(body)
	if err := os.WriteFile(tmp, shimBody, 0o777); err != nil {
		return "", err
	}
	if err := os.Rename(tmp, body); err != nil {
		return "", err
	}
	if err := link(program, filepath.Join(own, "ak")); err != nil {
		return "", err
	}
	for _, name := range shimmed {
		if err := link(body, filepath.Join(dir, name)); err != nil {
			return "", err
		}
	}
	return dir, nil
}

// link makes path lead to target, whatever it led to before.
func link(target, path string) error {
	at, err := filepath.EvalSymlinks(path)
	if want, _ := filepath.EvalSymlinks(target); err == nil && at == want {
		return nil
	}
	tmp := aside(path)
	if err := os.Symlink(target, tmp); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// aside is where a file is made whole before it lands at path.
func aside(path string) string {
	return filepath.Join(filepath.Dir(path), fmt.Sprintf(".%s.%d", filepath.Base(path), os.Getpid()))
}
