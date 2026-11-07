//go:build linux

package box

import (
	"context"
	"maps"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"
)

// accountCache is the build cache a check's box names a command that names none, Python's: the
// one Go names outside the box, where the overlay of a home alone shows it and nothing hidden
// covers it, or "".  A check's throwaway HOME shows the account's warm cache, but a command moving
// HOME, as tasks ask of every manual run, left it and compiled the standard library past its own
// timeout (6 Nov 2026).  Naming it mounts nothing, so what the box hides stays hidden and what Go
// writes there goes with the overlay.  With no overlay, nothing is asked of Go.
func accountCache(env, own map[string]string, writable, overlays, hidden []string) string {
	if _, named := env["GOCACHE"]; named || len(overlays) == 0 {
		return ""
	}
	cache := goCache(env)
	if cache == "" || inside(cache, hidden) || !overlaid(cache, own, writable, overlays) {
		return ""
	}
	return cache
}

// goCache is the build cache `go env GOCACHE` names outside the box, asked of ak's own Go, where
// one is there, or "".
func goCache(env map[string]string) string {
	program := ours("go")
	if program == "" {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	// Go starts by writing its telemetry under HOME, making a missing one, so it answers in a
	// read-only view of the host.  Local: ak's own Go answers, never a toolchain it would fetch;
	// from /, no go.mod is read.
	cmd := exec.CommandContext(ctx, "bwrap", "--unshare-user", "--ro-bind", "/", "/", "--dev", "/dev", "--", program, "env", "GOCACHE")
	cmd.Dir = "/"
	for key, value := range env {
		cmd.Env = append(cmd.Env, key+"="+value)
	}
	cmd.Env = append(cmd.Env, "GOTOOLCHAIN=local")
	named, err := cmd.Output()
	// A path is bytes, any of them its own: only Go's line end is not.  `off`, empty or relative:
	// Go keeps no cache.
	cache := strings.TrimSuffix(string(named), "\n")
	if err != nil || !filepath.IsAbs(cache) {
		return ""
	}
	if cache, err = filepath.EvalSymlinks(cache); err != nil {
		return "" // nothing where it points
	}
	return cache
}

// overlaid is whether the overlay of a home alone shows path and all beneath it, so that what is
// written through path goes when the box ends: the deepest place mounted at or above it is one,
// and none mounted beneath is a place of the box's own or a writable one, which keeps what is
// written through it.
func overlaid(path string, own map[string]string, writable, overlays []string) bool {
	mounted := slices.AppendSeq(slices.Clone(writable), maps.Keys(own))
	for above := path; !slices.Contains(overlays, above); above = filepath.Dir(above) {
		if above == "/" || slices.Contains(mounted, above) {
			return false
		}
	}
	return !slices.ContainsFunc(mounted, func(place string) bool { return inside(place, []string{path}) })
}
