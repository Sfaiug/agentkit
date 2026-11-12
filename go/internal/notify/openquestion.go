package notify

import "context"

// OpenedQuestion records a question's first interactive open without answering it.
func OpenedQuestion(name string, capture func(string) string) (bool, error) {
	carried := false
	err := Held(context.Background(), name, func(current string) error {
		notice := open(current)
		if !OwnerQuestion(notice) {
			return nil
		}
		at, known := finite(notice.Get("time"))
		if !known {
			return nil
		}
		carried = true
		if notice.Get("opened_at") != nil {
			return nil
		}
		pane := capture(current)
		notice.Set("opened_at", max(clock(), at))
		notice.Set("opened_pane", pane)
		return writeNotice(current, notice)
	})
	return carried, err
}
