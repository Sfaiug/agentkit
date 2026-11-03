package config

import (
	"os"
	"path/filepath"
	"strings"
)

// LiveHost is the ssh alias of the live product host a seat may not write to by hand, `live_host`
// in config.toml, "" where the owner named none or that file does not read: ak ships with none.
func LiveHost() string {
	data, err := os.ReadFile(filepath.Join(Home(), "config.toml"))
	if err != nil {
		return ""
	}
	held, err := ReadTOML(string(data))
	if err != nil {
		return ""
	}
	alias, _ := held["live_host"].(string)
	return alias
}

// UnderCode is whether the path is ~/code or inside it: a checkout there is the owner's, never a
// run's to delete nor a seat's to make.  With no home to say, it counts as there.
func UnderCode(path string) bool {
	home := UserHome()
	if home == "" {
		return true
	}
	code, resolved := Resolve(filepath.Join(home, "code")), Resolve(path)
	return resolved == code || strings.HasPrefix(resolved, strings.TrimSuffix(code, string(filepath.Separator))+string(filepath.Separator))
}
