package harness

import (
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// opencodeSwitchable is opencode.py's `switchable`: whether the running TUI can move to `model` at
// `effort` by `/ak-model`, not where the variant a launch would run, the id's own `#variant`, else
// the effort, is one a launch defines itself (adapters/opencode.sh `variants`), which OpenCode
// reads only as it starts.  An answer that cannot be read restarts too: a launch defines whatever
// it needs.
func opencodeSwitchable(model, effort string) bool {
	adapter, err := config.Adapter("opencode")
	if errors.Is(err, config.ErrNoAdapterDir) {
		adapter, err = config.ShippedAdapter("opencode")
	}
	env, unread := config.ChildEnv()
	if err != nil || unread != nil {
		return false
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, adapter, "variants", model)
	cmd.Env, cmd.WaitDelay = env, time.Second
	host.AdapterCall(cmd)
	out, err := cmd.Output()
	doc, unread := run.Decode([]byte(strings.ToValidUTF8(string(out), "�")))
	top, _ := doc.(*run.Object)
	if err != nil || unread != nil || top == nil {
		return false
	}
	_, variant, _ := strings.Cut(model, "#")
	if variant == "" {
		variant = effort
	}
	providers, _ := top.Get("provider").(*run.Object)
	if providers == nil {
		return false
	}
	for _, name := range providers.Keys() {
		provider, _ := providers.Get(name).(*run.Object)
		if provider == nil {
			return false
		}
		models, _ := provider.Get("models").(*run.Object)
		if models == nil {
			return false
		}
		for _, id := range models.Keys() {
			entry, _ := models.Get(id).(*run.Object)
			if entry == nil {
				return false
			}
			if variants, _ := entry.Get("variants").(*run.Object); variants == nil || variants.Has(variant) {
				return false
			}
		}
	}
	return true
}
