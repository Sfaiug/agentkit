package seat

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
)

// AnswerWritten is notify.answer_written as the tick's typed answers asks it: a message the owner
// typed into the seat's conversation after what it asked them answers it now; whether it did.
func AnswerWritten(name string) (bool, error) {
	done, _, err := answerWritten(filepath.Join(config.Home(), "state"), name, seconds(time.Now()), 0, false)
	return done, err
}
