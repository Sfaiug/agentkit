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
	"agentkit/internal/run"
)

// A seat's status line, `ak hook status` as hooks/claude-status.sh, writes down the model and
// effort each render of its conversation names, in state/model-<conversation>.json, for a look to
// read without another answer (harness.model_report).  Only an id that names one file is written;
// a render's file goes in whole, through a dot-file of its own beside it.
var (
	reportable = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)
	reportFile = regexp.MustCompile(`^(model-[A-Za-z0-9_-]+\.json|\.model-[A-Za-z0-9_-]+\.[A-Za-z0-9]+)$`)
)

// reportPath is the file a status render of that conversation is written down in.
func reportPath(conversation string) string {
	return filepath.Join(config.Home(), "state", "model-"+conversation+".json")
}

// Report writes down what a status render's JSON says its conversation runs on: `model.id`, and
// `model.effort`, else `effort.level`, as jq's `//` reads them.  True where that changed what was
// written, for the seat to be looked at again; a render naming no model, or no conversation one
// file can name, writes nothing.
func Report(payload []byte) bool {
	read, _ := run.Decode(payload)
	render, _ := read.(*run.Object)
	if render == nil {
		return false
	}
	conversation, _ := render.Get("session_id").(string)
	model := render.Dict("model")
	if !reportable.MatchString(conversation) || model == nil || model.Str("id") == "" {
		return false
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
			return false
		}
	}
	report := fmt.Sprintf(`{"model":%s,"effort":%s}`, run.Line(model.Str("id")), run.Line(effort))
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

// StatusCommand is ak's status line as a seat's harness runs it, Go's at root: the render's JSON on
// its stdin, piped on to the owner's command where it has one.
func StatusCommand(root string) string {
	return commandhelp.ShellJoin([]string{filepath.Join(root, "bin", "ak"), "hook", "status"})
}

// StatusFiles is the settings files that harness reads the owner's status command from, the
// first naming one its, which a seat's line hands it behind ak's own (`ak hook status`); none
// where Go prints no such line.
func StatusFiles(name string) []string { return plugins[name].status }

// asReported is a status line reporting its model by the id its answers name.
func asReported(model string) (string, error) { return model, nil }
