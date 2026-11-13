// Rulebook news belongs to the prompt hook: what changed since the launch or last handover,
// its inline delivery or pending file, and the acknowledgement and compaction that change what
// the conversation holds. Current and Update use the launch renderer and Python-locked record writer.
package hooks

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/fetch"
	"agentkit/internal/gitcall"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// Rulebooks shares the launch's renderer and record writer, and the runs a prompt carries
// (handback.Riding), without depending on seat launchers, whose adapters also install hooks.
type Rulebooks struct {
	Current func(string) (string, error)
	Update  func(string, func(*run.Object) bool) error
	Riding  func(string) (func() string, error)
}

type RulebookRefusal string

func (r RulebookRefusal) Error() string { return string(r) }

// RulebookDigest is the digest recorded at launch and each handover.
func RulebookDigest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

const (
	// ackWords stand between a change's file and the command only that file gives.
	ackWords     = "Once you have read all of the above, run this to say so:"
	changedWords = "Your rulebook changed: the diff below takes the one you hold to your current one, and where " +
		"your current rulebook differs from the one you were opened with, it wins."
	wholeWords = "Your current rulebook follows, whole: where it differs from the one you were opened with, it wins."
)

// PromptNews decides the context a seat's prompt carries (orch.prompt_news), and tell writes what
// it is told and says it, "" for none: only for its own conversation on a harness taking context,
// the runs riding on it, the questions an owner's prompt may answer and the Mac files pasted into
// it, then its rulebook's news.  `said` is the owner's words, nil for a prompt that is not theirs.
// The rulebook is decided last, as it is held from its hand-over on, so nothing may fail after it.
// False for known, with nothing written, where Go cannot tell its runs as Python does.
func (books Rulebooks) PromptNews(launched, conversation string, said *string) (tell func() string, known bool) {
	name, record, kind := owned(launched, conversation)
	if record == nil || !harness.TakesContext(kind) {
		return func() string { return "" }, true
	}
	riding := func() string { return "" }
	if said != nil {
		var err error
		if riding, err = books.Riding(name); err != nil {
			return nil, false
		}
	}
	return func() string {
		besides := ""
		if said != nil {
			besides = paragraphs(riding(), notify.AnswerContext(name, *said), fetch.Pasted(*said))
		}
		whole := func(news string) string { return paragraphs(besides, news) }
		return whole(books.rulebookNews(name, kind, record, conversation, whole))
	}, true
}

// paragraphs is the parts that say anything, a blank line apart.
func paragraphs(parts ...string) string {
	return strings.Join(slices.DeleteFunc(parts, func(part string) bool { return part == "" }), "\n\n")
}

// RulebookCompacted is a compaction of the seat's own conversation (orch.rulebook_compacted): it
// keeps its launch's rulebook, in the system prompt, and drops what it read since, so its next
// prompt is told what changed since that launch.
func (books Rulebooks) RulebookCompacted(launched, conversation string) {
	if name, record, _ := owned(launched, conversation); record != nil {
		books.setRecord(name, field{"rulebook_read", nil}, field{"rulebook_told", nil})
	}
}

// owned is the seat's name now, its record and its harness where that conversation is its own;
// a nil record otherwise, a harness whose evidence Go does not read yet among them.
func owned(launched, conversation string) (string, *run.Object, string) {
	name, _, err := config.ResolveSession(launched)
	if err != nil {
		return "", nil, ""
	}
	record, _ := run.ReadJSON(ownFile("session", name))
	kind := config.SeatHarness(name)
	if record == nil {
		return name, nil, kind
	}
	if own, _ := harness.Owns(kind, record, conversation); !own {
		return name, nil, kind
	}
	return name, record, kind
}

// rulebookNews is what that prompt is told of the rules (orch.rulebook_news), "" where its
// conversation holds the current ones.  Handing them over records them as held; where the record
// cannot be written nothing is handed over, and the next prompt tries again.
func (books Rulebooks) rulebookNews(name, kind string, record *run.Object, conversation string, whole func(string) string) string {
	text, err := books.Current(name)
	sha := RulebookDigest([]byte(text))
	if err != nil || sha == heldSHA(record, conversation) {
		return ""
	}
	HandTaskTemplate() // the numbers its rulebook now says may be new
	news := wholeWords + "\n\n" + text
	if change := rulebookChange(name, record, conversation, text); change != "" {
		news = changedWords + "\n\n" + change
	}
	fits := func(part string) bool { return harness.ContextFits(kind, whole(part)) }
	told := record.Dict("rulebook_told")
	if told == nil || told.Str("conversation") != conversation || told.Str("sha") != sha {
		if fits(news) {
			read := run.NewObject()
			read.Set("conversation", conversation)
			read.Set("sha", sha)
			if books.setRecord(name, field{"rulebook_read", read}) != nil {
				return ""
			}
			replace(ownFile("held", name), []byte(text)) // what a later change is told against; failed, it is told whole
			return news
		}
		told = nil
	}
	return books.rulebookPointer(name, told, conversation, sha, news, fits)
}

// rulebookPointer is what a prompt carries in place of news too long for it, or for a prompt
// before it (orch.rulebook_pointer): the seat's `change` file, holding the news and ending with
// the command only that file gives, so running it says the conversation read it to its end.
// Every prompt names the file again until then, with the same code while the rules stay the same.
// One whose other context leaves no room even for this names nothing, since more would cut that
// context off, and neither does one whose record or file cannot be written.
func (books Rulebooks) rulebookPointer(name string, told *run.Object, conversation, sha, news string, fits func(string) bool) string {
	path := ownFile("change", name)
	pointer := "Read all of " + path + "; run its last line."
	if !fits(pointer) {
		return ""
	}
	if told == nil {
		code := make([]byte, 6)
		rand.Read(code)
		told = run.NewObject()
		told.Set("conversation", conversation)
		told.Set("sha", sha)
		told.Set("code", hex.EncodeToString(code))
		if books.setRecord(name, field{"rulebook_told", told}) != nil {
			return ""
		}
	}
	if replace(path, fmt.Appendf(nil, "%s\n\n%s\n\nak orch rules %s\n", strings.TrimRightFunc(news, config.Space), ackWords, told.Str("code"))) != nil {
		return ""
	}
	return pointer
}

// RulebookRead is the seat's conversation saying it read the file its prompt named, by the code
// that file ended with (orch.rulebook_ack): that conversation and those rules are held from here
// on.  False for known where Go does not read that harness's evidence of its conversation yet.
func (books Rulebooks) RulebookRead(launched, code string) (known bool, err error) {
	known = true
	err = notify.Held(context.Background(), launched, func(current string) error {
		record, err := run.ReadJSON(ownFile("session", current))
		if errors.Is(err, run.ErrLoneSurrogate) {
			known = false
			return nil
		}
		var told *run.Object
		if record != nil {
			told = record.Dict("rulebook_told")
		}
		if code == "" || told == nil || told.Str("code") != code {
			return RulebookRefusal("that is not the code the seat's latest prompt gave; read the rulebook that prompt names and run the code it gives")
		}
		own, read := harness.Owns(config.SeatHarness(current), record, told.Str("conversation"))
		if !read {
			known = false
			return nil
		}
		if !own {
			return RulebookRefusal(current + "'s conversation is not the one that code was given to")
		}
		text, err := books.Current(current)
		if err != nil {
			return err
		}
		if told.Str("sha") != RulebookDigest([]byte(text)) {
			return RulebookRefusal("the rules changed since that prompt; the next one names them")
		}
		replace(ownFile("held", current), []byte(text)) // what a later change is told against; failed, it is told whole
		held := run.NewObject()
		held.Set("conversation", told.Str("conversation"))
		held.Set("sha", told.Str("sha"))
		return books.setRecord(current, field{"rulebook_read", held}, field{"rulebook_told", nil})
	})
	return known, err
}

// heldSHA is the digest of the rulebook that conversation holds: the one it was last handed, else
// its launch's, which is in every conversation's system prompt.
func heldSHA(record *run.Object, conversation string) string {
	if read := record.Dict("rulebook_read"); read != nil && read.Str("conversation") == conversation {
		return read.Str("sha")
	}
	return record.Str("rulebook_sha")
}

// rulebookChange is what changed from the rulebook that conversation holds to text, or "" where
// ak no longer has the one it holds.  Any copy will do, under any name the seat had, since a
// rename leaves some behind: the rules last handed, those a conversation said it read before
// prompts carried them, or its launch's.
func rulebookChange(name string, record *run.Object, conversation, text string) string {
	holds := heldSHA(record, conversation)
	for _, each := range plan.Names(name) {
		for _, kind := range []string{"held", "rules", "rulebook"} {
			data, err := os.ReadFile(ownFile(kind, each))
			if err == nil && len(data) > 0 && RulebookDigest(data) == holds {
				return unifiedDiff(keepLines(gitcall.Decoded(string(data))), keepLines(text), "the rulebook you hold", "your current rulebook", 1)
			}
		}
	}
	return ""
}

// HandTaskTemplate puts templates/task.md at this host's numbers beside the seats' rulebooks
// (orch.hand_task_template).  A seat that cannot get it still has its rules, so a failed write
// stops nothing, and the next changed rulebook tries again.
func HandTaskTemplate() {
	written, err := os.ReadFile(filepath.Join(config.Repo(), "templates", "task.md"))
	if err == nil && os.MkdirAll(filepath.Join(config.Home(), "state"), 0o777) == nil {
		replace(filepath.Join(config.Home(), "state", "task-template.md"), []byte(config.InForce(task.Text(written))))
	}
}

// setRecord sets fields in the seat's record, removing those whose value is nil, under the
// record's lock (config.update_session); an error where no record of that name takes them.
func (books Rulebooks) setRecord(name string, fields ...field) error {
	found := false
	err := books.Update(name, func(data *run.Object) bool {
		found = true
		for _, f := range fields {
			if f.value == nil {
				data.Delete(f.key)
			} else {
				data.Set(f.key, f.value)
			}
		}
		return true
	})
	if err == nil && !found {
		return fmt.Errorf("no record of %s", name)
	}
	return err
}

func ownFile(kind, name string) string {
	return filepath.Join(config.Home(), "state", config.SeatFileNames(name)[kind])
}

type field struct {
	key   string
	value any
}

// replace publishes a whole file as Python's orch.replace_file does.
func replace(path string, data []byte) error {
	tmp := fmt.Sprintf("%s.%d.tmp", path, os.Getpid())
	defer os.Remove(tmp)
	if err := os.WriteFile(tmp, data, 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
