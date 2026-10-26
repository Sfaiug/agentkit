package plan

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
)

// group is how to stop cmd: Windows runs ak in WSL2 first, where a check's children go with it.
func group(cmd *exec.Cmd) (stop func()) {
	return func() { cmd.Process.Kill() }
}

// lock opens path and takes no lock: no Python ak writes a plan beside native Windows ak.
func lock(_ context.Context, path string) (*os.File, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	return os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
}
