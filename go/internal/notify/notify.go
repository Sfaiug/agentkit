// Package notify owns what a page says and who may ask.  It hides a page's title, the owner's
// mention, where the owner's id and the webhook come from (the environment, else the secrets
// file), how the webhook is asked whether it is live, the terminal notice's text, the rule that
// a question asks first, and a worker's suppression: a run's worker asks the owner nothing.
// Sending, cards and the outbox join it later.
package notify

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptrace"
	"net/url"
	"os"
	"path/filepath"
	"strings"
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

const (
	webhookEnv  = "AGENTKIT_DISCORD_WEBHOOK"
	webhookFile = "discord_webhook"
)

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

// Check asks the configured webhook whether it is live and says how it answered, returning
// ak's exit code.  Its GET pages nobody, so $AK_NOTIFY_SINK never changes which webhook is
// asked.  An error asks nothing: ErrUnread, or no webhook configured.
func Check(out, errOut io.Writer) (int, error) {
	hook, err := secret(webhookEnv, webhookFile)
	if err != nil {
		return 0, err
	}
	if hook == "" {
		return 0, fmt.Errorf("--check: no webhook configured; put one in %s or $%s", secretPath(webhookFile), webhookEnv)
	}
	if !strings.HasPrefix(hook, "https://") && !strings.HasPrefix(hook, "http://") {
		fmt.Fprintln(errOut, "notify: fail (the configured webhook is not an http(s) URL)")
		return 1, nil
	}
	status, err := answer(hook)
	if err != nil {
		fmt.Fprintf(errOut, "notify: fail (%s)\n", err)
		return 1, nil
	}
	if status != http.StatusOK {
		fmt.Fprintf(out, "notify: fail (%d)\n", status)
		return 1, nil
	}
	fmt.Fprintln(out, "notify: ok (200)")
	return 0, nil
}

// answer is the status the URL answers a GET with; a 200 cut off is no answer.
func answer(hook string) (int, error) {
	connected := false
	// what a failure may say: once Go holds a connection to ask on, the server knows the token,
	// the secret, and may echo it in whatever Go's errors quote, a header or a Location
	unanswered := func(err error) (int, error) {
		if connected {
			return 0, errors.New("no response")
		}
		var quoting *url.Error
		if errors.As(err, &quoting) {
			err = quoting.Err // it quotes the URL
		}
		return 0, fmt.Errorf("no response: %w", err)
	}
	trace := &httptrace.ClientTrace{GotConn: func(httptrace.GotConnInfo) { connected = true }}
	request, err := http.NewRequestWithContext(httptrace.WithClientTrace(context.Background(), trace), http.MethodGet, hook, nil)
	if err != nil {
		return unanswered(err)
	}
	request.Header.Set("User-Agent", "agentkit/1 (+https://github.com)")
	client := &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(next *http.Request, via []*http.Request) error {
		next.Header.Del("Referer") // Go's, which would hand the secret URL to where it redirects
		if len(via) >= 10 {
			return http.ErrUseLastResponse // past Python's 10, the redirect is the answer
		}
		return nil
	}}
	response, err := client.Do(request)
	if err != nil {
		return unanswered(err)
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusOK {
		if _, err = io.Copy(io.Discard, response.Body); err != nil {
			return unanswered(err)
		}
	}
	return response.StatusCode, nil
}

// payload is what a page posts: its title, then the owner's mention, the only one it may ping.
// What was asked stays in the seat.
func payload(seat string) (*run.Object, error) {
	owner, err := secret("AGENTKIT_DISCORD_USER_ID", "discord_user_id")
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

// secret is $variable, else the one line of the secrets file; "" for none.
func secret(variable, file string) (string, error) {
	value := os.Getenv(variable)
	if value == "" {
		data, err := os.ReadFile(secretPath(file))
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

func secretPath(file string) string {
	return filepath.Join(config.Home(), "secrets", file)
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
