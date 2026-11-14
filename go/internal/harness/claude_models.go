package harness

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func init() {
	verbs["claude models"] = claudeModels
}

// dated is the date a model's id may end in, which the [catalog] table names it without.
var dated = regexp.MustCompile(`-[0-9]{8}$`)

// tsv is jq's @tsv, which keeps each field on its line and between its tabs.
var tsv = strings.NewReplacer(`\`, `\\`, "\t", `\t`, "\n", `\n`, "\r", `\r`)

// claudeModels is adapters/claude.sh's `models`, for the login $AGENTKIT_ACCOUNT names: claude has
// no command that lists its models, but Anthropic's models API names every model the login runs,
// newest first, a page at a time, asked through curl with the token on its stdin, in no argument
// list and no file.  One line each: its id, a dated one the table knows undated answering as the
// table's, so a model added from the table stays marked as added; its `display_name` without the
// leading `Claude `; and the efforts its `capabilities.effort` supports, in the API's order, or
// `none` where it takes no effort.  $ANTHROPIC_BASE_URL is claude's own, and where the tests' fake
// API lives.  1 where the listing fails or names nothing, or there is no token to ask with:
// config.catalog decides what stands in.
func claudeModels(_ []string, out, errOut io.Writer) int {
	login, _, err := config.Account("claude")
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 1
	}
	token := claudeBearer(login)
	base := cmp.Or(os.Getenv("ANTHROPIC_BASE_URL"), "https://api.anthropic.com")
	var models []any
	for after := ""; token != ""; {
		url := base + "/v1/models?limit=1000"
		if after != "" {
			url += "&after_id=" + after
		}
		curl := exec.Command(claudeProgram("curl"), "-sf", "-H", "@-", "-H", "anthropic-beta: oauth-2025-04-20",
			"-H", "anthropic-version: 2023-06-01", url)
		curl.Stdin, curl.Stderr = strings.NewReader("Authorization: Bearer "+token+"\n"), errOut
		said, err := curl.Output()
		page, unread := run.Decode(said)
		data, _ := index(page, "data")
		listed, ok := data.([]any)
		if err != nil || unread != nil || !ok {
			return 1
		}
		models = append(models, listed...)
		if after = ""; page.(*run.Object).Get("has_more") == true {
			after = page.(*run.Object).Str("last_id")
		}
		if after == "" {
			break
		}
	}
	table, _ := config.CatalogTable("claude")
	var lines []string
	for _, each := range models {
		id, _ := index(each, "id")
		name, _ := index(each, "display_name")
		if name == nil || name == false {
			name = id
		}
		capabilities, _ := index(each, "capabilities")
		model, named := id.(string)
		label, labelled := name.(string)
		efforts, read := claudeEfforts(capabilities)
		if !named || !labelled || !read {
			return 1 // where jq fails on the listing's shape, failing all of it
		}
		if bare := dated.ReplaceAllString(model, ""); slices.ContainsFunc(table, func(row []string) bool { return row[0] == bare }) {
			model = bare
		}
		lines = append(lines, tsv.Replace(model)+"\t"+tsv.Replace(strings.TrimPrefix(label, "Claude "))+"\t"+tsv.Replace(efforts))
	}
	if len(lines) == 0 {
		return 1
	}
	fmt.Fprintln(out, strings.Join(lines, "\n"))
	return 0
}

// claudeProgram is the program of that name claude.sh runs: where PATH finds no claude, its
// preamble puts claude's installer's folder ahead of PATH for every program the script runs.
func claudeProgram(name string) string {
	if _, err := exec.LookPath("claude"); err == nil || errors.Is(err, exec.ErrDot) {
		return name
	}
	if found, err := exec.LookPath(filepath.Join(os.Getenv("HOME"), ".local", "bin", name)); err == nil {
		return found
	}
	return name
}

// claudeBearer is the token the listing asks with, as the script finds it: the worker token, from
// the environment or its file, else the seat's own login's, never renewed for this; "" for none.
func claudeBearer(login config.Login) string {
	file, variable := config.WorkerToken("claude", login)
	if token := getenv(login, variable); token != "" {
		return token
	}
	data, _ := os.ReadFile(file)
	if token := strings.TrimRight(string(data), "\n"); token != "" {
		return token
	}
	_, _, oauth := claudeLogin(login)
	token, _ := oauth.Get("accessToken").(string)
	return token
}

// claudeEfforts is the efforts a model's capabilities say it supports, a space apart, `none` where
// it supports none; false where they come in a shape jq cannot read.
func claudeEfforts(capabilities any) (string, bool) {
	effort, read := index(capabilities, "effort")
	if effort == nil || effort == false {
		effort = run.NewObject()
	}
	supported, readable := index(effort, "supported")
	if !read || !readable {
		return "", false
	}
	if supported != true {
		return "none", true
	}
	var levels []string
	for _, level := range effort.(*run.Object).Keys() {
		if each, ok := effort.(*run.Object).Get(level).(*run.Object); ok && each.Get("supported") == true {
			levels = append(levels, level)
		}
	}
	return strings.Join(levels, " "), true
}

// index is jq's `.key` of value: null's is null, and anything but an object or null fails, false.
func index(value any, key string) (any, bool) {
	if object, ok := value.(*run.Object); ok {
		return object.Get(key), true
	}
	return nil, value == nil
}
