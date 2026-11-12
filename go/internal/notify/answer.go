package notify

import (
	"math"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/transcript"
)

// AnswerContext is the open questions this prompt may answer, each whole and dated, in the order
// asked (notify.answer_context), "" for none.  Read without the notice's lock: a sender holds it
// while typing a prompt and waiting for this hook.
func AnswerContext(name, said string) string {
	notice := Last(name)
	if notice == nil || notice.Get("watcher") == true || akPrompt(name, said, notice) {
		return ""
	}
	dated := notice.Dict("asked_at")
	var context []string
	for _, question := range questions(notice) {
		asked, known := 0.0, false
		if dated != nil {
			asked, known = dated.Num(questionKey(question))
		}
		if !known {
			if asked, known = notice.Num("time"); !known {
				return ""
			}
		}
		stamp := time.Unix(int64(math.Floor(asked)), 0).UTC().Format("2006-01-02 15:04:05 UTC")
		context = append(context, "Asked "+stamp+":\n"+question)
	}
	return "Questions you asked the owner that this prompt may answer:\n\n" + strings.Join(context, "\n\n")
}

// akPrompt is whether the prompt is a line ak typed rather than the owner's answer to the notice
// (notify.ak_prompt): one typed since its question, or the one that put the question to the seat,
// which carries its words and is typed before the question is recorded.
func akPrompt(name, said string, notice *run.Object) bool {
	since, dated := notice.Num("time")
	if !dated || said == "" {
		return false
	}
	asking := false
	for _, question := range questions(notice) {
		asking = asking || strings.Contains(questionKey(said), questionKey(question))
	}
	for sent := range transcript.Entries(filepath.Join(state(), config.SeatFileNames(name)["input"])) {
		at, stamped := sent.Num("at")
		if stamped && at >= 0 && sent.Str("source") != "owner" && sent.Str("text") == said && (asking || at >= since) {
			return true
		}
	}
	return false
}
