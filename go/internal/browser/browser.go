// Package browser is what ak knows of the server's one shared, logged-in Chromium, a stack ak
// reads and does not run.  It hides the stack's units: an Xvfb display `:99`, its window manager,
// the Chromium whose profile is the owner's logins, x11vnc, noVNC and the MCP server every seat
// shares; the DevTools and MCP addresses, and noVNC's, read from the unit websockify runs in; and
// how systemd and DevTools are read: `systemctl show` and `is-active`, and DevTools' HTTP JSON as
// Python's urllib and json read it.  `login`, `install` and `mcp-register` join it later.
package browser

import (
	"bytes"
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// ErrPython leaves a status to Python ak before Go has printed anything: what Go cannot read as
// Python reads it, or where Python's own reading ends in a traceback.
var ErrPython = errors.New("left to Python")

const (
	display   = ":99"
	mcpURL    = "http://localhost:8931/mcp"
	mcpUnit   = "browser-bridge-mcp.service"
	novncUnit = "browser-bridge-novnc.service"
	vnc       = "127.0.0.1:5900"  // what websockify proxies, beside the address it listens on
	limit     = 120 * time.Second // a systemctl's, as Python's browser.systemctl waits
)

var units = []string{"browser-bridge-xvfb.service", "browser-bridge-openbox.service",
	"browser-bridge-chromium.service", "browser-bridge-x11vnc.service", novncUnit}

// Where the stack answers; a test points them at its own.
var (
	cdp     = "http://127.0.0.1:9222"
	unitDir = "/etc/systemd/system"
)

// hostPort is websockify's listening address in its ExecStart, digits as Python's \d reads them.
var hostPort = regexp.MustCompile(`^(\p{Nd}{1,3}(?:\.\p{Nd}{1,3}){3}|\[[0-9A-Fa-f:]+\]):(\p{Nd}{1,5})$`)

// client reads DevTools as Python's urllib does: through no proxy (proxied leaves one to
// Python), asking for no compression, within its 4 seconds.
var client = &http.Client{Timeout: 4 * time.Second, Transport: &http.Transport{DisableCompression: true}}

// Status prints `ak browser status` as Python's browser.status does and is its exit code: 1 when
// a part that is installed is down.  Its lines wait until every reading is in, so a status left
// to Python prints nothing; a systemctl that fails ends it after the lines before it.  A reader
// that stops reading ends it with 0, as Python's BrokenPipeError handling does.
func Status(out io.Writer) (int, error) {
	lines, healthy, err := status()
	if errors.Is(err, ErrPython) {
		return 0, err
	}
	signal.Notify(make(chan os.Signal, 1), syscall.SIGPIPE) // a closed pipe is a write error, not death
	for _, line := range lines {
		if _, failed := io.WriteString(out, line+"\n"); failed != nil {
			return 0, nil
		}
	}
	if healthy {
		return 0, err
	}
	return 1, err
}

func status() ([]string, bool, error) {
	var lines []string
	say := func(format string, args ...any) { lines = append(lines, fmt.Sprintf(format, args...)) }
	// once a unit is installed a part that is down fails the status; with none, this is a Mac
	healthy, installed := true, false
	if !onPath("systemctl") {
		say("units      no systemd on this machine; the stack lives on the server")
		say("mcp        no systemd on this machine; the shared server lives on the server")
	} else {
		env, err := config.ChildEnv()
		if err != nil {
			return nil, false, ErrPython
		}
		states, err := unitStates(env)
		if err != nil {
			return nil, false, err
		}
		down := false
		for i, unit := range units {
			say("  %-32s %s", unit, states[i])
			installed = installed || states[i] != "absent"
			down = down || !strings.HasPrefix(states[i], "active")
		}
		if !installed {
			say("units      none installed here; `ak browser install` puts them in")
		}
		healthy = !installed || !down
		code, active, err := systemctl(env, "is-active", mcpUnit)
		if err != nil {
			return lines, false, err
		}
		if code == 0 && strings.TrimFunc(active, config.Space) == "active" {
			say("mcp        %s active (%s)", mcpURL, mcpUnit)
		} else {
			say("mcp        %s not active; `ak browser install` sets it up", mcpURL)
			healthy = healthy && !installed
		}
	}
	version, err := read("/json/version")
	var list any
	if err == nil {
		list, err = read("/json/list")
	}
	if errors.Is(err, ErrPython) {
		return nil, false, err
	}
	if err != nil {
		say("cdp        %s unreachable (%v)", cdp, err)
		healthy = healthy && !installed
	} else {
		rows, err := tabs(version, list)
		if err != nil {
			return nil, false, err
		}
		lines = append(lines, rows...)
	}
	var missing []string
	if !onPath("xdotool") {
		missing = append(missing, "xdotool")
	}
	if !onPath("import") && !onPath("magick") {
		missing = append(missing, "imagemagick")
	}
	if missing != nil {
		say("desktop    DISPLAY=%s, missing %s", display, strings.Join(missing, ", "))
	} else {
		say("desktop    DISPLAY=%s, xdotool and import present", display)
	}
	address, err := novnc()
	if err != nil {
		return nil, false, err
	}
	if address != "" {
		say("novnc      %s", address)
	} else {
		say("novnc      no address recorded; the noVNC unit is not installed here")
	}
	return lines, healthy, nil
}

// onPath is whether Python's shutil.which finds the program, a relative PATH entry's included.
func onPath(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil || errors.Is(err, exec.ErrDot)
}

// systemctl is `systemctl ARGS`'s exit code and what it printed, run as Python's
// browser.systemctl runs it; an error is one Python's ak browser says.
func systemctl(env []string, args ...string) (int, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), limit)
	defer cancel()
	command := exec.CommandContext(ctx, "systemctl", args...)
	if errors.Is(command.Err, exec.ErrDot) {
		command.Err = nil // Python's subprocess runs what a relative PATH entry finds
	}
	var out bytes.Buffer
	command.Env, command.Stdin, command.Stdout = env, os.Stdin, &out
	command.WaitDelay = limit // a program it left holding its output open is waited for no longer
	err := command.Run()
	var exited *exec.ExitError
	switch {
	case ctx.Err() != nil:
		return 0, "", fmt.Errorf("systemctl %s did not return within %.0fs", strings.Join(args, " "), limit.Seconds())
	case errors.As(err, &exited):
		return exited.ExitCode(), out.String(), nil
	case err != nil:
		return 0, "", fmt.Errorf("cannot run systemctl: %v", err)
	}
	return 0, out.String(), nil
}

// unitStates is each unit's "active (running)", "inactive (dead)" or "absent", as Python's
// browser.unit_states reads `systemctl show`.
func unitStates(env []string) ([]string, error) {
	_, out, err := systemctl(env, append([]string{"show", "--no-pager", "--property=Id",
		"--property=LoadState", "--property=ActiveState", "--property=SubState"}, units...)...)
	if err != nil {
		return nil, err
	}
	if !utf8.ValidString(out) {
		return nil, ErrPython // Python puts its own replacement in
	}
	blocks, current := map[string]map[string]string{}, map[string]string{}
	for _, line := range append(config.SplitLines(out), "") {
		if strings.TrimFunc(line, config.Space) == "" {
			if current["Id"] != "" {
				blocks[current["Id"]] = current
			}
			current = map[string]string{}
			continue
		}
		key, value, _ := strings.Cut(line, "=")
		current[key] = value
	}
	states := make([]string, len(units))
	for i, unit := range units {
		block, ok := blocks[unit]
		load, loaded := block["LoadState"]
		if !ok || !loaded || load == "not-found" || load == "masked" {
			states[i] = "absent"
			continue
		}
		field := func(key string) string {
			if value, ok := block[key]; ok {
				return value
			}
			return "?"
		}
		states[i] = field("ActiveState") + " (" + field("SubState") + ")"
	}
	return states, nil
}

// read is one of DevTools' JSON answers, as Python's browser.cdp reads it; an error says why it
// cannot be read.
func read(path string) (any, error) {
	if proxied() {
		return nil, ErrPython
	}
	response, err := client.Get(cdp + path)
	var failed *url.Error
	if errors.As(err, &failed) {
		return nil, failed.Err // the address is on the line already
	} else if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode > 299 {
		return nil, errors.New(response.Status)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, err
	}
	value, err := run.DecodeShown(body)
	if errors.Is(err, run.ErrLimit) {
		return nil, ErrPython
	}
	return value, err
}

// proxied is whether Python's urllib sends a request to DevTools through a proxy the
// environment names, as its getproxies_environment and proxy_bypass_environment decide.
func proxied() bool {
	proxies := map[string]string{}
	for _, pair := range os.Environ() {
		name, value, _ := strings.Cut(pair, "=")
		if scheme, ok := strings.CutSuffix(strings.ToLower(name), "_proxy"); ok && value != "" {
			proxies[scheme] = value
		}
	}
	if _, cgi := os.LookupEnv("REQUEST_METHOD"); cgi {
		delete(proxies, "http") // a CGI request's HTTP_PROXY is its client's
	}
	for _, pair := range os.Environ() {
		name, value, _ := strings.Cut(pair, "=")
		if scheme, ok := strings.CutSuffix(name, "_proxy"); ok && value != "" {
			proxies[strings.ToLower(scheme)] = value
		} else if ok {
			delete(proxies, strings.ToLower(scheme))
		}
	}
	if proxies["http"] == "" || proxies["no"] == "*" {
		return false
	}
	host := strings.ToLower(strings.TrimPrefix(cdp, "http://"))
	hostOnly, _, _ := strings.Cut(host, ":")
	for _, name := range strings.Split(proxies["no"], ",") { // an empty name matches no host
		name = strings.ToLower(strings.TrimLeft(strings.TrimFunc(name, config.Space), "."))
		for _, each := range []string{hostOnly, host} {
			if each == name || strings.HasSuffix(each, "."+name) {
				return false
			}
		}
	}
	return true
}

// tabs is the reachable cdp line, the tabs line and each page's row, as Python's browser.status
// writes them from DevTools' version and list.
func tabs(version, list any) ([]string, error) {
	about, ok := version.(*run.Object)
	targets, listed := list.([]any)
	if !ok || !listed {
		return nil, ErrPython // Python's .get, or its loop, ends in a traceback on nearly any other
	}
	browser := "unknown build"
	if about.Has("Browser") {
		browser = run.Text(about.Get("Browser"))
	}
	var pages []*run.Object
	for _, target := range targets {
		page, ok := target.(*run.Object)
		if !ok {
			return nil, ErrPython
		}
		if page.Get("type") == "page" {
			pages = append(pages, page)
		}
	}
	rows := []string{fmt.Sprintf("cdp        %s reachable, %s", cdp, browser),
		fmt.Sprintf("tabs       %d open (cap %s; a tab idle %s min is closed by ak watch)", len(pages),
			setting("AK_BROWSER_TAB_CAP", "12"), setting("AK_BROWSER_TAB_IDLE_MIN", "60"))}
	stored := run.NewObject()
	data, err := os.ReadFile(filepath.Join(config.Home(), "state", "browser-tabs.json"))
	if err == nil {
		records, err := run.DecodeShown(data)
		if errors.Is(err, run.ErrLimit) {
			return nil, ErrPython
		}
		if object, ok := records.(*run.Object); ok {
			stored = object
		}
	}
	moment := float64(time.Now().UnixNano()) / 1e9
	for _, page := range pages {
		title, ok := page.Get("title").(string)
		if !ok && page.Truthy("title") {
			return nil, ErrPython // str's strip is all Python calls
		}
		address, ok := page.Get("url").(string)
		if !ok && page.Has("url") {
			return nil, ErrPython
		}
		changed := moment
		switch id := page.Get("id").(type) {
		case []any, *run.Object:
			return nil, ErrPython // no key of a dict, to Python
		case string:
			if record, ok := stored.Get(id).(*run.Object); ok {
				if at, ok := record.Num("last_change"); ok && !(at > moment) {
					changed = at
				}
			}
		}
		seconds := moment - changed
		if math.IsInf(seconds, 0) || math.IsNaN(seconds) {
			return nil, ErrPython // Python's int() of it raises
		}
		idle := "idle " + floorDiv(seconds, 60) + "m"
		if seconds >= 3600 {
			idle = "idle " + floorDiv(seconds, 3600) + "h"
		}
		title = cmp.Or(strings.TrimFunc(title, config.Space), "(untitled)")
		rows = append(rows, fmt.Sprintf("  %-60s %s %s", first(title, 60), first(address, 80), idle))
	}
	return rows, nil
}

// setting is the variable's number as Python's int() reads it where that is 1 or more, else
// fallback: the watch tick's tab cap and idle minutes.
func setting(name, fallback string) string {
	number := config.Int(strings.TrimFunc(os.Getenv(name), config.Space))
	if number == nil || number.Sign() < 1 {
		return fallback
	}
	return number.String()
}

// floorDiv is Python's int(x // y) for a finite x ≥ 0 and a y > 0, rounded as CPython's float
// floor division rounds it.
func floorDiv(x, y float64) string {
	div := (x - math.Mod(x, y)) / y
	floor := math.Floor(div)
	if div-floor > 0.5 {
		floor++
	}
	return strconv.FormatFloat(floor, 'f', 0, 64)
}

// first is the text's first n code points, as Python's text[:n].
func first(text string, n int) string {
	for i := range text {
		if n == 0 {
			return text[:i]
		}
		n--
	}
	return text
}

// novnc is the address websockify was told to listen on, as Python's browser.novnc_url reads it
// from the noVNC unit installed, else from the checkout's copy: "" where neither names one.
func novnc() (string, error) {
	for _, path := range []string{filepath.Join(unitDir, novncUnit),
		filepath.Join(config.Repo(), "browser", "systemd", novncUnit)} {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		if !utf8.Valid(data) {
			return "", ErrPython // Python's read_text raises
		}
		for _, line := range config.SplitLines(string(data)) {
			if !strings.HasPrefix(line, "ExecStart=") {
				continue
			}
			for _, token := range strings.FieldsFunc(line, config.Space) {
				if hostPort.MatchString(token) && token != vnc {
					return "http://" + token + "/vnc.html?autoconnect=1&resize=remote", nil
				}
			}
		}
	}
	return "", nil
}
