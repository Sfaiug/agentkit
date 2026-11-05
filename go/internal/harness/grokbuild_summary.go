package harness

import (
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// grokSettingsChanged leaves a differing summary to Python's follow_model, including its
// freshness and choice of configured model and supported effort. grokbuild.py's session_dir
// reads GROK_HOME directly and quotes the whole working directory, with spaces as %20.
func grokSettingsChanged(record *run.Object) bool {
	if !record.Truthy("conversation") || !record.Truthy("cwd") {
		return false
	}
	home := os.Getenv("GROK_HOME")
	if home == "" {
		home = filepath.Join(config.UserHome(), ".grok")
	}
	cwd := strings.ReplaceAll(url.QueryEscape(record.Str("cwd")), "+", "%20")
	summary, _ := run.ReadJSON(filepath.Join(home, "sessions", cwd, record.Str("conversation"), "summary.json"))
	if summary == nil || summary.Str("current_model_id") == "" {
		return false
	}
	models, err := config.Models()
	if err != nil {
		return true
	}
	name := record.Str("orchestrator")
	entry := models[name]
	effort := entry.Efforts["effort"]
	if held := record.Dict("efforts"); held != nil {
		if own := held.Dict(name); own != nil {
			effort = own.Str("effort")
		}
	}
	reported := summary.Str("reasoning_effort")
	return summary.Str("current_model_id") != entry.ID || reported != "" && reported != effort
}
