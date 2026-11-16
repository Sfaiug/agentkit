package harness

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// claudeEndpoint is a HOME whose curl is Anthropic's usage endpoint, answering the file `body` with
// the HTTP code in `code` and the response headers in `headers`, and the prepaid credits ask with
// `prepaid`, failing where there is none; it logs each ask's words to `asked`, and the headers it
// was handed, those on its stdin first, to `sent`.  Its claude is version 2.1.400, and its
// `security` holds no Keychain entry.  The seat's own login there holds an access token, live.
func claudeEndpoint(t *testing.T) (home string, write func(path, text string)) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake curl is a shell script")
	}
	home = t.TempDir()
	write = func(path, text string) {
		path = filepath.Join(home, path)
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(text), 0o700)
	}
	write("bin/curl", `#!/bin/sh
printf '%s\n' "$*" >> "$HOME/asked"
for arg; do
  case $prev in
  -D) dump=$arg ;;
  -H) case $arg in @-) cat ;; *) printf '%s\n' "$arg" ;; esac >> "$HOME/sent" ;;
  esac
  case $arg in https://*) url=$arg ;; esac
  prev=$arg
done
case $url in
*/prepaid/credits) cat "$HOME/prepaid" 2>/dev/null || exit 22 ;;
*) cat "$HOME/headers" > "$dump" 2>/dev/null; printf '%s\n%s' "$(cat "$HOME/body")" "$(cat "$HOME/code")" ;;
esac
`)
	write("bin/claude", "#!/bin/sh\necho '2.1.400 (Claude Code)'\n")
	write("bin/security", "#!/bin/sh\nexit 44\n")
	write(".claude/.credentials.json", fmt.Sprintf(`{"claudeAiOauth": {"accessToken": "seat-acme", "expiresAt": %d}}`,
		time.Now().Add(time.Hour).UnixMilli()))
	write("code", "200")
	for key, value := range map[string]string{"HOME": home, "AGENTKIT_ADAPTER_DIR": "", "AGENTKIT_ACCOUNT": "",
		"CLAUDE_CONFIG_DIR": "", "CLAUDE_CODE_OAUTH_TOKEN": "",
		"PATH": filepath.Join(home, "bin") + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	return home, write
}

// usageSaid is what `usage` answers for the login the environment names, as one line of JSON
// whatever its spacing.
func usageSaid(t *testing.T) string {
	t.Helper()
	login, _, err := config.Account("claude")
	if err != nil {
		t.Fatal(err)
	}
	said := Usage("claude")(login)
	value, err := run.Decode([]byte(said))
	if err != nil {
		t.Fatalf("answered no JSON: %q", said)
	}
	return run.Line(value)
}

// line is that JSON as usageSaid writes it.
func line(t *testing.T, text string) string {
	t.Helper()
	value, err := run.Decode([]byte(text))
	if err != nil {
		t.Fatal(err)
	}
	return run.Line(value)
}

// A 200 reads as claude.sh's jq reads it: a meter for each limit with a reset and a percentage, one
// model's own cap naming it; the unpaused grants with resets left, by kind, one giving its use back
// to the week of that model's name; no credits asked where extra usage is off.  It asks once, on
// the seat's own token, naming the claude it runs as, and leaves nothing in ak's tmp.
func TestClaudeUsageReadsTheMetersOfA200(t *testing.T) {
	home, write := claudeEndpoint(t)
	write("body", `{"limits": [
  {"kind": "five_hour", "group": "session", "percent": 12, "resets_at": "2026-11-15T10:00:00.123456+00:00"},
  {"kind": "seven_day", "group": "weekly", "percent": 40.5, "resets_at": "2026-11-20T05:00:00Z"},
  {"kind": "seven_day_fable", "group": "weekly", "percent": 90, "resets_at": "2026-11-20T05:00:00+00:00",
   "scope": {"model": {"display_name": "Fable"}}},
  {"kind": "overage", "group": "weekly", "percent": null, "resets_at": null}],
 "cedar_ember": {"eligible": true, "grants": [
  {"type": "session", "resets_left": 2, "usable_now": true},
  {"gives_back_weekly": true, "type": "weekly", "resets_left": 1},
  {"clears": ["five_hour", "seven_day"], "resets_left": 1, "paused": true},
  {"clears": ["seven_day"], "resets_left": 3},
  {"clears": ["five_hour", "seven_day"], "resets_left": 0}]},
 "extra_usage": {"is_enabled": false}}`)
	said := usageSaid(t)
	session := time.Date(2026, 11, 15, 10, 0, 0, 0, time.UTC).Unix()
	week := time.Date(2026, 11, 20, 5, 0, 0, 0, time.UTC).Unix()
	want := line(t, fmt.Sprintf(`{"provider": "anthropic", "error": null, "meters": [
  {"name": "five_hour", "used": 12, "resets_at": %d, "window_secs": 18000},
  {"name": "seven_day", "used": 40.5, "resets_at": %d, "window_secs": 604800},
  {"name": "seven_day_fable", "used": 90, "resets_at": %[2]d, "window_secs": 604800, "scope": "Fable"}],
 "resets": 6, "reset_kinds": [{"kind": "5-hour", "left": 2, "usable": true},
  {"kind": "weekly", "left": 3, "usable": false}, {"kind": "Fable", "left": 1, "usable": false}]}`, session, week))
	if said != want {
		t.Fatal(said)
	}
	if asks := asked(t, home); strings.Count(asks, "https://") != 1 || !strings.Contains(asks, "https://api.anthropic.com/api/oauth/usage?cedar_ember=1") {
		t.Errorf("asked %q", asks)
	}
	sent, _ := os.ReadFile(filepath.Join(home, "sent"))
	if !strings.HasPrefix(string(sent), "Authorization: Bearer seat-acme\n") ||
		!strings.Contains(string(sent), "\nUser-Agent: claude-cli/2.1.400 (external, cli)\n") {
		t.Errorf("sent %q", sent)
	}
	if left, _ := os.ReadDir(filepath.Join(home, ".agentkit", "tmp")); len(left) != 0 {
		t.Errorf("left %v in tmp", left)
	}
}

// Only where extra usage is on is the organization's prepaid balance asked, under its id: what is
// left is the smaller of the month's limit and the balance, in units of its currency, `unlimited`
// with no limit and auto-reload on.
func TestClaudeUsageAsksTheCreditsOnlyWhereExtraUsageIsOn(t *testing.T) {
	home, write := claudeEndpoint(t)
	write(".claude.json", `{"oauthAccount": {"organizationUuid": "0f3a9c2e-1b2d"}}`)
	write("prepaid", `{"amount": 2000, "auto_reload_settings": {"enabled": false}}`)
	for _, each := range []struct{ extra, credits string }{
		{`{"is_enabled": true, "monthly_limit": 5000, "used_credits": 1250, "currency": "eur", "decimal_places": 2}`,
			`, "credits": 20, "currency": "EUR"`},
		{`{"is_enabled": true, "monthly_limit": 5000, "used_credits": 4000, "decimal_places": 2}`,
			`, "credits": 10, "currency": "USD"`},
		{`{"is_enabled": true, "monthly_limit": null, "decimal_places": 2}`, `, "credits": 20, "currency": "USD"`},
	} {
		write("body", `{"limits": [], "extra_usage": `+each.extra+`}`)
		said := usageSaid(t)
		if want := line(t, `{"provider": "anthropic", "error": null, "meters": [], "resets": 0, "reset_kinds": []`+each.credits+`}`); said != want {
			t.Errorf("%s: %s", each.extra, said)
		}
		if asks := asked(t, home); !strings.Contains(asks, "https://api.anthropic.com/api/oauth/organizations/0f3a9c2e-1b2d/prepaid/credits") {
			t.Errorf("%s: asked %q", each.extra, asks)
		}
	}
	if sent, _ := os.ReadFile(filepath.Join(home, "sent")); !strings.Contains(string(sent), "\nx-organization-uuid: 0f3a9c2e-1b2d\n") {
		t.Errorf("sent %q", sent)
	}
	write("prepaid", `{"amount": 2000, "auto_reload_settings": {"enabled": true}}`)
	write("body", `{"limits": [], "extra_usage": {"is_enabled": true, "monthly_limit": null, "decimal_places": 2}}`)
	if said := usageSaid(t); !strings.HasSuffix(said, `"credits": "unlimited", "currency": "USD"}`) {
		t.Errorf("auto-reload: %s", said)
	}
	asked(t, home)
	write("body", `{"limits": [], "extra_usage": {"is_enabled": false, "monthly_limit": 5000, "used_credits": 0}}`)
	if said := usageSaid(t); strings.Contains(said, "credits") || strings.Contains(asked(t, home), "prepaid") {
		t.Errorf("extra usage off: %s", said)
	}
}

// Not 200 is the error object, a refused login's saying so; the endpoint's Retry-After, seconds or
// a date, is `retry_after` in seconds from now, and nothing else is asked.
func TestClaudeUsageSaysWhenToAskAgainAfterARefusal(t *testing.T) {
	home, write := claudeEndpoint(t)
	write("body", `{"error": {"type": "rate_limit_error"}, "extra_usage": {"is_enabled": true}}`)
	write(".claude.json", `{"oauthAccount": {"organizationUuid": "0f3a9c2e-1b2d"}}`)
	write("code", "429")
	refusal := `{"provider": "anthropic", "meters": [], "error": "unknown: HTTP 429 from api.anthropic.com/api/oauth/usage"`
	write("headers", "HTTP/2 429\r\nretry-after: 0120 \r\n\r\n")
	if said := usageSaid(t); said != line(t, refusal+`, "retry_after": 120}`) {
		t.Errorf("seconds: %s", said)
	}
	write("headers", "HTTP/2 429\r\nRetry-After: "+time.Now().Add(time.Hour).UTC().Format(http.TimeFormat)+"\r\n\r\n")
	said := usageSaid(t)
	value, _ := run.Decode([]byte(said))
	if retry, _ := value.(*run.Object).Num("retry_after"); retry < 3590 || retry > 3600 {
		t.Errorf("a date: %s", said)
	}
	write("headers", "HTTP/2 429\r\n\r\n")
	if said := usageSaid(t); said != line(t, refusal+"}") {
		t.Errorf("none: %s", said)
	}
	if asks := asked(t, home); strings.Contains(asks, "prepaid") {
		t.Errorf("asked %q", asks)
	}
	write("code", "401")
	if said := usageSaid(t); !strings.HasSuffix(said, `HTTP 401 from api.anthropic.com/api/oauth/usage; token may be expired, run 'claude' once to refresh"}`) {
		t.Errorf("refused: %s", said)
	}
}

// A seat login that has ended gives way to the worker token; with neither there is no token, and
// nothing is asked.
func TestClaudeUsageAsksOnTheWorkerTokenOnceTheSeatsHasEnded(t *testing.T) {
	home, write := claudeEndpoint(t)
	write("body", `{"limits": []}`)
	write(".claude/.credentials.json", `{"claudeAiOauth": {"accessToken": "seat-acme", "expiresAt": 1700000000000}}`)
	write(".agentkit/secrets/claude_oauth_token", "worker-acme\n")
	if said := usageSaid(t); !strings.Contains(said, `"meters": []`) || strings.Contains(said, "unknown") {
		t.Errorf("worker token: %s", said)
	}
	if sent, _ := os.ReadFile(filepath.Join(home, "sent")); !strings.Contains(string(sent), "Authorization: Bearer worker-acme\n") {
		t.Errorf("sent %q", sent)
	}
	asked(t, home)
	os.Remove(filepath.Join(home, ".agentkit/secrets/claude_oauth_token"))
	said := usageSaid(t)
	value, _ := run.Decode([]byte(said))
	if why := value.(*run.Object).Str("error"); !strings.HasPrefix(why, "unknown: no Claude Code OAuth token (") || asked(t, home) != "" {
		t.Errorf("none: %s", said)
	}
}

// A seat login holding a refresh token counts as lapsed, so `usage`, like `auth`, renews it by one
// turn of claude before asking on it, once it has ended or in its last 270 seconds, as claude.sh's
// lapsed() reads it, though it still signs in until its end; one with longer left does not.
func TestAClaudeLoginInItsLast270SecondsCountsAsLapsed(t *testing.T) {
	_, write := claudeEndpoint(t)
	login, _, err := config.Account("claude")
	if err != nil {
		t.Fatal(err)
	}
	for _, left := range []time.Duration{-10 * time.Second, 260 * time.Second, 280 * time.Second} {
		write(".claude/.credentials.json", fmt.Sprintf(`{"claudeAiOauth": {"accessToken": "seat-acme", "refreshToken": "r", "expiresAt": %d}}`,
			time.Now().Add(left).UnixMilli()))
		if answer, _ := Auth("claude", login, true); answer.Lapsed != (left < 270*time.Second) || answer.Yes != (left > 0) {
			t.Errorf("%v left: %+v", left, answer)
		}
	}
}
