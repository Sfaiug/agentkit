package harness

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func init() {
	plugins["muse"] = plugin{identity: museIdentity, auth: museAuth, usageTaken: museUsageTaken, usageRecorded: museUsageRecorded, recordTurn: museRecordTurn,
		seats: true, looks: true, record: museRecord, keys: []string{"muse_launch"}, kept: museKept, forget: receiptGone("muse"),
		opens: true, interactive: museInteractive, seatWords: museSeatWords, owned: museConversation, launched: museLaunched, retire: receiptRetired("muse"),
		card: museCard, said: museSaid, typed: museTyping, answered: museAnswered, answer: museAnswer, resumable: museResumable, tokens: museTokens,
		// its launch receipt reads as no session where Python's strict read raises: a session
		// that is not UTF-8, or an `earlier` Python's set() refuses
		loose: true,
		hookEvent: func(event *run.Object, _ io.Writer, _ func(string) (string, error), _ func(string)) (*run.Object, int) {
			return museHookEvent(event), 0
		}}
}

// museIdentity is Muse's release label plus the build its launcher installed, which the launcher
// records beside itself: the label alone cannot tell a frozen installed release from the next.
func museIdentity(text string, argv []string) (string, bool) {
	launcher := config.Resolve(Binary(argv[0]))
	data, err := os.ReadFile(filepath.Join(filepath.Dir(launcher), ".muse-version"))
	if err != nil {
		return text, true
	}
	if !utf8.Valid(data) {
		return "", false
	}
	build := strings.TrimFunc(string(data), config.Space)
	if build == "" || strings.Contains(text, build) {
		return text, true
	}
	return text + " (installed build " + build + ")", true
}
