package install

import (
	"errors"
	"fmt"
	"os"
	"time"
	"unicode/utf8"

	"agentkit/internal/task"
)

// text is a file as Python's read_text reads it: UTF-8, every line ending a newline.
func text(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err == nil && !utf8.Valid(data) {
		err = fmt.Errorf("%s is not UTF-8", path)
	}
	return task.Text(data), err
}

// backUp copies a file of the owner's to `<file>.bak-<today>` beside it, its mode and time
// kept, as shutil.copy2 does in install.sh, before install changes it; it is the copy's path.
func backUp(path string) (string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	backup := path + ".bak-" + time.Now().Format("20060102")
	if err := os.WriteFile(backup, data, info.Mode().Perm()); err != nil {
		return "", err
	}
	return backup, errors.Join(os.Chmod(backup, info.Mode().Perm()), os.Chtimes(backup, time.Time{}, info.ModTime()))
}

// replace puts text in a file's place whole, so whoever reads it meets the old file or the new,
// never half: written first as `<file>.ak-tmp` beside it, made afresh so that its mode is perm
// as the umask leaves it.
func replace(path, text string, perm os.FileMode) error {
	tmp := path + ".ak-tmp"
	os.Remove(tmp)
	if err := os.WriteFile(tmp, []byte(text), perm); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
