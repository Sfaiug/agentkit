package harness

import (
	"cmp"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// planHost is MiMo's token plan, per region (opencode.py PLAN_HOST).
var planHost = regexp.MustCompile(`^token-plan[\w-]*\.xiaomimimo\.com$`)

// opencodeMode is "subscription" where OpenCode sends this MiMo model to a token-plan host,
// "payg" wherever that is not certain, and "" for a model of any other provider, as opencode.py's
// `mode` reads the one global opencode.json the adapter launches OpenCode with: a plain https
// token-plan URL under native `providers.mimo.settings.baseURL` or legacy
// `provider.mimo.options.baseURL`, and no other endpoint under either table.  Anything that could
// send the model elsewhere unseen is payg, which never spends money unasked.
func opencodeMode(model config.Model) string {
	if prefix, _, _ := strings.Cut(model.ID, "/"); prefix != "mimo" {
		return ""
	}
	folder := cmp.Or(os.Getenv("OPENCODE_CONFIG_DIR"),
		walked(cmp.Or(os.Getenv("XDG_CONFIG_HOME"), walked(config.UserHome(), ".config")), "opencode"))
	if os.Getenv("OPENCODE_CONFIG") != "" {
		return "payg"
	}
	if _, err := os.Stat(walked(folder, "opencode.jsonc")); !errors.Is(err, fs.ErrNotExist) {
		return "payg"
	}
	data, err := os.ReadFile(walked(folder, "opencode.json"))
	if err != nil {
		return "payg"
	}
	doc, err := run.Decode(data)
	if err != nil {
		return "payg"
	}
	native, legacy := table(doc, "providers", "mimo"), table(doc, "provider", "mimo")
	held := table(native, "settings")
	if !held.Truthy("baseURL") {
		held = table(legacy, "options")
	}
	url, plain := held.Get("baseURL").(string)
	if !plain || !isASCII(url) || strings.ContainsAny(url, `{\`) {
		return "payg"
	}
	for _, other := range append(endpoints(native), endpoints(legacy)...) {
		if text, ok := other.(string); !ok || text != url {
			return "payg"
		}
	}
	if !onPlan(url) {
		return "payg"
	}
	return "subscription"
}

// onPlan is whether Python's urllib.parse.urlsplit reads that ASCII URL as https to a token-plan
// host, with no user part and a port, if any, that is a number in range.  A bracketed host is
// none: urlsplit refuses one that is no IP address, and an IP address is no plan host.
func onPlan(url string) bool {
	url = strings.TrimLeftFunc(url, func(char rune) bool { return char <= ' ' }) // C0 controls and space
	url = strings.NewReplacer("\t", "", "\r", "", "\n", "").Replace(url)
	if len(url) < len("https://") || !strings.EqualFold(url[:len("https:")], "https:") || url[len("https:"):len("https://")] != "//" {
		return false
	}
	netloc := url[len("https://"):]
	if end := strings.IndexAny(netloc, "/?#"); end >= 0 {
		netloc = netloc[:end]
	}
	if strings.ContainsAny(netloc, "@[]") {
		return false
	}
	host, port, _ := strings.Cut(netloc, ":")
	if port != "" {
		number, err := strconv.Atoi(port)
		if err != nil || strings.Trim(port, "0123456789") != "" || number > 65535 {
			return false
		}
	}
	return planHost.MatchString(strings.ToLower(host))
}

// walked is name in dir as the adapter's shell joins "$dir/name" and the system walks it: never
// cleaned, as `..` after a link leads out of the link's target, where OpenCode reads.
func walked(dir, name string) string {
	return dir + string(filepath.Separator) + name
}

// table is the object under those keys, an empty one where any of them holds no object.
func table(value any, keys ...string) *run.Object {
	for _, key := range keys {
		held, _ := value.(*run.Object)
		if held == nil {
			return run.NewObject()
		}
		value = held.Get(key)
	}
	if held, _ := value.(*run.Object); held != nil {
		return held
	}
	return run.NewObject()
}

// endpoints is every endpoint a provider table names anywhere inside it: `baseURL`, and legacy
// `api` (opencode.py `_urls`).
func endpoints(value any) []any {
	var found []any
	switch value := value.(type) {
	case *run.Object:
		for _, key := range value.Keys() {
			if key == "baseURL" || key == "api" {
				found = append(found, value.Get(key))
			} else {
				found = append(found, endpoints(value.Get(key))...)
			}
		}
	case []any:
		for _, item := range value {
			found = append(found, endpoints(item)...)
		}
	}
	return found
}

func isASCII(text string) bool {
	for i := 0; i < len(text); i++ {
		if text[i] >= 0x80 {
			return false
		}
	}
	return true
}
