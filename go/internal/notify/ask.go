package notify

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lifecycle"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// cardWait is how long the owner out of the seat holds back its card, in seconds.
const cardWait = 60

// also joins the questions one notice asks.
const also = " Also: "

type field struct {
	key   string
	value any
}

// Ask asks the owner a seat's question for it, by name, as Python's shaped does: kept as the
// seat's notice, joined to the questions still standing there, and paged at once, the card of
// its episode going out once.  It answers the exit code and whether Go decided it at all: where
// the seat's word hangs on a record Go does not read yet, or a file it reads is one Go cannot
// read as Python does, it records nothing and leaves the ask to Python.
func Ask(name string, record map[string]any, question string, out, errOut io.Writer) (int, bool) {
	_, ownerErr := secret("AGENTKIT_DISCORD_USER_ID", "discord_user_id")
	if _, webhookErr := webhook(false, io.Discard); ownerErr != nil || webhookErr != nil {
		return 0, false
	}
	var attached bool
	var held *os.File
	for {
		// read first without the lock, so that an ask left to Python makes no file at all
		if _, known := standing(name, record); !known || config.EnsureDirs() != nil {
			return 0, false
		}
		var err error
		if held, err = lock.Wait(context.Background(), seatFile("notify", name, "lock")); err != nil {
			return 0, false
		}
		now, renamed, err := config.ResolveSession(name)
		if err == nil && now == name {
			// and again under it: an owner's close, which Python writes holding this lock, or an
			// attach may have come while this ask waited
			var known bool
			if attached, known = standing(name, renamed); known {
				break
			}
		}
		held.Close()
		if err != nil || now == name {
			return 0, false
		}
		name, record = now, renamed // a rename won while this ask waited for the lock
	}
	defer held.Close()
	previous, err := run.ReadJSON(seatFile("notify", name, "json"))
	unkept := errors.Is(err, run.ErrLoneSurrogate)
	if previous != nil {
		if _, asks := previous.Get("text").(string); previous.Str("kind") != "needs" || !asks {
			previous = nil // no question of the seat's: what Python's last reads as none
		}
	}
	notice, readable := said(name, question, previous)
	card, cardErr := readObject(seatFile("card", name, "json"))
	if errors.Is(cardErr, errNotObject) {
		card, cardErr = nil, nil
	}
	if card == nil {
		card = run.NewObject()
	}
	_, eventErr := readEvent(cardKey(card.Get("episode")))
	if unkept || !readable || cardErr != nil || card.Str("word") == "needs you" && eventErr != nil {
		return 0, false
	}
	if err := writeNotice(name, notice); err != nil {
		fmt.Fprintf(errOut, "notify: record could not be persisted (%s); retry required\n", failed(err))
		return 1, true
	}
	// Python ends the seat's `ak wait` under this lock: a seat Go knows, with no watch record,
	// waits on nothing
	if wait, err := lock.Wait(context.Background(), seatFile("seat", name, "lock")); err == nil {
		wait.Close()
	}
	code, err := page(name, card, notice, attached, errOut)
	if err != nil {
		fmt.Fprintf(out, "WARN card transition for %s failed (%s); retry required\n", name, failed(err))
		return 1, true
	}
	return code, true
}

// standing is whether a client is attached to the seat, and whether Go knows its word, which
// Python's session_state decides: `needs you`, the question asked now standing, for a name no
// record and no tmux session holds, and for a seat ak's server holds alive with no turn, run or
// watch record, on a harness whose chat Python does not read for the question (none `nudge`s).
func standing(name string, record map[string]any) (attached, known bool) {
	exists := func(path string) bool { _, err := os.Lstat(path); return !errors.Is(err, fs.ErrNotExist) }
	if path, _ := config.SessionPath(name); record == nil && exists(path) {
		return false, false // a record that is no object
	}
	for _, kind := range []string{"seat", "hook", "stop"} {
		if exists(seatFile(kind, name, "json")) {
			return false, false
		}
	}
	if exists(filepath.Join(state(), "watch.json")) {
		return false, false
	}
	if runs, err := os.ReadDir(run.Runs()); len(runs) > 0 || err != nil && !errors.Is(err, fs.ErrNotExist) {
		return false, false
	}
	if record != nil {
		orchestrator, _ := record["orchestrator"].(string)
		model, err := config.ModelNamed(orchestrator)
		if err != nil {
			return false, false
		}
		if nudged, err := lifecycle.Nudged(model.Harness); err != nil || nudged {
			return false, false
		}
	}
	panes, _ := tmux.Ask(tmux.Own(), "list-panes", "-a", "-F", "#{session_attached}\t#{pane_dead}\t#{session_name}")
	found, alive := false, false
	for _, line := range config.SplitLines(panes) {
		clients, rest, _ := strings.Cut(line, "\t")
		dead, session, _ := strings.Cut(rest, "\t")
		if session != tmux.Control && config.Fold(session) == name {
			found, alive, attached = true, alive || dead != "1", clients != "" && clients != "0"
		}
	}
	if found {
		return attached, record != nil && alive
	}
	legacy := slices.ContainsFunc(tmux.Sessions(tmux.Default), func(session tmux.Session) bool {
		return session.Mark == "1" && config.Fold(session.Name) == name
	})
	return false, record == nil && !legacy
}

// said is the seat's notice once it asks the question, as Python's _said records it, and
// whether Go reads the notice it replaces as Python does: the question joins those still standing
// unanswered, each once, in the order asked, and one asked again keeps its first words and is
// dated anew.  A newer notice carries the answer to the one it replaced.
func said(name, question string, previous *run.Object) (*run.Object, bool) {
	var standing []string
	dated, dates, ids := run.NewObject(), run.NewObject(), run.NewObject()
	if previous != nil && previous.Get("watcher") != true && !resolved(previous) {
		standing = questions(previous)
		var read [3]bool
		dated, read[0] = copied(previous, "asked_at", run.NewObject())
		dates, read[1] = copied(previous, "question_times", dated)
		ids, read[2] = copied(previous, "question_ids", run.NewObject())
		if read != [3]bool{true, true, true} {
			return nil, false
		}
	}
	asked, key := standing, questionKey(question)
	if !slices.ContainsFunc(standing, func(q string) bool { return questionKey(q) == key }) {
		asked = append(slices.Clone(standing), question)
	}
	now := run.Float(clock())
	dated.Set(key, now)
	dates.Set(key, now)
	ids.Set(key, nil)
	notice := run.NewObject()
	for _, f := range []field{{"session", name}, {"kind", "needs"}, {"text", strings.Join(asked, also)}, {"time", now},
		{"source", nil}, {"watcher", false}} {
		notice.Set(f.key, f.value)
	}
	if len(asked) > 1 {
		listed := make([]any, len(asked))
		for i, q := range asked {
			listed[i] = q
		}
		notice.Set("questions", listed)
	}
	notice.Set("asked_at", dated)
	notice.Set("question_times", dates)
	notice.Set("question_ids", ids)
	if previous != nil {
		earlier := "earlier_answer_at"
		if previous.Has("answered_at") {
			earlier = "answered_at"
		}
		if previous.Truthy(earlier) {
			notice.Set("earlier_answer_at", previous.Get(earlier))
		}
	}
	return notice, true
}

// copied is a copy of the notice's map under key, or of `or` for none, as Python's
// dict(notice.get(key) or ...) makes it; false for a value it would fail on or read otherwise.
func copied(notice *run.Object, key string, or *run.Object) (*run.Object, bool) {
	if !notice.Truthy(key) {
		return or.Copy(), true
	}
	if object := notice.Dict(key); object != nil {
		return object.Copy(), true
	}
	return nil, false
}

// page is Python's transition for the question just asked, the seat's word `needs you`: its card
// begins the episode now unless that episode's card went out, and goes now unless it went, an
// answer came after it, a client is attached or left within the minute, or the episode predates
// this install.  A seat the owner closed is never paged either, which no seat Go knows is.
func page(name string, card, notice *run.Object, attached bool, errOut io.Writer) (int, error) {
	asked, _ := notice.Num("time")
	stamp := clock()
	if card.Str("word") != "needs you" {
		card = episode(card, asked, asked)
	}
	if !card.Truthy("sent") {
		card.Set("began", run.Float(stamp)) // `ak notify` begins its episode at the command
		if err := writeCard(name, card); err != nil {
			return 0, err
		}
	}
	since, _ := card.Num("since")
	if answered := max(number(card, "answered_at"), number(notice, "earlier_answer_at")); answered > since {
		// the answer ended the episode, its card left as it went: this question is one of its own,
		// which the tick pages once its minute has passed
		if err := retire(card); err != nil {
			return 0, err
		}
		return 0, writeCard(name, episode(card, max(stamp, asked), max(answered, asked)))
	}
	if card.Truthy("sent") {
		return 0, nil
	}
	if card.Truthy("present") != attached {
		card.Set("present", attached)
		card.Set("left", run.Float(stamp))
		if err := writeCard(name, card); err != nil {
			return 0, err
		}
	}
	// the owner's last key in the seat holds nothing back: an ask waits for no earlier key
	if attached || stamp-number(card, "left") < cardWait || number(card, "began") < installedAt() {
		return 0, nil
	}
	return sendCard(name, card, notice, errOut)
}

// episode is a new needs-you card, unsent, the work an older one covered kept.
func episode(old *run.Object, since, began float64) *run.Object {
	id := make([]byte, 16)
	rand.Read(id)
	card := run.NewObject()
	for _, f := range []field{{"word", "needs you"}, {"since", run.Float(since)}, {"began", run.Float(began)},
		{"episode", hex.EncodeToString(id)}, {"sent", false}} {
		card.Set(f.key, f.value)
	}
	if old.Truthy("completed") {
		card.Set("completed", old.Get("completed"))
	}
	return card
}

// retire ends a needs-you episode: its card, if Discord has not taken it yet, never goes out.
func retire(card *run.Object) error {
	held, err := holdOutbox()
	if err != nil {
		return err
	}
	defer held.Close()
	event, err := readEvent(cardKey(card.Get("episode")))
	if err != nil || event == nil || event.Str("status") == "delivered" || event.Str("status") == "disabled" {
		return err
	}
	event.Set("status", "disabled")
	event.Set("error", "the question it asked is over")
	event.Set("next_attempt", nil)
	return writeEvent(event)
}

// installedAt is when the ak running now was put in place: install.sh's stamp, or this program's
// own write where later; 0 where no install stamped the home.
func installedAt() float64 {
	data, err := os.ReadFile(filepath.Join(state(), "installed-at"))
	if err != nil {
		return 0
	}
	stamp, err := strconv.ParseFloat(strings.TrimFunc(string(data), config.Space), 64)
	if err != nil {
		return 0
	}
	if program, err := os.Executable(); err == nil {
		if info, err := os.Stat(program); err == nil {
			stamp = max(stamp, float64(info.ModTime().UnixNano())/1e9)
		}
	}
	return stamp
}

// resolved is whether the notice was answered: retired, answered after it, or moved on since an
// open of it.
func resolved(notice *run.Object) bool {
	asked, isAsked := finite(notice.Get("time"))
	answered, isAnswered := finite(notice.Get("answered_at"))
	opened, isOpened := finite(notice.Get("opened_at"))
	moved, isMoved := finite(notice.Get("last_progress_at"))
	return notice.Truthy("seen") || isAsked && isAnswered && asked < answered ||
		isAsked && isOpened && isMoved && asked <= opened && opened < moved
}

// questions are those a needs notice asks, in the order asked.
func questions(notice *run.Object) []string {
	var listed []string
	for _, q := range notice.List("questions") {
		if text, ok := q.(string); ok {
			listed = append(listed, text)
		} else {
			listed = nil
			break
		}
	}
	if len(listed) == 0 {
		return []string{notice.Str("text")}
	}
	return listed
}

// questionKey is a question's identity, which its dates are kept under; its words stay as asked.
func questionKey(question string) string {
	return casefold(config.Fold(question))
}

func finite(value any) (float64, bool) {
	number, ok := run.Num(value)
	return number, ok && !math.IsInf(number, 0) && !math.IsNaN(number)
}

// number is the key's number, or 0, as Python's `get(key) or 0` reads it.
func number(object *run.Object, key string) float64 {
	value, _ := object.Num(key)
	return value
}

func writeNotice(name string, notice *run.Object) error {
	tmp := seatFile("notify", name, "tmp")
	if err := os.WriteFile(tmp, []byte(run.Line(notice)+"\n"), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, seatFile("notify", name, "json"))
}

func writeCard(name string, card *run.Object) error {
	if err := durable(seatFile("card", name, "json"), 0o666, card); err != nil {
		return err
	}
	syncDir(state())
	return nil
}

// errNotObject is a file holding JSON that is no object.
var errNotObject = errors.New("not a JSON object")

// readObject is the JSON object a file holds, nil where there is no file, and an error where
// Python's json.loads fails on it, Go cannot keep what it holds, or it holds no object.
func readObject(path string) (*run.Object, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	value, err := run.Decode(data)
	if err != nil {
		return nil, err
	}
	object, ok := value.(*run.Object)
	if !ok {
		return nil, errNotObject
	}
	return object, nil
}

// failed is the name of the error Python raises where a write fails as err did.
func failed(err error) string {
	switch {
	case errors.Is(err, fs.ErrPermission):
		return "PermissionError"
	case errors.Is(err, fs.ErrNotExist):
		return "FileNotFoundError"
	case errors.Is(err, syscall.EISDIR):
		return "IsADirectoryError"
	case errors.Is(err, syscall.ENOTDIR):
		return "NotADirectoryError"
	}
	return "OSError"
}

func state() string { return filepath.Join(config.Home(), "state") }

// seatFile is the seat's file of one kind, with that extension.
func seatFile(kind, name, extension string) string {
	return filepath.Join(state(), kind+"-"+name+"."+extension)
}

func clock() float64 { return float64(time.Now().UnixNano()) / 1e9 }
