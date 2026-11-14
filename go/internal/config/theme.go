package config

import (
	"os"
	"path/filepath"
	"sync"
	"time"
)

// themeRead is config.toml's stat as Theme last read it, and the word its `theme` named.
var themeRead struct {
	sync.Mutex
	path  string
	moved time.Time
	size  int64
	named string
}

// Theme is the word config.toml's `theme` names, `white` or `black` where the owner chose one on
// `c`, as the file is now, else "" (Python's config.theme): every draw asks, so nothing that draws
// for hours, a seat's bar among them, keeps one chosen before.  Read again only once the file moved.
func Theme() string {
	path := filepath.Join(Home(), "config.toml")
	seen, err := os.Stat(path)
	if err != nil {
		return ""
	}
	themeRead.Lock()
	defer themeRead.Unlock()
	if path != themeRead.path || !seen.ModTime().Equal(themeRead.moved) || seen.Size() != themeRead.size {
		themeRead.path, themeRead.moved, themeRead.size, themeRead.named = path, seen.ModTime(), seen.Size(), ""
		if root, err := fileTable(); err == nil {
			themeRead.named, _ = root.get("theme").(string)
		}
	}
	return themeRead.named
}

// SaveTheme writes config.toml as Python's config.save does with `theme` set to `name`, the theme
// marked on `c`.  `keep` is as RememberDefaults's.
func SaveTheme(name string, keep func() error) error {
	return saveConfig(fileTable, func(root *table) error {
		root.put("theme", name)
		return nil
	}, keep)
}
