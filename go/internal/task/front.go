package task

import (
	"errors"
	"os"
	"unicode/utf8"
)

// Front is a task file's front matter, each key as it last says it, or the sentence ak refuses
// the file with, as Python's front_matter reads it.
func Front(path string) (map[string]string, error) {
	data, err := os.ReadFile(path)
	if err == nil && !utf8.Valid(data) {
		err = errors.New(path + ": invalid UTF-8")
	}
	if err != nil {
		return nil, err
	}
	meta, _, err := frontMatter(path, Text(data))
	return meta, err
}
