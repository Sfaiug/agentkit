package harness

import (
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// claudeAuth reads Claude Code's logins as claude.sh's `auth` does.  For a turn the worker token
// answers first, from the environment or its file; otherwise, and alone for `seat`, the seat's
// own login answers: the two expire apart, and a good worker token would hide a seat's lapsed
// login.  A lapsed login holding a refresh token renews only in a turn of Claude Code.
func claudeAuth(login config.Login, seat bool) Answer {
	token, variable := config.WorkerToken("claude", login)
	if !seat && getenv(login, variable) != "" {
		return Answer{Yes: true, Line: "claude: " + variable + " is set"}
	}
	if !seat {
		data, err := os.ReadFile(token)
		info, gone := os.Stat(token)
		if err == nil && gone == nil && !blank(string(data)) {
			// `claude setup-token` mints a token for a year, so its file's own date is the token's
			table, _ := config.Section("claude", "login")
			life := int64(0)
			if days, ok := table["token_days"].(*big.Int); ok {
				life = days.Int64() * 86400
			}
			left := info.ModTime().Unix() + life - time.Now().Unix()
			if left <= 0 {
				return Answer{Line: "claude: worker token expired; run `claude setup-token` and replace " + token}
			}
			return Answer{Yes: true, Line: fmt.Sprintf("claude: long-lived worker token in %s (expires in %d days)%s",
				token, left/86400, claudeWho(login))}
		}
	}
	file, blob, oauth := claudeLogin(login)
	ends, dated := claudeEnds(oauth)
	expired := ends <= time.Now().UnixMilli()
	lapsed := given(oauth.Get("refreshToken")) && dated && expired
	auth, _ := config.Section("claude", "auth")
	remedy, _ := auth["remedy"].(string)
	no := func(line string) Answer { return Answer{Line: "claude: " + line + "; " + remedy, Lapsed: lapsed} }
	switch {
	case !strings.Contains(string(blob), "accessToken"):
		return no("no OAuth credentials in " + file + " and no " + variable)
	case !given(oauth.Get("accessToken")):
		return no("the credentials in " + file + " carry no access token")
	case !dated:
		return no("the credentials in " + file + " record no usable expiry")
	case expired:
		return no("the OAuth token in " + file + " expired")
	}
	return Answer{Yes: true, Line: "claude: the OAuth token in " + file + " is still valid" + claudeWho(login)}
}

// claudeLogin is the seat's own login: the file it is kept in, the text read, on a Mac the usual
// login's Keychain entry first, and its `claudeAiOauth` object, empty where it holds none.
func claudeLogin(login config.Login) (file string, blob []byte, oauth *run.Object) {
	file = config.LoginPath("claude", "credentials", login)
	table, _ := config.Section("claude", "login")
	keychain, _ := table["keychain"].(string)
	var err error = os.ErrNotExist
	if runtime.GOOS == "darwin" && keychain != "" && getenv(login, login.Env) == "" {
		blob, err = exec.Command("security", "find-generic-password", "-s", keychain, "-w").Output()
		blob = []byte(strings.TrimRight(string(blob), "\n"))
	}
	if err != nil {
		blob, _ = os.ReadFile(file)
	}
	value, _ := run.Decode(blob)
	if whole, ok := value.(*run.Object); ok {
		oauth = whole.Dict("claudeAiOauth")
	}
	if oauth == nil {
		oauth = run.NewObject()
	}
	return file, blob, oauth
}

// digits is what claude.sh takes for an epoch: nothing but decimal digits.
var digits = regexp.MustCompile(`^[0-9]+$`)

// claudeEnds is the epoch millisecond the login's access token ends, `expiresAt`, which every
// file seen writes in milliseconds and an eleven-digit one or shorter in seconds; false where it
// writes none.
func claudeEnds(oauth *run.Object) (int64, bool) {
	text := fmt.Sprint(oauth.Get("expiresAt"))
	if !digits.MatchString(text) {
		return 0, false
	}
	if len(text) <= 11 {
		text += "000"
	}
	ends, err := strconv.ParseInt(text, 10, 64)
	return ends, err == nil
}

// claudeWho is `; logged in as <email>` where Claude Code wrote down whose the login is, else "".
func claudeWho(login config.Login) string {
	data, _ := os.ReadFile(config.LoginPath("claude", "who", login))
	value, _ := run.Decode(data)
	if whole, ok := value.(*run.Object); ok && whole.Dict("oauthAccount") != nil {
		if email := whole.Dict("oauthAccount").Str("emailAddress"); email != "" {
			return "; logged in as " + email
		}
	}
	return ""
}
