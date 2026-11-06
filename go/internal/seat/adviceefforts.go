package seat

import (
	"errors"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const adviceBackupPrefix = ".advice-"

// savingEfforts stages every legacy record before replacing any, and keeps originals and
// Python's locks, which `take` takes, until config.toml lands. A failed save restores them.
func savingEfforts(inFile []string, models map[string]config.Model, offered []string, take func(locks []string) ([]*os.File, error), save func(func() error) error) (err error) {
	type staged struct {
		path, tmp, backup string
		written, landed   bool
	}
	var records []*staged
	var held []*os.File
	defer func() {
		for i := len(records) - 1; i >= 0; i-- {
			record := records[i]
			if err != nil && record.landed {
				if undo := os.Rename(record.backup, record.path); undo != nil {
					err = errors.Join(err, undo)
					continue // keep the original if the filesystem refuses its restoration
				}
			}
			os.Remove(record.backup)
			if record.written {
				os.Remove(record.tmp)
			}
		}
		for _, file := range held {
			file.Close()
		}
	}()
	return save(func() error {
		paths := config.SeatRecords("session")
		locks := make([]string, len(paths))
		for i, path := range paths {
			locks[i] = filepath.Join(filepath.Dir(path), "."+strings.TrimSuffix(filepath.Base(path), ".json")+".lock")
		}
		var err error
		if held, err = take(locks); err != nil {
			return err
		}
		for _, path := range paths {
			before, err := os.ReadFile(path)
			if err != nil {
				if os.IsNotExist(err) {
					continue
				}
				return err
			}
			value, err := run.Decode(before)
			if err != nil {
				if errors.Is(err, run.ErrLoneSurrogate) {
					return err
				}
				continue
			}
			data, _ := value.(*run.Object)
			if data == nil || data.Has(config.Renamed) {
				continue
			}
			read, ok := readsAsSeat(data, inFile, models, offered)
			if !ok {
				continue
			}
			name, _ := config.SeatFileOwner(filepath.Base(path))
			ownEfforts(read, name, models)
			if run.Equal(read.Get("efforts"), data.Get("efforts")) {
				continue
			}
			info, err := os.Stat(path)
			if err != nil {
				return err
			}
			backup, err := os.CreateTemp(filepath.Dir(path), adviceBackupPrefix)
			if err != nil {
				return err
			}
			record := &staged{path: path, tmp: strings.TrimSuffix(path, ".json") + ".tmp", backup: backup.Name()}
			records = append(records, record)
			_, writeErr := backup.Write(before)
			modeErr := backup.Chmod(info.Mode().Perm())
			if err := errors.Join(writeErr, modeErr, backup.Close()); err != nil {
				return err
			}
			data.Set("efforts", read.Get("efforts"))
			if err := os.WriteFile(record.tmp, []byte(run.Encode(data)+"\n"), 0o666); err != nil {
				return err
			}
			record.written = true
		}
		for _, record := range records {
			if err := os.Rename(record.tmp, record.path); err != nil {
				return err
			}
			record.landed = true
		}
		return nil
	})
}

// tryLocks takes each lock while it is free, and the first that is not ends it with
// lock.ErrHeld, returning those taken: a Python rename locks old then new, in either name
// order, so a record's lock is never waited for while another's is held.
func tryLocks(paths []string) ([]*os.File, error) {
	var held []*os.File
	for _, path := range paths {
		file, err := lock.Try(path)
		if err != nil {
			return held, err
		}
		held = append(held, file)
	}
	return held, nil
}
