package usage

import (
	"context"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

const (
	probeCap   = 30 * time.Second // an adapter's `usage` that runs no model
	probeEvery = 60.0             // seconds one ask answers for, where the harness names no cadence
)

// gently is that provider's reading, asked at most once in its harness's cadence across this
// host, Python's usage._probe_gently: the moment is written in its probe lock, under that lock,
// as the ask goes out, so a caller waiting on the lock reads the answer instead of asking again.
func gently(src source) *run.Object {
	path := filepath.Join(state(), src.Name+"-probe.lock")
	held, err := lockFile(path)
	if err != nil { // no lock to take: still one probe
		now := clock()
		fresh := probe(src, now)
		noteRetry(src.Name, fresh, clock())
		cached := cachedProvider(src.Name)
		return onto(cached, kept(cached, fresh, now), now)
	}
	defer held.Close()
	cached := cachedProvider(src.Name)
	every := src.facts.ProbeEvery
	if every <= 0 {
		every = probeEvery
	}
	if cooling(src.Name, every) {
		return cached
	}
	now := clock()
	os.WriteFile(path, []byte(run.Float(now)), 0o666)
	fresh := probe(src, now)
	noteRetry(src.Name, fresh, clock())
	return patch(src.Name, kept(cached, fresh, now))
}

// probe is that provider's reading as its adapter's `usage` verb answers it now, Python's
// usage._probe.
func probe(src source, now float64) *run.Object {
	adapter, err := config.Adapter(src.Harness)
	if src.Via == "" {
		err = fmt.Errorf("~/.agentkit/config.toml: [providers.%s] has no model", src.Name)
	}
	if err != nil {
		return fields("provider", src.Name, "meters", []any{}, "error", "unknown: "+err.Error(), "pace", nil,
			"resets", nil, "exhausted", false, "probed_at", now)
	}
	name := filepath.Base(adapter)
	data, said := answer(adapter, name, src.Name)
	out := fields("provider", src.Name, "harness", src.Harness, "via", src.Via, "meters", []any{}, "error", data.Get("error"),
		"pace", nil, "resets", 0.0, "exhausted", false, "probed_at", now)
	var credits any = "unlimited"
	if data.Get("credits") != credits {
		credits = nil
		if left, ok := number(data.Get("credits")); ok {
			credits = left
		}
	}
	if credits != nil {
		out.Set("credits", credits)
		if currency, _ := data.Get("currency").(string); currency != "" {
			out.Set("currency", currency)
		}
	}
	if retry, ok := number(data.Get("retry_after")); ok && retry > 0 {
		out.Set("retry_after", retry)
	}
	meters := []any{}
	for _, each := range data.List("meters") {
		meter := object(each)
		if _, named := meter.Get("name").(string); !named || !numbers(meter, "used") {
			if !out.Truthy("error") {
				out.Set("error", "unknown: "+name+" reported a meter without a name and a numeric used%")
			}
			continue
		}
		meters = append(meters, normalized(meter, now))
	}
	out.Set("meters", meters)
	out.Set("pace", topPace(meters))
	if src.facts.None && !out.Truthy("error") && len(meters) == 0 {
		// a harness that reads no meter answered none: neutral, not unknown
		why, _ := data.Get("none").(string)
		out.Set("none", true)
		out.Set("none_reason", "no meter")
		if why != "" {
			out.Set("none_reason", why)
		}
	}
	if len(meters) == 0 && !out.Truthy("error") && !out.Truthy("none") {
		out.Set("error", "unknown: adapter returned no meters")
	}
	if said && len(meters) == 0 && !refused(text(data.Get("error"))) {
		// only the harness's own `auth` says whether the login is what failed, never the error
		env, _ := config.ChildEnv()
		var told []string
		for _, pair := range env {
			if !strings.HasPrefix(pair, host.Marker+"=") {
				told = append(told, pair)
			}
		}
		var loggedIn any
		if answered, yes, _ := worker.Login(adapter, append(told, "AGENTKIT_PROVIDER="+src.Name)); answered {
			loggedIn = yes
		}
		out.Set("logged_in", loggedIn)
	}
	return out
}

// answer is the JSON object the adapter's `usage` printed for the usual login of that provider,
// or one saying why there is none, and whether it is the adapter's own answer, whose error the
// `auth` question may be asked about.
func answer(adapter, name, provider string) (*run.Object, bool) {
	failed := func(why string) (*run.Object, bool) {
		return fields("meters", []any{}, "error", "unknown: "+name+" usage "+why), false
	}
	ctx, cancel := context.WithTimeout(context.Background(), probeCap)
	defer cancel()
	cmd := exec.CommandContext(ctx, adapter, "usage")
	cmd.Env = append(os.Environ(), "AGENTKIT_ACCOUNT=", "AGENTKIT_PROVIDER="+provider)
	cmd.WaitDelay = time.Second
	host.Group(cmd)
	out, err := cmd.Output()
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return failed("timed out after 30s")
	}
	if err != nil && !errors.As(err, new(*exec.ExitError)) {
		return failed("produced no JSON (" + err.Error() + ")")
	}
	// read as Python's text mode reads it
	said := strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(strings.ToValidUTF8(string(out), string(utf8.RuneError)))
	value, err := run.Decode([]byte(said))
	if err != nil {
		return failed("produced no JSON (" + err.Error() + ")")
	}
	data, ok := value.(*run.Object)
	if !ok {
		return failed("produced no JSON (expected a JSON object, got " + typeName(value) + ")")
	}
	if code := cmd.ProcessState.ExitCode(); code != 0 {
		return failed("exited " + strconv.Itoa(code))
	}
	if _, listed := data.Get("meters").([]any); data.Has("meters") && !listed {
		return failed("produced no JSON (expected a list of meters)")
	}
	return data, data.Truthy("error")
}

// what a probe the endpoint was briefly unable to answer says: a 5xx, or that it never came back
var (
	fiveHundred = regexp.MustCompile(`(?i)HTTP 5[0-9][0-9]`)
	timedOut    = regexp.MustCompile(`(?i)timed out`)
)

// refused is whether an error says the endpoint would not answer, Python's usage.probe_refused:
// a rate limit, a 5xx or a probe that never came back, none of which says anything of the
// credentials it went out with.
func refused(error string) bool {
	if harness.Limited(error) || timedOut.MatchString(error) {
		return true
	}
	for _, span := range fiveHundred.FindAllStringIndex(error, -1) { // whole, as Python's \b says
		before, _ := utf8.DecodeLastRuneInString(error[:span[0]])
		after, _ := utf8.DecodeRuneInString(error[span[1]:])
		if (span[0] == 0 || !word(before)) && (span[1] == len(error) || !word(after)) {
			return true
		}
	}
	return false
}

// cooling is whether that provider's adapter was asked inside every seconds, by the moment its
// lock holds, or its last refusal named a not-before still ahead.
func cooling(provider string, every float64) bool {
	now := clock()
	if asked, ok := readNumber(filepath.Join(state(), provider+"-probe.lock")); ok && now-asked >= 0 && now-asked < every {
		return true
	}
	until, ok := readNumber(filepath.Join(state(), provider+"-probe.retry"))
	return ok && now < until
}

// noteRetry writes down the Retry-After the ask came back with, as a not-before beside the lock,
// so deleting the snapshot buys no earlier ask.
func noteRetry(provider string, fresh *run.Object, now float64) {
	if secs, ok := number(fresh.Get("retry_after")); ok && secs > 0 && config.EnsureDirs() == nil {
		os.WriteFile(filepath.Join(state(), provider+"-probe.retry"), []byte(run.Float(now+secs)), 0o666)
	}
}

// readNumber is the finite number a file holds, as Python's float() reads its text.
func readNumber(path string) (float64, bool) {
	data, err := os.ReadFile(path)
	if err != nil || !utf8.Valid(data) {
		return 0, false
	}
	value, err := strconv.ParseFloat(strings.TrimFunc(string(data), config.Space), 64)
	return value, err == nil && !math.IsInf(value, 0) && !math.IsNaN(value)
}
