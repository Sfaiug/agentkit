package harness

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// CodexPairing is the manual code that pairs the provider's app with a Codex seat
// (codex-seat.py `pair_again`), asked of the app server the seat's guard runs, through the socket
// a connection.json names: the one given, or with none the one in the Codex home of the seat
// named seat, by its name or one it had, whose launch receipt names that home (codex.py
// `pairing_home`).  It starts nothing and writes nothing: the seat and its Codex run on.  Not
// known where Python must answer, which is never once the request has gone: Python would ask
// Codex for a second code.  An error is in Python's words, as codex-seat.py says it.
func CodexPairing(seat, connection string) (code string, known bool, err error) {
	defer func() {
		if err != nil {
			err = fmt.Errorf("codex seat: %w", err)
		}
	}()
	if connection == "" {
		name, record, err := config.ResolveSession(seat)
		if err != nil {
			return "", false, nil
		}
		receipt := codexReceipt(run.Fields(codexLaunch, record[codexLaunch]))
		if receipt == nil || !receipt.Truthy("remote") {
			return "", true, fmt.Errorf("%s has no Codex remote connection; open its Codex seat first", name)
		}
		if !launchToken.MatchString(receipt.Str("remote")) {
			return "", false, nil
		}
		connection = filepath.Join(config.Home(), "state", "codex-remote-"+receipt.Str("remote"), "connection.json")
	}
	data, err := os.ReadFile(connection)
	if err != nil {
		return "", true, errors.New(config.PyError(err))
	}
	read, _ := run.Decode(data)
	named, _ := read.(*run.Object)
	if named == nil || named.Str("socket") == "" {
		return "", false, nil
	}
	client, err := codexDial(named.Str("socket"), time.Time{})
	if dial := (*net.OpError)(nil); errors.As(err, &dial) && dial.Op == "dial" {
		return "", true, errors.New(config.PyError(err))
	}
	if err != nil {
		return "", false, nil // a handshake Python says in its own words
	}
	defer client.conn.Close()
	result, err := client.call("remoteControl/pairing/start", map[string]any{"manualCode": true})
	switch {
	case errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF):
		return "", true, errors.New("Codex app server closed its socket")
	case errors.Is(err, os.ErrDeadlineExceeded):
		return "", true, errors.New("timed out")
	case err != nil:
		return "", true, errors.New(config.PyError(err))
	}
	read, _ = run.Decode(result)
	answer, _ := read.(*run.Object)
	if answer == nil || !answer.Has("manualPairingCode") {
		return "", true, errors.New("Codex app server gave no pairing code")
	}
	return run.Text(answer.Get("manualPairingCode")), true, nil
}
