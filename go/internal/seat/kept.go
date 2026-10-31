package seat

import (
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// The questions a seat keeps back for the end of the turn it asks them in live in its seat
// file's `unasked` (watch.keep), read and marked here alone, as `ak notify needs` will keep one.

// also is what a notice puts between the questions it asks (notify.ALSO).
const also = " Also: "

func seatFile(name string) string {
	return filepath.Join(config.Home(), "state", "seat-"+config.Fold(name)+".json")
}

// Kept is whether the seat keeps any question back.
func Kept(name string) bool {
	data, _ := run.ReadJSON(seatFile(name))
	return data != nil && data.Dict("unasked") != nil
}

// TurnEnded writes down that the turn the seat kept its questions back in has ended, on each
// of them that holds no end already (watch.turn_ended), so it is on record before its harness
// takes the next prompt.
func TurnEnded(name string) error {
	if !Kept(name) {
		return nil // nothing kept: a stop writes nothing
	}
	path, ended := seatFile(name), run.Float(seconds(time.Now()))
	return put(path, strings.TrimSuffix(path, ".json")+".lock", run.Line, false, func(data *run.Object) bool {
		unasked := data.Dict("unasked")
		if unasked == nil {
			return false
		}
		// each question in the order kept, an older install's single one among them, as
		// watch.questions_kept reads it: its words, its card's id, and its moments
		listed, ok := unasked.Get("questions").([]any)
		if !ok {
			listed = []any{unasked}
		}
		var kept []any
		var texts []string
		for _, each := range listed {
			asked, _ := each.(*run.Object)
			if asked == nil {
				continue
			}
			text, ok := asked.Get("text").(string)
			if !ok {
				continue
			}
			question := run.NewObject()
			question.Set("ended", ended)
			question.Set("text", text)
			question.Set("id", asked.Get("id"))
			for _, key := range []string{"at", "ended"} {
				if _, ok := asked.Num(key); ok {
					question.Set(key, asked.Get(key))
				}
			}
			kept, texts = append(kept, question), append(texts, text)
		}
		if len(kept) == 0 {
			return false
		}
		fresh := run.NewObject()
		fresh.Set("text", strings.Join(texts, also))
		fresh.Set("questions", kept)
		return set([]field{{"unasked", fresh}}, field{"session", name})(data)
	})
}
