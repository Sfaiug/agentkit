package tick

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
)

// keepConversations is Python's watch.keep_conversations: each conversation of every seat, those it
// left included (notify.Listed), given ak's own name for its file where its harness keeps one
// (harness.Keep), none of them read; errLeft where Go does not list a seat's as Python does.
func keepConversations() error {
	for _, path := range config.SeatFiles() {
		name, _ := config.SeatFileOwner(filepath.Base(path))
		_, had, err := notify.Listed(name, false)
		if err != nil {
			return errLeft
		}
		for _, each := range had {
			harness.Keep(each.Harness, each.Record)
		}
	}
	return nil
}
