package harness

import (
	"cmp"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// A seat's status line, `ak hook status` as hooks/claude-status.sh, writes down the model and
// effort each render of its conversation names, in state/model-<conversation>.json, for a look to
// read without another answer (harness.model_report).  Only an id that names one file is written;
// a render's file goes in whole, through a dot-file of its own beside it.  Beside it,
// state/limits-<conversation>.json notes what its renders said of their login's limits (Noted).
var reportable = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// reportPath is the file a status render of that conversation is written down in.
func reportPath(conversation string) string {
	return filepath.Join(config.Home(), "state", "model-"+conversation+".json")
}

// rendered is a status render's JSON as the hook's one jq reads it: the render, its conversation,
// and what it says that conversation runs on, `model.id`, and `model.effort`, else
// `effort.level`, as jq's `//` reads them; no conversation for a render naming no model, or no
// conversation one file can name.
func rendered(payload []byte) (render *run.Object, conversation, report string) {
	read, _ := run.Decode(payload)
	if render, _ = read.(*run.Object); render == nil {
		return nil, "", ""
	}
	conversation, _ = render.Get("session_id").(string)
	model := render.Dict("model")
	if !reportable.MatchString(conversation) || model == nil || model.Str("id") == "" {
		return nil, "", ""
	}
	effort := model.Get("effort")
	if effort == nil || effort == false {
		switch top := render.Get("effort").(type) {
		case nil:
			effort = nil
		case *run.Object:
			if effort = top.Get("level"); effort == false {
				effort = nil
			}
		default: // jq cannot index it
			return nil, "", ""
		}
	}
	return render, conversation, fmt.Sprintf(`{"model":%s,"effort":%s}`, run.Line(model.Str("id")), run.Line(effort))
}

// Report writes down what a status render's JSON says its conversation runs on.  True where that
// changed what was written, for the seat to be looked at again; a render naming no model, or no
// conversation one file can name, writes nothing.
func Report(payload []byte) bool {
	_, conversation, report := rendered(payload)
	if conversation == "" {
		return false
	}
	path := reportPath(conversation)
	dir := filepath.Dir(path)
	if kept, _ := os.ReadFile(path); strings.TrimRight(string(kept), "\n") == report {
		return false
	}
	if os.MkdirAll(dir, 0o700) != nil {
		return false
	}
	tmp, err := os.CreateTemp(dir, ".model-"+conversation+".*")
	if err != nil {
		return false
	}
	_, err = io.WriteString(tmp, report+"\n")
	if err = cmp.Or(err, tmp.Close()); err == nil {
		err = os.Rename(tmp.Name(), path)
	}
	if err != nil {
		os.Remove(tmp.Name())
	}
	return err == nil
}

// Limits is the conversation of a status render of that harness's seat and each window of its
// login's limits the render carries, as `<window> <words>`; none where its renders carry none, or
// it is one Report writes nothing of.
func Limits(name string, payload []byte) (string, []string) {
	render, conversation, _ := rendered(payload)
	if hook := plugins[name].limits; hook != nil && conversation != "" {
		return conversation, hook(render)
	}
	return "", nil
}

// StatusMeters is those windows a render of that harness carried as endpoint meters, Python's
// plugin `status_meters`.
func StatusMeters(name string, windows []string) []any {
	if hook := plugins[name].statusMeters; hook != nil {
		return hook(windows)
	}
	return nil
}

// limitsPath is the note of what renders of that conversation said of their login's limits: each
// window as `[login, words, moment]`, the moment its render began, in json.dumps's spacing.
func limitsPath(conversation string) string {
	return filepath.Join(config.Home(), "state", "limits-"+conversation+".json")
}

// Noted is whether that conversation's note holds each of those windows as login's, read with no
// lock: a note read half-written or a moment old only costs one more Note.
func Noted(conversation, login string, windows []string) bool {
	data, _ := os.ReadFile(limitsPath(conversation))
	read, _ := run.Decode(data)
	note, _ := read.(*run.Object)
	for _, line := range windows {
		window, words, _ := strings.Cut(line, " ")
		if held := noted(note, window); held[0] != login || held[1] != words {
			return false
		}
	}
	return true
}

// noted is the note's `[login, words, moment]` of that window, nil for each part it lacks.
func noted(note *run.Object, window string) (held [3]any) {
	if note != nil {
		copy(held[:], note.List(window))
	}
	return held
}

// Note writes down the windows a render of that conversation on that login carried, which began
// at that moment, Python's watch.hook_meters, and answers those of them that changed from what the
// note held.  An idle seat renders its last answer again and again, so only a change is news; a
// window the note did not hold is only kept, as its numbers may be as old as the seat's last
// answer.  It is the note's one writer, under an exclusive lock on it from read to write, so
// windows are judged in the order renders began, whatever order their hand-ins arrive in; written
// in place, as a rename would take the lock's file away.
func Note(conversation, login string, began float64, windows []string) []string {
	path := limitsPath(conversation)
	os.MkdirAll(filepath.Dir(path), 0o700)
	if made, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o600); err == nil {
		made.Close()
	}
	file, err := lock.Edit(path)
	if err != nil {
		return nil
	}
	defer file.Close()
	data, _ := io.ReadAll(file)
	read, _ := run.Decode(data)
	note, _ := read.(*run.Object)
	if note == nil {
		note = run.NewObject()
	}
	var changed []string
	for _, line := range windows {
		window, words, _ := strings.Cut(line, " ")
		held := noted(note, window)
		if at, ok := run.Num(held[2]); ok && at >= began {
			continue
		}
		if len(note.List(window)) > 0 && (held[0] != login || held[1] != words) {
			changed = append(changed, line)
		}
		note.Set(window, []any{login, words, run.Float(began)})
	}
	written := run.Line(note)
	if _, err := file.WriteAt([]byte(written), 0); err != nil || file.Truncate(int64(len(written))) != nil {
		return nil
	}
	return changed
}

// Reported is the model, effort and moment the seat's status line last reported for the
// conversation it owns, the model as its harness's answers name it; "" where that harness's status
// line reports nothing or no render of that conversation has.  Its moment is the file's, read from
// the file read, which another render may since have replaced.
func (reader Reader) Reported(record *run.Object) (model string, effort any, at float64, err error) {
	conversation := record.Str("conversation")
	if hook := reader.own.owning; hook != nil {
		conversation = hook(record)
	}
	if reader.own.report == nil || !reportable.MatchString(conversation) {
		return "", nil, 0, nil
	}
	file, err := os.Open(reportPath(conversation))
	if err != nil {
		return "", nil, 0, nil
	}
	defer file.Close()
	data, err := io.ReadAll(file)
	info, statErr := file.Stat()
	read, _ := run.Decode(data)
	report, _ := read.(*run.Object)
	if err != nil || statErr != nil || report == nil || report.Str("model") == "" {
		return "", nil, 0, nil
	}
	model, err = reader.own.report(report.Str("model"))
	return model, report.Get("effort"), float64(info.ModTime().UnixNano()) / 1e9, err
}

// StatusCommand is ak's status line as that harness's seat runs it, Go's at root: the render's JSON
// on its stdin, piped on to the owner's command where it has one.
func StatusCommand(root, name string) string {
	return commandhelp.ShellJoin([]string{filepath.Join(root, "bin", "ak"), "hook", "status", name})
}

// StatusFiles is the settings files that harness reads the owner's status command from, the
// first naming one its, which a seat's line hands it behind ak's own (`ak hook status`); none
// where Go prints no such line.
func StatusFiles(name string) []string { return plugins[name].status }

// asReported is a status line reporting its model by the id its answers name.
func asReported(model string) (string, error) { return model, nil }
