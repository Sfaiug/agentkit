package adapters

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	record "agentkit/internal/run"
)

// answered is what the harness's `[prep]` file holds once a seat in this folder has its answers
// there, nothing written, or why the seat must not open on it; no object where the harness has
// no `[prep]`.
func answered(name string) (config.PrepTable, *record.Object, error) {
	folder, err := os.Getwd()
	if err != nil {
		return config.PrepTable{}, nil, err
	}
	// Getwd may answer $PWD, links and all, and the harness trusts where they lead
	prep, ok, err := config.Prep(name, config.Resolve(folder))
	if err != nil || !ok {
		return prep, nil, err
	}
	for _, path := range prep.Reads {
		if _, err := held(path); err != nil {
			return prep, nil, err
		}
	}
	data, err := held(prep.File)
	if err != nil {
		return prep, nil, err
	}
	if prep.Usual != "" {
		// A notice answered once is answered everywhere: only `true`s and the shared objects'
		// entries travel, so a named login keeps its own account, ids, caches, projects and
		// entries.  Nothing does from a file unread.
		if usual, err := held(prep.Usual); err == nil {
			for _, key := range usual.Keys() {
				if usual.Get(key) == true {
					data.Set(key, true)
				}
			}
			for _, key := range prep.Shared {
				entries := usual.Dict(key)
				if entries == nil || len(entries.Keys()) == 0 {
					continue
				}
				own := data.Dict(key)
				if own == nil {
					own = record.NewObject()
				}
				for _, name := range entries.Keys() {
					own.Set(name, entries.Get(name))
				}
				data.Set(key, own)
			}
		}
	}
	for _, answer := range prep.Answers {
		if err := give(data, answer); err != nil {
			return prep, nil, fmt.Errorf("cannot read %s: %w", prep.File, err)
		}
	}
	return prep, data, nil
}

// held is the JSON object at path, an empty one where no file is there.
func held(path string) (*record.Object, error) {
	data, err := record.ReadJSON(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return record.NewObject(), nil
	case err != nil:
		return nil, fmt.Errorf("cannot read %s: %w", path, err)
	case data == nil:
		return nil, fmt.Errorf("cannot read %s: not a JSON object", path)
	}
	return data, nil
}

// give puts the answer in data, making the objects on its way; anything else on its way is
// refused, since replacing it would lose what the owner had.
func give(data *record.Object, answer config.Answer) error {
	last := len(answer.Path) - 1
	for _, key := range answer.Path[:last] {
		if !data.Has(key) {
			data.Set(key, record.NewObject())
		}
		if data = data.Dict(key); data == nil {
			return fmt.Errorf("%s is not a JSON object", key)
		}
	}
	if !answer.Default || !data.Has(answer.Path[last]) {
		data.Set(answer.Path[last], answer.Value)
	}
	return nil
}

// prepare writes the harness's `[prep]` answers for a seat in this folder, on login.
func prepare(name string, login config.Login) error {
	prep, data, err := answered(name)
	if err != nil || data == nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(prep.File), 0o777); err != nil {
		return err
	}
	if err := replace(prep.File, record.Line(data)+"\n"); err != nil {
		return err
	}
	if login.Account == "" {
		return nil
	}
	for _, each := range prep.Links {
		source, target := under(login.Usual, each), under(login.Home, each)
		if _, err := os.Stat(source); err != nil {
			continue
		}
		if _, err := os.Lstat(target); err == nil {
			continue
		}
		// a seat opening beside this one may have just made it
		if err := os.Symlink(source, target); err != nil && !errors.Is(err, fs.ErrExist) {
			return err
		}
	}
	return nil
}

// replace puts text in path whole or not at all, from a temp file no other launch shares, since
// seats open side by side.  An existing file keeps the mode it had; a new one stays as
// CreateTemp made it, 0600.
func replace(path, text string) error {
	temporary, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(temporary.Name())
	_, err = temporary.WriteString(text)
	if closed := temporary.Close(); err == nil {
		err = closed
	}
	if info, statErr := os.Stat(path); err == nil && statErr == nil {
		err = os.Chmod(temporary.Name(), info.Mode().Perm())
	}
	if err == nil {
		err = os.Rename(temporary.Name(), path)
	}
	return err
}
