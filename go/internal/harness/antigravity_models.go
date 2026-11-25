package harness

import (
	"cmp"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
)

func init() {
	verbs["antigravity models"] = antigravityModels
}

// agyBracketed is the label's own naming of the effort word folded off an id of `agy models`.
var agyBracketed = regexp.MustCompile(` \([^)]*\)$`)

// antigravityModels is adapters/antigravity.sh's `models`: `agy models` prints one id per model and
// effort beside its label, strongest first (`gemini-3.8-flash-high<TAB>Gemini 3.8 Flash (High)`).
// They fold into the model `run` hands to --model, labelled as its first line says it, with the
// words `[effort] levels` in adapters/antigravity.toml names, strongest last; an id with no effort
// word is a model agy runs at no effort, `none`.  1 where the listing fails or says nothing:
// config.catalog decides what stands in.
func antigravityModels(_ []string, out, _ io.Writer) int {
	levels, err := config.Efforts("antigravity", "")
	if err != nil {
		return 1
	}
	flags, env := antigravityLogin()
	said, err := scriptCommand("agy", localBin(), env, "agy", append(flags, "models")...).Output()
	if err != nil {
		return 1
	}
	var order []string
	labels, took := map[string]string{}, map[string][]string{}
	for _, line := range strings.Split(string(said), "\n") {
		fields := strings.Split(line, "\t")
		if len(fields) < 2 {
			continue
		}
		id, label := fields[0], fields[1]
		if cut := strings.LastIndex(id, "-"); cut > 0 && slices.Contains(levels, id[cut+1:]) {
			took[id[:cut]] = append(took[id[:cut]], id[cut+1:])
			id, label = id[:cut], agyBracketed.ReplaceAllString(label, "")
		}
		if _, seen := labels[id]; !seen {
			order, labels[id] = append(order, id), label
		}
	}
	if len(order) == 0 {
		return 1
	}
	for _, id := range order {
		var words []string
		for _, word := range levels {
			if slices.Contains(took[id], word) {
				words = append(words, word)
			}
		}
		io.WriteString(out, id+"\t"+labels[id]+"\t"+cmp.Or(strings.Join(words, " "), "none")+"\n")
	}
	return 0
}

// antigravityLogin is antigravity.sh's header for the login $AGENTKIT_ACCOUNT names, which every
// verb runs first: agy's flags and environment.  An account keeps agy's application data, its
// login among it, in a directory of its own beside the usual one, which agy's --app_data_dir puts
// it in, and whose conversations/ and brain/ are the usual ones, linked before agy can make its
// own; agy's API-key sign-ins are dropped and the session bus closed, so it reads and writes its
// token file alone.  `ak update` owns agy's updates, so nothing mid-run moves.
func antigravityLogin() (flags, env []string) {
	account := os.Getenv("AGENTKIT_ACCOUNT")
	if account == "" {
		return nil, unsetting(nil, "AGY_CLI_DISABLE_AUTO_UPDATE=1")
	}
	usual := filepath.Dir(antigravityConversations())
	own := usual + "-" + account
	for _, store := range []string{"conversations", "brain"} {
		os.MkdirAll(filepath.Join(usual, store), 0o777)
		os.MkdirAll(own, 0o777)
		if _, err := os.Stat(filepath.Join(own, store)); err != nil {
			os.Symlink(filepath.Join("..", filepath.Base(usual), store), filepath.Join(own, store))
		}
	}
	return []string{"--app_data_dir=" + filepath.Base(own)}, unsetting([]string{"GEMINI_API_KEY", "GOOGLE_API_KEY", "AGY_ADC_AUTH"},
		"AGY_CLI_DISABLE_AUTO_UPDATE=1", "DBUS_SESSION_BUS_ADDRESS=disabled:")
}
