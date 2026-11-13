package harness

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// ConversationParts is what a harness keeps of that conversation besides its own file or folder,
// those parts present, to go before it so a pass cut short finds the conversation again; false
// where ending that harness's conversation is Python's, as its plugin's end_conversation writes
// a database Go's standard library does not.  Claude's is Go's, and none: its end is ak's name
// alone, the transcript Claude's to end.  Antigravity's is Go's while no home of it keeps
// conversation_summaries.db: its annotations, implicit and presence files in every home and its
// brain folder.  What cannot be looked at is an error, as a home nobody may search may still
// keep a part of it.
func ConversationParts(harness, path string) ([]string, bool, error) {
	if harness == "claude" {
		return nil, true, nil
	}
	if harness != "antigravity" {
		return nil, false, nil
	}
	home := filepath.Dir(filepath.Dir(path))
	others, _ := filepath.Glob(filepath.Join(filepath.Dir(home), filepath.Base(home)+"-*"))
	homes := append([]string{home}, others...)
	stem := strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
	var named []string
	for _, each := range homes {
		if held, err := there(filepath.Join(each, "conversation_summaries.db")); held || err != nil {
			return nil, false, err
		}
		named = append(named, filepath.Join(each, "annotations", stem+".pbtxt"), filepath.Join(each, "implicit", stem+".pb"),
			filepath.Join(each, "presence", stem+".lock"))
	}
	var parts []string
	for _, part := range append(named, filepath.Join(home, "brain", stem)) {
		held, err := there(part)
		if err != nil {
			return nil, false, err
		}
		if held {
			parts = append(parts, part)
		}
	}
	return parts, true, nil
}

// there is whether something is at the path, link or not.
func there(path string) (bool, error) {
	_, err := os.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	return err == nil, err
}
