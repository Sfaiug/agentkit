package harness

import (
	"io"
	"os/exec"
	"strings"

	"agentkit/internal/run"
)

func init() {
	verbs["opencode models"] = opencodeModels
}

// opencodeModels is adapters/opencode.sh's `models`: OpenCode's own list of every logged-in
// provider's models, each `provider/model` under the name OpenCode gives it, its variants its
// efforts (opencodeVariants), `none` for one with none.  A `mimo/` model's are left unsaid for the
// [catalog] table to give: its variants never reach MiMo's API, whose one control is the thinking
// switch opencodeVariants defines.  An id the table knows takes the table's label.  Not
// --standalone, whose private server lists no model at all (2.0.24).  1 where the list fails or
// says nothing: config.catalog decides what stands in.
func opencodeModels(_ []string, out, errOut io.Writer) int {
	if opencodeRefused(errOut) {
		return 1
	}
	listing := exec.Command(Binary("opencode"), "api", "model.list")
	// as the script's header leaves it: no update mid-run, no project's config and no seat's
	listing.Env = unsetting([]string{"OPENCODE_CONFIG_CONTENT"}, "OPENCODE_DISABLE_AUTOUPDATE=1",
		"OPENCODE_DISABLE_PROJECT_CONFIG=1", "OPENCODE_CONFIG_PROJECT_DISABLE=1")
	said, err := listing.Output()
	value, unread := run.Decode(said)
	data, read := index(value, "data")
	if err != nil || unread != nil || !read {
		return 1
	}
	models, _ := data.([]any) // a list of any other kind lists nothing
	var rows [][]string
	for _, each := range models {
		model, ok := each.(*run.Object)
		if !ok {
			return 1 // where jq fails on the listing's shape, or writes what no listing of OpenCode's holds
		}
		if model.Get("enabled") == false {
			continue
		}
		provider, named := model.Get("providerID").(string)
		id, identified := model.Get("id").(string)
		name := model.Get("name")
		if name == nil || name == false {
			name = id
		}
		var variants []any
		if provider != "mimo" {
			listed, _ := model.Get("variants").([]any) // variants of any other kind are none
			for _, variant := range listed {
				id, read := index(variant, "id")
				variants, ok = append(variants, id), ok && read
			}
		}
		label, labelled := texts([]any{name})
		efforts, joined := texts(variants)
		if !named || !identified || !ok || !labelled || !joined {
			return 1
		}
		if provider != "mimo" && len(efforts) == 0 {
			efforts = []string{"none"}
		}
		rows = append(rows, []string{provider + "/" + id, label[0], strings.Join(efforts, " ")})
	}
	if len(rows) == 0 {
		return 1
	}
	catalogued(out, "opencode", rows)
	return 0
}
