package harness

import (
	"io"
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// grokAnswer is the model and effort Grok Build last recorded for the seat's conversation, and
// when, as grokbuild.py's `running` reads them: 1.0.46 saves a `/model` or effort change in
// summary.json at once, before any answer, so the file's write time says when.
func grokAnswer(record *run.Object) (model, effort, at any, found bool) {
	if !record.Truthy("conversation") || !record.Truthy("cwd") {
		return nil, nil, nil, false
	}
	file, err := os.Open(filepath.Join(grokSession(record.Str("cwd"), record.Str("conversation")), "summary.json"))
	if err != nil {
		return nil, nil, nil, false
	}
	defer file.Close()
	data, err := io.ReadAll(file)
	if err != nil {
		return nil, nil, nil, false
	}
	value, _ := run.Decode(data)
	summary, _ := value.(*run.Object)
	info, err := file.Stat()
	if summary == nil || err != nil || summary.Str("current_model_id") == "" {
		return nil, nil, nil, false
	}
	return summary.Get("current_model_id"), summary.Get("reasoning_effort"), run.Float(float64(info.ModTime().UnixNano()) / 1e9), true
}
