// Package notify owns what a page says, who may ask and where pages go.  It hides a page's
// title, the owner's mention, where its id and the webhook come from ($AGENTKIT_DISCORD_USER_ID
// and $AGENTKIT_DISCORD_WEBHOOK, else the secrets file), how the webhook is asked whether it is
// live, the terminal notice's text, the rule that a question asks first, and a worker's
// suppression: a run's worker asks the owner nothing.  Sending, cards and the outbox join it
// later.
package notify

import (
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// askCap is where a question must have asked: a seat's bar and its menu row show a question
// from its start and cut the rest, so context written before the ask hides it.  One classic
// terminal line.
const askCap = 80

// ErrUnread is text Go cannot read as Python does, which leaves the command to Python.
var ErrUnread = errors.New("not UTF-8, or unreadable")

// Suppressed says why a run's worker asks nothing, on out and, outside a dry run, in the run's
// log; false outside a worker.  A worker's descendants inherit the guard and the log.
func Suppressed(dryRun bool, out io.Writer) bool {
	if os.Getenv("AK_RUN_ROLE") != "worker" {
		return false
	}
	line := "notify: needs suppressed: AK_RUN_ROLE=worker; only an orchestrator may notify"
	fmt.Fprintln(out, line)
	if log := os.Getenv("AK_RUN_LOG"); log != "" && !dryRun {
		if file, err := os.OpenFile(log, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666); err == nil {
			fmt.Fprintf(file, "[%s] %s\n", time.Now().Format("15:04:05"), line)
			file.Close()
		}
	}
	return true
}

// AsksFirst refuses a question whose "?" is not within its first askCap characters, counted
// as the bar shows them: from the first word, a run of spaces or line breaks as one.
func AsksFirst(question string) error {
	if !utf8.ValidString(question) {
		return ErrUnread
	}
	asked, _, found := strings.Cut(config.Fold(question), "?")
	if !found || utf8.RuneCountInString(asked) >= askCap {
		return fmt.Errorf(`put the question first, its "?" within %d characters: the status bar `+
			"and the menu show a question's start; context goes after it", askCap)
	}
	return nil
}

// DryRun shows what asking the question for the seat ("" outside one) would send, and sends
// nothing: the page as JSON on out, the terminal notice, which alone carries the question, on
// errOut.
func DryRun(seat, question string, out, errOut io.Writer) error {
	page, err := payload(seat)
	if err != nil {
		return err
	}
	fmt.Fprintln(out, run.Encode(page))
	fmt.Fprintln(errOut, "terminal notice: "+notice(fmt.Sprintf("Needs you · %s: %s", about(seat), question)))
	return nil
}

// payload is what a page posts: its title, then the owner's mention, the only one it may ping.
// What was asked stays in the seat.
func payload(seat string) (*run.Object, error) {
	owner, err := ownerID()
	if err != nil {
		return nil, err
	}
	page, mentions := run.NewObject(), run.NewObject()
	page.Set("username", "agentkit")
	content := "\U0001f64b Needs you · " + about(config.Fold(seat)) // 🙋 a seat with its hand up
	if owner != "" {
		content += " <@" + owner + ">"
		mentions.Set("users", []any{owner})
	} else {
		mentions.Set("parse", []any{})
	}
	page.Set("content", content)
	page.Set("allowed_mentions", mentions)
	return page, nil
}

// ownerID is the owner's Discord id; "" for none.
func ownerID() (string, error) {
	return secret("AGENTKIT_DISCORD_USER_ID", "discord_user_id")
}

// Check asks the webhook with a GET, which posts nothing, whatever $AK_NOTIFY_SINK says: Discord
// answers it with the hook.  It says how the webhook answered and whether that was 200; the
// error is for none configured, or ErrUnread.
func Check(out, errOut io.Writer) (bool, error) {
	url, err := secret("AGENTKIT_DISCORD_WEBHOOK", "discord_webhook")
	if err != nil {
		return false, err
	}
	if url == "" {
		return false, fmt.Errorf("--check: no webhook configured; put one in %s or "+
			"$AGENTKIT_DISCORD_WEBHOOK", secretsFile("discord_webhook"))
	}
	if !strings.HasPrefix(url, "https://") && !strings.HasPrefix(url, "http://") {
		fmt.Fprintln(errOut, "notify: fail (the configured webhook is not an http(s) URL)")
		return false, nil
	}
	status, err := get(url)
	if err != nil {
		fmt.Fprintf(errOut, "notify: fail (%s)\n", why(err))
		return false, nil
	}
	if status != http.StatusOK {
		fmt.Fprintf(out, "notify: fail (%d)\n", status)
		return false, nil
	}
	fmt.Fprintln(out, "notify: ok (200)")
	return true, nil
}

// get is url's status once its whole answer has come, asked as Python asks: its User-Agent,
// and giving up after its 15 seconds.
func get(url string) (int, error) {
	request, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return 0, err
	}
	request.Header.Set("User-Agent", "agentkit/1 (+https://github.com)")
	answer, err := (&http.Client{Timeout: 15 * time.Second}).Do(request)
	if err != nil {
		return 0, err
	}
	defer answer.Body.Close()
	_, err = io.Copy(io.Discard, answer.Body)
	return answer.StatusCode, err
}

// why is why the webhook did not answer, in words Go writes itself, never the error's text: the
// URL is the secret, and a server, its certificate or its redirects can echo any part of it there.
func why(err error) string {
	var timeout net.Error
	var dns *net.DNSError
	switch {
	case errors.As(err, &timeout) && timeout.Timeout():
		return "no response: timed out"
	case errors.As(err, &dns) && dns.IsNotFound:
		return "no response: no such host"
	case errors.Is(err, syscall.ECONNREFUSED):
		return "no response: connection refused"
	}
	return "no response"
}

// secret is $env, else the one line of the secrets file name; "" for none.
func secret(env, name string) (string, error) {
	value := os.Getenv(env)
	if value == "" {
		data, err := os.ReadFile(secretsFile(name))
		if os.IsNotExist(err) {
			return "", nil
		}
		if err != nil {
			return "", ErrUnread
		}
		// Python reads the file in universal newlines mode
		value = strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(string(data))
	}
	if !utf8.ValidString(value) {
		return "", ErrUnread
	}
	return strings.TrimFunc(value, config.Space), nil
}

// secretsFile is where the secret name is kept outside the environment.
func secretsFile(name string) string {
	return filepath.Join(config.Home(), "secrets", name)
}

// notice is text as a terminal notice shows it: on one line, each character Python's
// str.isprintable() rejects a space, at most 1000 characters.
func notice(text string) string {
	text = config.Fold(strings.Map(func(r rune) rune {
		if unicode.IsPrint(r) {
			return r
		}
		return ' '
	}, text))
	runes := []rune(text)
	return string(runes[:min(len(runes), 1000)])
}

// about is the seat a page is about, or agentkit outside a seat.
func about(seat string) string {
	if seat == "" {
		return "agentkit"
	}
	return seat
}
