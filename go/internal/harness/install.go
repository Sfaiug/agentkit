package harness

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// Yolo merges ak's yolo defaults into the harness's own settings, as install.sh's yolo defaults
// do: a seat, or anything started by hand, never asks before it acts and never updates itself,
// everything else the owner set kept.  The adapters pass their own bypass flags to every run;
// this is for the rest.  nil for a harness whose flags are the whole story.
func Yolo(name string, out io.Writer) error {
	if hook := plugins[name].yolo; hook != nil {
		return hook(out)
	}
	return nil
}

// Rulebook is the harness's own user-wide rulebook in HOME, which an older install linked ak's
// rules over; "" for none.
func Rulebook(name string) string {
	if own := plugins[name].rulebook; own != "" {
		return filepath.Join(config.UserHome(), own)
	}
	return ""
}

// settings is a harness's settings file as its yolo merge reads it, its folder made first.
func settings(path string) (string, bool, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return "", false, err
	}
	text, found, err := readConfig(path)
	if errors.Is(err, ErrPython) {
		// Python's install leaves such a file as it is too, said
		err = fmt.Errorf("%s is not UTF-8", path)
	}
	return text, found, err
}
