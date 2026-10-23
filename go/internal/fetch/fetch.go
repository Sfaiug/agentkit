// Package fetch resolves local files without starting the Mac bridge.
package fetch

import (
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"unicode"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

func Validate(args []string) string {
	if len(args) == 1 && args[0] == "--serve" {
		return ""
	}
	if len(args) > 0 && args[0] == "--" {
		args = args[1:]
	}
	if len(args) == 0 {
		return commandhelp.Usage("fetch")
	}
	for _, arg := range args {
		if arg == "--serve" {
			return commandhelp.Usage("fetch")
		}
	}
	if raw, ok := os.LookupEnv("AK_FETCH_TIMEOUT"); ok {
		value, err := strconv.ParseFloat(strings.TrimSpace(raw), 64)
		if err != nil || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
			return "AK_FETCH_TIMEOUT must be a finite, non-negative number"
		}
	}
	return ""
}

func normalize(value string) string {
	if _, err := os.Stat(config.Expand(value)); err == nil {
		return config.Expand(value)
	}
	value = strings.TrimSpace(value)
	if len(value) > 1 && value[0] == value[len(value)-1] && (value[0] == '\'' || value[0] == '"') {
		value = value[1 : len(value)-1]
	}
	// Terminal and Finder escape punctuation when a path is dropped into a shell.
	runes := []rune(value)
	var out strings.Builder
	for i := 0; i < len(runes); i++ {
		if runes[i] == '\\' && i+1 < len(runes) && (unicode.IsSpace(runes[i+1]) || strings.ContainsRune("\\'\"()[]{}<>|;&!$`*?#~", runes[i+1])) {
			i++
		}
		out.WriteRune(runes[i])
	}
	return out.String()
}

func Local(args []string) ([]string, bool) {
	if len(args) == 1 && args[0] == "--serve" {
		return nil, false
	}
	if args[0] == "--" {
		args = args[1:]
	}
	paths := make([]string, 0, len(args))
	for _, arg := range args {
		path := normalize(arg)
		if path == "" || strings.ContainsAny(path, "\x00\r\n\t") {
			return nil, false
		}
		path = config.Expand(path)
		if _, err := os.Stat(path); err != nil {
			return nil, false
		}
		absolute, err := filepath.Abs(path)
		if err != nil {
			return nil, false
		}
		paths = append(paths, absolute)
	}
	return paths, true
}
