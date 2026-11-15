package harness

import (
	"cmp"
	"errors"
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// usageEndpoint is the usage page Claude Code reads its login's limits from, its resets asked too.
const usageEndpoint = "https://api.anthropic.com/api/oauth/usage?cedar_ember=1"

// retryAfter is the header an endpoint names its own not-before in, whatever its case.
var retryAfter = regexp.MustCompile(`(?im)^retry-after:[ \t]*(.*)$`)

// claudeUsage is claude.sh's `usage` for the login, its renewal aside: its subscription's meters as
// the usage endpoint answers them, each limit one model's or one surface's own cap naming it in
// `scope`, and the credits extra usage has left.  Asked as Claude Code asks it, through curl with
// the headers on its stdin, in no argument list and no file, on the seat's own login while it
// has not ended, else the worker token, never both: a second ask kept both inside one 429.
func claudeUsage(login config.Login) *run.Object {
	file, _ := config.WorkerToken("claude", login)
	creds, _, oauth := claudeLogin(login)
	token, _ := oauth.Get("accessToken").(string)
	if ends, dated := claudeEnds(oauth); !dated || ends <= time.Now().Unix()*1000 {
		token = ""
	}
	if token == "" {
		token = claudeWorkerToken(login)
	}
	if token == "" {
		return unknown("no Claude Code OAuth token (" + file + " / macOS Keychain 'Claude Code-credentials' / " + creds + "); run 'claude' once to log in")
	}
	version, _ := claudeCommand("claude", "--version").Output()
	first, _, _ := strings.Cut(strings.TrimRight(string(version), "\n"), " ")
	headers := "Authorization: Bearer " + token + "\nanthropic-beta: oauth-2025-04-20\nanthropic-version: 2023-06-01\n" +
		"User-Agent: claude-cli/" + first + " (external, cli)\n"
	tmp := filepath.Join(config.Home(), "tmp")
	os.MkdirAll(tmp, 0o700)
	dump, err := os.CreateTemp(tmp, ".hdr.")
	if err != nil {
		return unknown("cannot create header file in " + tmp)
	}
	dump.Close()
	defer os.Remove(dump.Name())
	curl := claudeCommand("curl", "-s", "-m", "10", "-w", "\n%{http_code}", "-H", "@-", "-D", dump.Name(), usageEndpoint)
	curl.Stdin = strings.NewReader(headers)
	said, err := curl.Output()
	if errors.Is(err, exec.ErrNotFound) {
		return unknown("curl is required")
	}
	body, code := string(said), ""
	if cut := strings.LastIndexByte(strings.TrimRight(body, "\n"), '\n'); cut >= 0 {
		body, code = body[:cut], strings.TrimRight(body[cut+1:], "\n")
	}
	if code != "200" {
		why := "HTTP " + cmp.Or(code, "000") + " from api.anthropic.com/api/oauth/usage"
		if code == "401" || code == "403" { // only a refused login is the token's fault
			why += "; token may be expired, run 'claude' once to refresh"
		}
		answer := unknown(why)
		if retry := claudeRetry(dump.Name()); retry > 0 {
			answer.Set("retry_after", int(retry))
		}
		return answer
	}
	reading, err := run.Decode([]byte(body))
	meters, read := claudeMeters(reading)
	if err != nil || !read {
		return unknown("unparsable response from api.anthropic.com")
	}
	answer := run.NewObject()
	answer.Set("provider", "anthropic")
	answer.Set("error", nil)
	answer.Set("meters", meters)
	if extra, _ := at(reading, "extra_usage").(*run.Object); extra != nil && extra.Get("is_enabled") == true {
		claudeCredits(answer, extra, claudePrepaid(login, headers))
	}
	return answer
}

// claudeWorkerToken is the worker token as claude.sh finds it, from the environment or its file;
// "" for none.
func claudeWorkerToken(login config.Login) string {
	file, variable := config.WorkerToken("claude", login)
	if token := getenv(login, variable); token != "" {
		return token
	}
	data, _ := os.ReadFile(file)
	return strings.TrimRight(string(data), "\n")
}

// unknown is the answer of a read that found no meters, and why, as claude.sh's `err` writes it.
func unknown(why string) *run.Object {
	answer := run.NewObject()
	answer.Set("provider", "anthropic")
	answer.Set("meters", []any{})
	answer.Set("error", "unknown: "+strings.ReplaceAll(strings.ReplaceAll(why, `\`, ""), `"`, "'"))
	return answer
}

// claudeRetry is the endpoint's own not-before in the headers that file holds, in seconds from now:
// its delay seconds, leading zeros decimal, or the HTTP date to wait for; 0 where it named none
// still ahead, and the harness's own fifteen minutes stand.
func claudeRetry(file string) int64 {
	headers, _ := os.ReadFile(file)
	found := retryAfter.FindAllSubmatch(headers, -1)
	if len(found) == 0 {
		return 0
	}
	raw := strings.TrimRightFunc(strings.ReplaceAll(string(found[len(found)-1][1]), "\r", ""), unicode.IsSpace)
	if digits.MatchString(raw) {
		secs, _ := strconv.ParseInt(raw, 10, 64)
		return secs
	}
	at, err := http.ParseTime(raw)
	if err != nil {
		return 0
	}
	return max(0, at.Unix()-time.Now().Unix())
}

// claudeMeters is each limit of the endpoint's reading that names its reset and its used%, as one
// meter: its kind's name, a week's window unless it is the session's, and whose cap it is where its
// `scope` names its model's `display_name`, else its surface's; false where its limits cannot be
// read so.
func claudeMeters(reading any) ([]any, bool) {
	limits, ok := at(reading, "limits").([]any)
	if !ok {
		return nil, false
	}
	meters := []any{}
	for _, each := range limits {
		limit, ok := each.(*run.Object)
		if !ok || limit.Get("resets_at") == nil || limit.Get("percent") == nil {
			if each != nil && !ok {
				return nil, false
			}
			continue
		}
		stamp, ok := limit.Get("resets_at").(string)
		if !ok {
			return nil, false
		}
		if cut := fraction.FindStringIndex(stamp); cut != nil {
			stamp = stamp[:cut[0]] + stamp[cut[1]:]
		}
		if utc, cut := strings.CutSuffix(stamp, "+00:00"); cut {
			stamp = utc + "Z"
		}
		resets, err := time.Parse("2006-01-02T15:04:05Z", stamp)
		if err != nil {
			return nil, false
		}
		window := 604800
		if limit.Get("group") == "session" {
			window = 18000
		}
		meter := run.NewObject()
		meter.Set("name", limit.Get("kind"))
		meter.Set("used", limit.Get("percent"))
		meter.Set("resets_at", int(resets.Unix()))
		meter.Set("window_secs", window)
		for _, whose := range []string{"model", "surface"} {
			if name, _ := at(limit, "scope", whose, "display_name").(string); name != "" {
				meter.Set("scope", name)
				break
			}
		}
		meters = append(meters, meter)
	}
	return meters, true
}

// fraction is the first fraction of a second a reset is written with, which the reading drops.
var fraction = regexp.MustCompile(`\.[0-9]+`)

// at is what value holds at those keys, each an object's; nil where one is not.
func at(value any, keys ...string) any {
	for _, key := range keys {
		object, ok := value.(*run.Object)
		if !ok {
			return nil
		}
		value = object.Get(key)
	}
	return value
}

// claudePrepaid is the prepaid balance of the organization this login belongs to, as Claude Code
// keeps it beside the login, nil where it names none or the balance cannot be read.
func claudePrepaid(login config.Login, headers string) *run.Object {
	data, _ := os.ReadFile(config.LoginPath("claude", "who", login))
	who, _ := run.Decode(data)
	org, _ := at(who, "oauthAccount", "organizationUuid").(string)
	if org == "" || strings.Trim(org, "0123456789abcdef-") != "" {
		return nil
	}
	curl := claudeCommand("curl", "-sf", "-m", "5", "https://api.anthropic.com/api/oauth/organizations/"+org+"/prepaid/credits",
		"-H", "@-", "-H", "x-organization-uuid: "+org)
	curl.Stdin = strings.NewReader(headers)
	said, _ := curl.Output()
	value, _ := run.Decode(said)
	prepaid, _ := value.(*run.Object)
	return prepaid
}

// claudeCredits sets on answer what extra usage has left, as Claude Code counts it: the smaller of
// what its monthly limit has left and the prepaid balance, the limit unbounded when none is set
// and the balance while auto-reload tops it up, both unbounded `unlimited`.  The amounts are minor
// units of its `currency`, `decimal_places` of them to the unit.  The one-time credit adds nothing,
// as it adds nothing there; a balance or limit that cannot be read counts none.
func claudeCredits(answer, extra, prepaid *run.Object) {
	if prepaid == nil {
		return
	}
	exponent := extra.Get("decimal_places")
	if exponent == nil || exponent == false {
		exponent = at(prepaid, "balance", "money", "exponent")
	}
	limit := math.Inf(1)
	if extra.Get("monthly_limit") != nil {
		monthly, ok := run.Num(extra.Get("monthly_limit"))
		spent, counted := run.Num(extra.Get("used_credits"))
		if !ok || !counted {
			return
		}
		limit = monthly - spent
	}
	balance := math.Inf(1)
	if at(prepaid, "auto_reload_settings", "enabled") != true {
		amount, ok := run.Num(prepaid.Get("amount"))
		if !ok {
			return
		}
		balance = amount
	}
	places, ok := run.Num(exponent)
	if !ok {
		return
	}
	var credits any = "unlimited"
	if left := min(limit, balance); !math.IsInf(left, 1) {
		credits = run.Float(max(left, 0) / math.Pow(10, places))
	}
	currency := "USD"
	for _, named := range []any{extra.Get("currency"), prepaid.Get("currency")} {
		if text, ok := named.(string); ok {
			currency = text
			break
		}
	}
	answer.Set("credits", credits)
	answer.Set("currency", strings.ToUpper(currency))
}
