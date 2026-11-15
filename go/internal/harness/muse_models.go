package harness

import (
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func init() {
	verbs["muse models"] = museModels
}

// museModelList is what museModels says to `muse serve`: an MSP session opened, then its model list.
const museModelList = `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"agentkit","version":"1"}}}
{"jsonrpc":"2.0","method":"initialized"}
{"jsonrpc":"2.0","id":2,"method":"model/list"}
`

// museModels is adapters/muse.sh's `models`, on the login $AGENTKIT_ACCOUNT names: muse has no
// command that lists its models, but `muse serve` speaks MSP on stdio (`muse schema`), and its
// `model/list` names the models this login's provider catalog offers, newest first, each with its
// reasoning-effort `variants`, weakest first, its labels the ids themselves (1.4.1).  Asked once,
// stdin closed, so the host answers and exits; no session is started or kept.  1 where the listing
// fails or names nothing -- a login-less host lists none: config.catalog decides what stands in.
func museModels(_ []string, out, _ io.Writer) int {
	account := os.Getenv("AGENTKIT_ACCOUNT")
	// as the script's header leaves it: no seat's rulebook, no update mid-run, and on an account
	// its own config home without the usual login's key; on the usual login, without the config
	// home of an account a seat handed down
	unset, set := []string{"TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE"}, []string{"MUSE_NO_AUTO_UPDATE=1", "MUSE_LAUNCHER_INSTALL=0"}
	if account != "" {
		unset, set = append(unset, "XDG_CONFIG_HOME", "META_API_KEY"), append(set, "XDG_CONFIG_HOME="+museConfig(account))
	} else if strings.HasPrefix(os.Getenv("XDG_CONFIG_HOME"), config.UserHome()+"/.muse-") {
		unset = append(unset, "XDG_CONFIG_HOME")
	}
	serve := exec.Command(Binary("muse"), "serve", "--no-session-log")
	serve.Env, serve.Stdin = unsetting(unset, set...), strings.NewReader(museModelList)
	said, err := serve.Output()
	if err != nil {
		return 1
	}
	var lines []string
	for _, line := range strings.Split(string(said), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		value, unread := run.Decode([]byte(line))
		id, read := index(value, "id")
		if unread != nil || !read {
			return 1 // where jq fails on the answer, failing all of it
		}
		// the list's answer is the one whose id is 2, as jq compares numbers
		number, _ := id.(run.Number)
		if second, err := strconv.ParseFloat(string(number), 64); err != nil || second != 2 {
			continue
		}
		result, _ := index(value, "result")
		held, read := index(result, "models")
		models, ok := held.([]any)
		if !read || !ok {
			return 1
		}
		for _, model := range models {
			id, read := index(model, "modelId")
			label, _ := index(model, "displayLabel")
			variants, _ := index(model, "variants")
			listed, _ := variants.([]any) // an effort list of any other kind goes unsaid
			efforts, joined := texts(listed)
			fields, written := texts([]any{id, label})
			if !read || !joined || !written {
				return 1 // where jq fails on the listing's shape, or writes what no listing of Muse's holds
			}
			lines = append(lines, tsv.Replace(fields[0])+"\t"+tsv.Replace(fields[1])+"\t"+tsv.Replace(strings.Join(efforts, " ")))
		}
	}
	if len(lines) == 0 {
		return 1
	}
	io.WriteString(out, strings.Join(lines, "\n")+"\n")
	return 0
}
