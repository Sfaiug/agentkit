package harness

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// codexNamed keeps the seat's remote-control environment named after the seat, as codex-seat.py's
// `connected` does beside its TUI until ctx ends: each second until its server reads connected,
// then each 30, it reads the server's remote-control status, keeps the environment among those its
// home may have to delete (`enroll`), and names it after the seat on the provider when either has
// changed.  It asks for no pairing: a code is the owner's to request (codex-seat.py --pair).
func codexNamed(ctx context.Context, home, socket string, log io.Writer) {
	var named [2]string
	for {
		wait := time.Second
		client, err := codexDial(socket)
		if err == nil {
			var status *run.Object
			if status, err = codexStatus(client); err == nil {
				if named, err = codexEnroll(ctx, home, status, named); err == nil && status.Str("status") == "connected" {
					wait = 30 * time.Second
				}
			}
			client.conn.Close()
		}
		if err != nil {
			fmt.Fprintf(log, "Codex remote control: %v\n", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}

// codexStatus is the server's remote-control status.
func codexStatus(client *codexClient) (*run.Object, error) {
	result, err := client.call("remoteControl/status/read", nil)
	if err != nil {
		return nil, err
	}
	read, _ := run.Decode(result)
	status, _ := read.(*run.Object)
	if status == nil {
		return nil, errors.New("Codex remote status is not an object")
	}
	return status, nil
}

// codexEnroll writes the status's environment down among the home's enrollments, with the login
// that may delete it, before any request can fail, and names it after the seat where the
// environment or the seat's name is not the one last named: the pair named now.
func codexEnroll(ctx context.Context, home string, status *run.Object, named [2]string) ([2]string, error) {
	environment := status.Str("environmentId")
	if environment == "" {
		return [2]string{}, nil
	}
	records, err := codexEnrollments(home)
	if err != nil {
		return named, err
	}
	if !records.Has(environment) {
		records.Set(environment, run.Fields("auth", codexResolved(filepath.Join(home, "auth.json"))))
	}
	entry := records.Dict(environment)
	if entry == nil {
		return named, fmt.Errorf("%s names %s with no login", codexEnrolled(home), environment)
	}
	if err := os.WriteFile(codexEnrolled(home), []byte(run.Line(records)), 0o666); err != nil {
		return named, err
	}
	name, _, err := config.ResolveSession(os.Getenv("AGENTKIT_SESSION"))
	if err != nil {
		return named, err
	}
	if named != [2]string{environment, name} {
		if err := codexRename(ctx, entry.Str("auth"), environment, name); err != nil {
			return named, err
		}
	}
	return [2]string{environment, name}, nil
}

// codexEnrolled is the file a seat's home keeps its enrollments in, each environment by the login
// that may delete it, so a login changed since still finds it.
func codexEnrolled(home string) string { return filepath.Join(home, "agentkit-enrollments.json") }

// codexEnrollments are the home's enrollments as written down, with each one its state database
// holds for the login it runs on now (codex-seat.py `enrollments`): a pane can close before its
// first connected status was read.
func codexEnrollments(home string) (*run.Object, error) {
	records := run.NewObject()
	data, err := os.ReadFile(codexEnrolled(home))
	if err == nil {
		read, err := run.Decode(data)
		if records, _ = read.(*run.Object); err != nil || records == nil {
			return nil, fmt.Errorf("%s holds no enrollments", codexEnrolled(home))
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	auth := filepath.Join(home, "auth.json")
	data, err = os.ReadFile(auth)
	if errors.Is(err, fs.ErrNotExist) {
		return records, nil
	}
	read, _ := run.Decode(data)
	login, _ := read.(*run.Object)
	if err != nil || login == nil {
		return nil, fmt.Errorf("%s holds no login", auth)
	}
	var account any
	if tokens := login.Dict("tokens"); tokens != nil {
		account = tokens.Get("account_id")
	}
	for _, database := range config.Glob(home, "state_*.sqlite") {
		found, err := codexEnvironments(database, account)
		if err != nil {
			return nil, err
		}
		for _, environment := range found {
			if !records.Has(environment) {
				records.Set(environment, run.Fields("auth", codexResolved(auth)))
			}
		}
	}
	return records, nil
}

// codexEnvironments are the environments that state database enrolled for that account, read only:
// none for an account that is no text, as SQLite matches nothing to a NULL.
func codexEnvironments(database string, account any) ([]string, error) {
	conn, err := sqlite.Open(database, sqlite3.OPEN_READONLY)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	named, isText := account.(string)
	if !isText || !codexTable(conn, "remote_control_enrollments") {
		return nil, nil
	}
	stmt, _, err := conn.Prepare("SELECT environment_id FROM remote_control_enrollments WHERE account_id = ?")
	if err != nil {
		return nil, err
	}
	defer stmt.Close()
	var found []string
	for err = stmt.BindText(1, named); err == nil && stmt.Step(); {
		if stmt.ColumnType(0) == sqlite3.TEXT {
			found = append(found, stmt.ColumnText(0))
		}
	}
	if err == nil {
		err = stmt.Err()
	}
	return found, err
}

// codexTable is whether that database holds a table of that name.
func codexTable(conn *sqlite3.Conn, name string) bool {
	stmt, _, err := conn.Prepare("SELECT 1 FROM sqlite_master WHERE name = ?")
	if err != nil {
		return false
	}
	defer stmt.Close()
	return stmt.BindText(1, name) == nil && stmt.Step()
}

// codexRename names the environment on the provider, on the login it was enrolled with
// (codex-seat.py `remote_request`).
func codexRename(ctx context.Context, auth, environment, name string) error {
	data, err := os.ReadFile(auth)
	if err != nil {
		return err
	}
	read, _ := run.Decode(data)
	login, _ := read.(*run.Object)
	var tokens *run.Object
	if login != nil {
		tokens = login.Dict("tokens")
	}
	if tokens == nil {
		return fmt.Errorf("%s holds no tokens", auth)
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	// Python's quote(environment, safe=""): every byte past the unreserved ones escaped
	path := strings.ReplaceAll(url.QueryEscape(environment), "+", "%20")
	request, err := http.NewRequestWithContext(ctx, http.MethodPatch,
		"https://chatgpt.com/backend-api/wham/remote/control/environments/"+path,
		bytes.NewReader([]byte(run.Line(run.Fields("name", name)))))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+tokens.Str("access_token"))
	request.Header.Set("ChatGPT-Account-Id", tokens.Str("account_id"))
	request.Header.Set("Content-Type", "application/json")
	request.Close = true // a name is set seldom: no connection is kept for the next
	client := http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	io.Copy(io.Discard, response.Body)
	if response.StatusCode/100 != 2 {
		return fmt.Errorf("Codex remote PATCH: HTTP %d", response.StatusCode)
	}
	return nil
}

// codexKeepEnrollments writes down the enrollments a stopped server leaves its home, for a forget
// to delete whichever login the seat runs on next.
func codexKeepEnrollments(home string) {
	if records, err := codexEnrollments(home); err == nil {
		os.WriteFile(codexEnrolled(home), []byte(run.Line(records)), 0o666)
	}
}

// codexBackfillFreed puts back the backfill an earlier server of that home was running as it
// stopped, as codex-seat.py `connected` does: the home's lock keeps that server out, and its lease
// would otherwise outlast Codex's own wait as it starts.
func codexBackfillFreed(home string) error {
	for _, database := range config.Glob(home, "state_*.sqlite") {
		conn, err := sqlite.Open(database, sqlite3.OPEN_READWRITE)
		if err != nil {
			return err
		}
		if codexTable(conn, "backfill_state") {
			err = conn.Exec("UPDATE backfill_state SET status = 'pending' WHERE status = 'running'")
		}
		if closed := conn.Close(); err == nil {
			err = closed
		}
		if err != nil {
			return err
		}
	}
	return nil
}
