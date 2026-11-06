package notify

import (
	"io"

	"agentkit/internal/run"
)

// Remind pages the owner once per key about what, `Claude II login`, its card a seat's question's
// with what in the seat's place and the outbox keeping text, the whole sentence, as Python's
// notify.page asks for a page nothing owes: one not out yet that was queued before the ak running
// now was installed is dropped unsent, as Page's is not, and said so through log.
func Remind(key, what, text string, log func(string), errOut io.Writer) error {
	page, err := payload(what)
	if err != nil {
		return err
	}
	_, err = queuePage(key, text, page, func(event *run.Object) (bool, error) {
		if number(event, "created_at") >= installedAt() {
			return false, nil
		}
		if err := dropHistory(event); err != nil {
			return true, err
		}
		log("notification " + event.Str("id") + " dropped unsent: queued before the agentkit running now was installed")
		return true, nil
	}, errOut)
	return err
}
