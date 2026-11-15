package harness

import (
	"cmp"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
)

func init() {
	verbs["antigravity models"] = antigravityModels
}

var (
	// agyEffort is the effort word an id of `agy models` may end in, agyBracketed the label's own
	// naming of it, and agyLadder those words weakest first.
	agyEffort    = regexp.MustCompile(`-(low|medium|high)$`)
	agyBracketed = regexp.MustCompile(` \([^)]*\)$`)
	agyLadder    = []string{"low", "medium", "high"}
)

// antigravityModels is adapters/antigravity.sh's `models`: `agy models` prints one id per model and
// effort beside its label, strongest first (`gemini-3.8-flash-high<TAB>Gemini 3.8 Flash (High)`).
// They fold into the model `run` hands to --model, labelled as its first line says it, with the
// words it hands to --effort strongest last; an id with no effort word is a model agy runs at no
// effort, `none`.  1 where the listing fails or says nothing: config.catalog decides what stands in.
func antigravityModels(_ []string, out, _ io.Writer) int {
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
		if at := agyEffort.FindStringIndex(id); at != nil {
			took[id[:at[0]]] = append(took[id[:at[0]]], id[at[0]+1:])
			id, label = id[:at[0]], agyBracketed.ReplaceAllString(label, "")
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
		for _, word := range agyLadder {
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
