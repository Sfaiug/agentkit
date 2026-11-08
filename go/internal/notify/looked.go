package notify

import (
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Looked is the word a seat's look published as an Asked, the question's only where the look
// published it as the word's reason: a word Go reads no other way.
func Looked(published func(string) (string, any)) Asked {
	return func(name string, notice *run.Object, _ time.Time) (string, any, bool) {
		word, since := published(name)
		file, _ := readObject(seatFile("seat", name, "json"))
		return word, since, file != nil && looked(file, notice)
	}
}

// looked is whether the seat's look published that question as its word's reason.
func looked(file, notice *run.Object) bool {
	return config.Fold(file.Str("reason")) == config.Fold(notice.Str("text"))
}
