// Package config checks configuration before a shadow command reaches an operation.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func Home() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".agentkit")
}

func Expand(path string) string {
	if path == "~" || strings.HasPrefix(path, "~/") || strings.HasPrefix(path, "~"+string(filepath.Separator)) {
		home, _ := os.UserHomeDir()
		path = filepath.Join(home, strings.TrimPrefix(path[1:], "/"))
	}
	return filepath.Clean(path)
}

func Absolute(path string) string {
	path, _ = filepath.Abs(Expand(path))
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return resolved
	}
	return path
}

func Check() error {
	path := filepath.Join(Home(), "config.toml")
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("cannot read %s: %w", path, err)
	}
	if err := syntax(string(data)); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	return nil
}
