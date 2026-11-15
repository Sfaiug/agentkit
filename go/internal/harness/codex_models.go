package harness

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func init() {
	verbs["codex models"] = codexModels
}

// codexModels is adapters/codex.sh's `models`, for the login codexLogin picks: `default` first, as
// the [catalog] table answers for Codex's own model, then each model `codex debug models` lists
// as `list`ed, refreshed for this login (never --bundled, which skips that): its slug, its display
// name and the reasoning levels it supports, strongest last.  1 where the listing fails, comes in a
// shape jq cannot read or lists nothing: config.catalog decides what stands in.
func codexModels(_ []string, out, _ io.Writer) int {
	listing := exec.Command(Binary("codex"), "debug", "models")
	// As the script runs it: on an account its own home, none of the usual login's keys; on the
	// usual login, without the home of an account a seat handed down.
	account := os.Getenv("AGENTKIT_ACCOUNT")
	listing.Env = slices.DeleteFunc(os.Environ(), func(pair string) bool {
		name, value, _ := strings.Cut(pair, "=")
		return name == "CODEX_HOME" && (account != "" || strings.HasPrefix(value, config.UserHome()+"/.codex-")) ||
			account != "" && (name == "OPENAI_API_KEY" || name == "CODEX_API_KEY")
	})
	if account != "" {
		listing.Env = append(listing.Env, "CODEX_HOME="+codexLogin())
	}
	said, err := listing.Output()
	value, unread := run.Decode(said)
	held, _ := index(value, "models")
	models, ok := held.([]any)
	if err != nil || unread != nil || !ok {
		return 1
	}
	var lines []string
	for _, model := range models {
		visibility, read := index(model, "visibility")
		if !read {
			return 1
		}
		if visibility != "list" {
			continue
		}
		listed := model.(*run.Object)
		levels := listed.Get("supported_reasoning_levels")
		if levels == nil || levels == false {
			levels = []any{}
		}
		each, ok := levels.([]any)
		fields := []any{listed.Get("slug"), listed.Get("display_name")}
		for _, level := range each {
			effort, read := index(level, "effort")
			fields, ok = append(fields, effort), ok && read
		}
		// each a string, null nothing, as jq's @tsv and join write them
		texts := make([]string, len(fields))
		for i, field := range fields {
			text, isText := field.(string)
			texts[i], ok = text, ok && (isText || field == nil)
		}
		if !ok {
			return 1 // where jq fails on the listing's shape, or writes what no listing of Codex's holds
		}
		lines = append(lines, tsv.Replace(texts[0])+"\t"+tsv.Replace(texts[1])+"\t"+tsv.Replace(strings.Join(texts[2:], " ")))
	}
	if len(lines) == 0 {
		return 1
	}
	own := []string{"default", "", "default"}
	table, _ := config.CatalogTable("codex")
	if at := slices.IndexFunc(table, func(row []string) bool { return row[0] == "default" }); at >= 0 {
		own = table[at]
	}
	fmt.Fprintf(out, "%s\t%s\t%s\n%s\n", own[0], own[2], own[1], strings.Join(lines, "\n"))
	return 0
}
