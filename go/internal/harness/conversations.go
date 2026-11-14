package harness

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// An End ends a conversation its harness's own way, with whatever that harness keeps of it
// elsewhere, only where ends(those other parts, present) holds right before anything goes, so one
// a seat took up meanwhile stays; safe is whether a path is ours, reached through no link
// (retention.safe).  What its harness's way could not do is the error.
type End func(ends func(parts ...string) bool, safe func(path string) bool) error

// ConversationEnd is how that harness ends the conversation at that path
// (harness.end_conversation), nil where that way is Python's: a harness Go does not end, and
// Antigravity while a home of it keeps conversation_summaries.db, which its plugin writes and Go
// does not.  What cannot be looked at is an error, as a home nobody may search may still keep a
// part of it.
func ConversationEnd(harness, path string) (End, error) {
	switch harness {
	case "claude":
		return claudeEnd(path), nil
	case "antigravity":
		if _, ours, err := antigravityParts(path); !ours || err != nil {
			return nil, err
		}
		return antigravityEnd(path), nil
	case "codex":
		return codexThreadEnd(path), nil
	case "grokbuild":
		return grokEnd(path), nil
	case "muse":
		return museEnd(path), nil
	}
	return nil, nil
}

// claudeEnd is ak's name alone: the transcript it names, while Claude keeps it, is Claude's to end.
func claudeEnd(path string) End {
	return func(ends func(...string) bool, _ func(string) bool) error {
		if !ends() {
			return nil
		}
		return os.Remove(path)
	}
}

// antigravityEnd takes its annotations, implicit and presence files in every home and its brain
// folder, then its .db: a pass cut short finds the .db again.  One a home of which came to keep
// conversation_summaries.db since stays.
func antigravityEnd(path string) End {
	return func(ends func(...string) bool, _ func(string) bool) error {
		parts, ours, err := antigravityParts(path)
		if !ours || err != nil || !ends(parts...) {
			return err
		}
		for _, part := range parts { // ends refused any reached through a link
			if err := os.RemoveAll(part); err != nil {
				return err
			}
		}
		return os.Remove(path)
	}
}

// antigravityParts is what Antigravity keeps of that conversation besides its .db, those parts
// present; false while a home of it keeps conversation_summaries.db.
func antigravityParts(path string) ([]string, bool, error) {
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
