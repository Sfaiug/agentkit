package notify

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"math"
	"net"
	"net/http"
	"net/http/httptrace"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tmux"
)

const (
	sinkEnv    = "AK_NOTIFY_SINK" // the suites' destination; it outranks the owner's webhook
	sinkLogEnv = "AK_NOTIFY_SINK_LOG"
	webhookEnv = "AGENTKIT_DISCORD_WEBHOOK"
)

// backoff is the wait before each retry, by the attempts made, in seconds.
var backoff = []float64{60, 180, 600, 1800, 3600}

// sendCard queues the episode's one card under the seat's lock and makes its first attempt; the
// tick's retries take it from there.
func sendCard(name string, card, notice *run.Object, errOut io.Writer) (int, error) {
	page, err := payload(name)
	if err != nil {
		return 0, err
	}
	held, err := holdOutbox()
	if err != nil {
		return 0, err
	}
	defer held.Close()
	key := cardKey(card.Get("episode"))
	event, err := readEvent(key)
	if err != nil {
		return 0, err
	}
	text := notice.Str("text")
	fresh := event == nil
	if fresh {
		event = run.NewObject()
		for _, f := range []field{{"id", key}, {"source", "card:" + card.Str("episode")}, {"episode", card.Get("episode")},
			{"session", name}, {"kind", "needs"}, {"text", text}, {"files", []any{}}, {"payload", page},
			{"message", "Needs you · " + name + ": " + text}, {"created_at", run.Float(clock())},
			{"sink", sink() != ""}, {"status", "pending"}, {"attempts", 0}, {"next_attempt", 0}} {
			event.Set(f.key, f.value)
		}
		if err := writeEvent(event); err != nil {
			return 0, err
		}
	}
	card.Set("sent", true)
	if err := writeCard(name, card); err != nil {
		return 0, err
	}
	if fresh {
		terminalNotice(name, "Needs you · "+name+": "+text)
	}
	return attempt(event, errOut)
}

// attempt sends a queued event once its time has come: 1 only for one blocked, which waits for
// its webhook to be fixed, else 0 for one delivered, disabled or durably retried.
func attempt(event *run.Object, errOut io.Writer) (int, error) {
	id, status := event.Str("id"), event.Str("status")
	if status == "delivered" || status == "disabled" {
		return 0, nil
	}
	// an event reaches only the destination it was queued for: a test's is never the owner's
	if queued := event.Truthy("sink"); queued != (sink() != "") {
		if !queued {
			fmt.Fprintf(errOut, "notify: event %s was queued for the configured webhook; %s is set, so it waits\n", id, sinkEnv)
			return 0, nil
		}
		diverted(fmt.Sprintf("event %s was queued under %s; it is dropped, never delivered to the configured webhook", id, sinkEnv), errOut)
		event.Set("status", "disabled")
		event.Set("error", "queued under "+sinkEnv)
		event.Set("next_attempt", nil)
		return 0, writeEvent(event)
	}
	address, err := webhook(false, errOut)
	if err != nil {
		event.Set("status", "blocked")
		event.Set("error", "cannot read the configured webhook")
		event.Set("next_attempt", nil)
		event.Delete("webhook")
		fmt.Fprintln(errOut, "notify: cannot read the configured webhook; event retained")
		return 1, writeEvent(event)
	}
	fingerprint := digest(address)
	if address == "" && event.Truthy("webhook") && !run.Equal(event.Get("webhook"), fingerprint) {
		// a process missing its caller's environment keeps an event queued for a webhook
		event.Set("status", "blocked")
		event.Set("webhook", fingerprint)
		event.Set("error", "no webhook configured for queued event")
		event.Set("next_attempt", nil)
		if err := writeEvent(event); err != nil {
			return 0, err
		}
	}
	if run.Equal(event.Get("webhook"), fingerprint) {
		if event.Str("status") == "blocked" {
			fmt.Fprintf(errOut, "notify: event %s blocked (%s); fix the webhook configuration\n", id, event.Str("error"))
			return 1, nil
		}
		if next, _ := event.Num("next_attempt"); clock() < next {
			return 0, nil
		}
	}
	attempts, _ := event.Int("attempts")
	attempts++
	delay := backoff[min(attempts, len(backoff))-1]
	event.Set("attempts", attempts)
	event.Set("status", "pending")
	event.Set("webhook", fingerprint)
	event.Set("next_attempt", run.Float(clock()+delay))
	// a sender killed mid-post leaves the event scheduled
	if err := writeEvent(event); err != nil {
		return 0, err
	}
	sent, err := post(event.Dict("payload"), event.Str("message"), errOut)
	if err != nil {
		return 0, err
	}
	// Python also adds the owner's `paged` row to history.db, which Go writes from milestone 5a
	event.Set("status", sent.status)
	receipt := run.NewObject()
	if sent.messageID != "" {
		receipt.Set("message_id", sent.messageID)
		receipt.Set("webhook", sent.webhook)
	}
	event.Set("receipt", receipt)
	if sent.err != "" {
		event.Set("error", sent.err)
	} else {
		event.Delete("error")
	}
	next := any(nil)
	if sent.status == "pending" {
		next = run.Float(clock() + max(delay, sent.retryAfter))
	}
	event.Set("next_attempt", next)
	if err := writeEvent(event); err != nil {
		return 0, err
	}
	if sent.status == "pending" {
		at, _ := run.Num(next)
		fmt.Fprintf(errOut, "notify: event %s queued; retry after %.0f\n", id, at)
	}
	if sent.status == "blocked" {
		return 1, nil
	}
	return 0, nil
}

// A sent is how a post went: its status, why it failed, how long the webhook asked to wait, and
// the message it made with a digest of the webhook that made it, never the webhook itself.
type sent struct {
	status, err, messageID, webhook string
	retryAfter                      float64
}

// post sends the page where pages go, and says on errOut where it went and why it did not.
func post(page *run.Object, message string, errOut io.Writer) (sent, error) {
	address, err := webhook(true, errOut)
	switch {
	case err != nil:
		return sent{}, err
	case address == "" || strings.ToLower(address) == "off":
		fmt.Fprintf(errOut, "notify: no webhook configured; message: %s\n", message)
		return sent{status: "disabled"}, nil
	case !strings.HasPrefix(address, "https://") && !strings.HasPrefix(address, "http://"):
		fmt.Fprintln(errOut, "notify: the configured webhook is not an http(s) URL")
		return sent{status: "blocked", err: "webhook is not an http(s) URL"}, nil
	}
	target, valid := webhookURL(address)
	request, err := http.NewRequest("POST", target, bytes.NewReader([]byte(run.Line(page))))
	if !valid || err != nil {
		fmt.Fprintln(errOut, "notify: webhook POST failed (ValueError)")
		return sent{status: "blocked", err: "ValueError"}, nil
	}
	var wrote atomic.Bool
	request = request.WithContext(httptrace.WithClientTrace(request.Context(), &httptrace.ClientTrace{
		WroteRequest: func(info httptrace.WroteRequestInfo) { wrote.Store(info.Err == nil) },
	}))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("User-Agent", userAgent)
	answer, err := client().Do(request)
	var reply []byte
	if err == nil {
		defer answer.Body.Close()
		if answer.StatusCode/100 != 2 {
			code := answer.StatusCode
			failed := sent{status: "blocked", err: fmt.Sprintf("HTTP %d", code)}
			if code == 408 || code == 429 || code >= 500 {
				failed.status = "pending"
			}
			if code == 429 {
				failed.retryAfter = retryAfter(answer)
			}
			fmt.Fprintf(errOut, "notify: webhook POST failed (HTTP %d)\n", code)
			return failed, nil
		}
		reply, err = io.ReadAll(answer.Body)
	}
	if err != nil {
		name := failure(err, wrote.Load())
		fmt.Fprintf(errOut, "notify: webhook POST failed (%s)\n", name)
		return sent{status: "pending", err: name}, nil
	}
	delivered := sent{status: "delivered"}
	data, _ := run.Decode(reply)
	if made, ok := data.(*run.Object); ok {
		if id := text(made.Get("id")); id != "" && !strings.ContainsFunc(id, func(r rune) bool { return !unicode.IsDigit(r) }) {
			delivered.messageID, delivered.webhook = id, digest(address)
		}
		if mentions, ok := made.Get("mentions").([]any); ok {
			learn(mentions)
		}
	}
	return delivered, nil
}

// webhookURL is the webhook a POST asks, and whether it names a host and a port Python takes:
// its query kept but for `wait`, which is true so that Discord answers with the message it made.
func webhookURL(address string) (string, bool) {
	parsed, err := url.Parse(address)
	if err != nil || parsed.Hostname() == "" {
		return "", false
	}
	if port := parsed.Port(); port != "" {
		if number, err := strconv.Atoi(port); err != nil || number > 65535 {
			return "", false
		}
	}
	rest, _, _ := strings.Cut(address, "#")
	base, query, _ := strings.Cut(rest, "?")
	var pairs []string
	for _, pair := range strings.Split(query, "&") {
		// as parse_qsl reads a pair, a blank value dropped, and as urlencode writes it back
		key, value, _ := strings.Cut(pair, "=")
		if key, value = unquote(key), unquote(value); value != "" && key != "wait" {
			pairs = append(pairs, url.QueryEscape(key)+"="+url.QueryEscape(value))
		}
	}
	return strings.TrimRight(base, "/") + "?" + strings.Join(append(pairs, "wait=true"), "&"), true
}

// unquote is a query's word with its escapes read, or as written where one cannot be.
func unquote(word string) string {
	if read, err := url.QueryUnescape(word); err == nil {
		return read
	}
	return strings.ReplaceAll(word, "+", " ")
}

// failure is the name of Python's error for a POST nothing answered: urllib's URLError until the
// request is written, then the socket's own.
func failure(err error, wrote bool) string {
	var timeout net.Error
	switch {
	case !wrote:
		return "URLError"
	case errors.As(err, &timeout) && timeout.Timeout():
		return "TimeoutError"
	case errors.Is(err, syscall.ECONNRESET):
		return "ConnectionResetError"
	case errors.Is(err, io.ErrUnexpectedEOF):
		return "IncompleteRead"
	}
	return "RemoteDisconnected"
}

// retryAfter is how long a 429 asks to wait, the longer of its header's and its body's, held to
// the backoff's bounds.
func retryAfter(answer *http.Response) float64 {
	delay := 0.0
	header := answer.Header.Get("Retry-After")
	if seconds, err := strconv.ParseFloat(header, 64); err == nil {
		delay = seconds
	} else if when, err := http.ParseTime(header); err == nil {
		delay = time.Until(when).Seconds()
	}
	body, _ := io.ReadAll(answer.Body)
	data, _ := run.Decode(body)
	if asked, ok := data.(*run.Object); ok {
		if seconds, err := strconv.ParseFloat(text(asked.Get("retry_after")), 64); err == nil {
			delay = max(delay, seconds)
		}
	}
	if math.IsInf(delay, 0) || math.IsNaN(delay) {
		return backoff[len(backoff)-1]
	}
	return min(backoff[len(backoff)-1], max(backoff[0], delay))
}

// learn keeps the name Discord gave the owner a delivered card pinged, for the `c` screen's row:
// only the message a card makes names them.  Best effort: the card went either way.
func learn(mentions []any) {
	for _, mention := range mentions {
		user, _ := mention.(*run.Object)
		if user == nil {
			continue
		}
		if name, ok := user.Get("username").(string); ok && user.Truthy("id") {
			known := run.NewObject()
			known.Set("id", text(user.Get("id")))
			known.Set("name", name)
			path := filepath.Join(state(), "discord-user.json")
			if os.WriteFile(strings.TrimSuffix(path, ".json")+".tmp", []byte(run.Line(known)+"\n"), 0o666) == nil {
				os.Rename(strings.TrimSuffix(path, ".json")+".tmp", path)
			}
		}
	}
}

// text is a JSON string or number as Python's str() writes it.
func text(value any) string {
	switch value := value.(type) {
	case string:
		return value
	case run.Number:
		return string(value)
	}
	return ""
}

// sink is the suites' destination, "" outside a test: a URL, or any other word, which posts
// nowhere.
func sink() string {
	return strings.TrimFunc(os.Getenv(sinkEnv), config.Space)
}

// webhook is where a page goes: the sink outranks the configured webhook, always, and `report`
// says on errOut and in $AK_NOTIFY_SINK_LOG that it turned one away, for the suite to fail on.
func webhook(report bool, errOut io.Writer) (string, error) {
	marker := sink()
	if marker == "" {
		return secret(webhookEnv, "discord_webhook")
	}
	target := "off"
	if strings.HasPrefix(marker, "https://") || strings.HasPrefix(marker, "http://") {
		target = marker
	}
	if report {
		if configured, err := secret(webhookEnv, "discord_webhook"); err == nil && configured != "" && configured != target {
			diverted(sinkEnv+" is set; this notification went to the test sink and not to the configured webhook", errOut)
		}
	}
	return target, nil
}

func diverted(line string, errOut io.Writer) {
	fmt.Fprintln(errOut, "notify: "+line)
	if path := os.Getenv(sinkLogEnv); path != "" {
		if file, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666); err == nil {
			fmt.Fprintln(file, line)
			file.Close()
		}
	}
}

// terminalNotice shows text on each terminal looking at ak's server, never at the seat it is
// about, best effort: a pane's own terminal through tmux, or a client's where tmux cannot pass
// it on, once a window.
func terminalNotice(seat, text string) {
	clients, err := tmux.Ask(tmux.Own(), "list-clients", "-F",
		"#{client_tty}\t#{session_name}\t#{window_id}\t#{pane_tty}\t#{pane_dead}\t#{client_control_mode}")
	if err != nil {
		return
	}
	var looking [][]string
	excluded := map[string]bool{} // windows shared with the seat, and panes exited on stale ttys
	for _, line := range config.SplitLines(clients) {
		client := strings.Split(line, "\t")
		if len(client) < 2 || len(client) > 6 {
			continue
		}
		client = append(client, make([]string, 6-len(client))...)
		if client[5] == "1" {
			continue // a control-mode client has no terminal
		}
		looking = append(looking, client)
		if client[1] == seat || client[4] != "0" {
			excluded[client[2]] = true
		}
	}
	osc := "\x1b]9;" + notice(text) + "\a"
	written, passing := map[string]bool{}, false
	var targets [][2]string // each terminal and what it is sent
	for _, client := range looking {
		tty, attached, window, pane := client[0], client[1], client[2], client[3]
		if attached == "" || attached == seat {
			continue
		}
		passthrough := pane != "" && window != "" && !excluded[window]
		target, key, sequence := tty, tty, osc
		if passthrough {
			target, key = pane, window
			sequence = "\x1bPtmux;" + strings.ReplaceAll(osc, "\x1b", "\x1b\x1b") + "\x1b\\"
		}
		if !written[key] && strings.HasPrefix(target, "/dev/") {
			written[key], passing = true, passing || passthrough
			targets = append(targets, [2]string{target, sequence})
		}
	}
	if passing {
		// a server started before seats asked for it passes nothing on
		tmux.Ask(tmux.Own(), "set-option", "-g", "allow-passthrough", "on")
	}
	for _, target := range targets {
		terminal.Write(target[0], []byte(target[1]))
	}
}

func outbox() string { return filepath.Join(state(), "notification-outbox") }

// holdOutbox takes the outbox's lock, after the seat's, its folder made and on the disk first.
func holdOutbox() (*os.File, error) {
	if err := config.EnsureDirs(); err != nil {
		return nil, err
	}
	if err := os.Mkdir(outbox(), 0o700); err != nil && !errors.Is(err, fs.ErrExist) {
		return nil, err
	}
	for _, dir := range []string{state(), config.Home(), filepath.Dir(config.Home())} {
		syncDir(dir)
	}
	return lock.Wait(context.Background(), filepath.Join(outbox(), ".lock"))
}

// cardKey is the outbox id of an episode's one card, a test's apart from the owner's.
func cardKey(episode any) string {
	return digest(run.Line([]any{"card", episode, sink() != ""}))
}

// readEvent is the outbox's event of that id, nil for none, and an error where Python fails on it.
func readEvent(id string) (*run.Object, error) {
	return readObject(filepath.Join(outbox(), id+".json"))
}

// writeEvent puts the event in the outbox whole and on the disk; it never holds the webhook.
func writeEvent(event *run.Object) error {
	path := filepath.Join(outbox(), event.Str("id")+".json")
	defer os.Remove(strings.TrimSuffix(path, ".json") + ".tmp")
	if err := durable(path, 0o600, event); err != nil {
		return err
	}
	syncDir(outbox())
	return nil
}

// durable writes value to path whole and on the disk, through a temporary file beside it.
func durable(path string, mode os.FileMode, value *run.Object) error {
	tmp := strings.TrimSuffix(path, ".json") + ".tmp"
	file, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, mode)
	if err != nil {
		return err
	}
	_, err = file.WriteString(run.Line(value) + "\n")
	if err == nil {
		err = file.Sync()
	}
	if closed := file.Close(); err == nil {
		err = closed
	}
	if err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// syncDir puts a folder's entries on the disk, where the system can.
func syncDir(path string) {
	if dir, err := os.Open(path); err == nil {
		dir.Sync()
		dir.Close()
	}
}

func digest(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}
