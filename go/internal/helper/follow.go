package helper

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"maps"
	"math/big"
	"os"
	"slices"
	"time"

	"agentkit/internal/config"
)

// look is how often a turn on a machine looks at its login files here, Python's machine_turn.LOOK:
// a renewal revokes the turn's copy, and a real harness re-read its file for only 1.7 s of refusals
// (2 Nov 2026), `lend` and sending within, where a new ssh to a far machine took 3.7 s and the turn
// died of the refusals.
const look = 250 * time.Millisecond

// A follower is what a turn on a machine follows of its login here, Python's
// machine_turn._following: the files the harness's `[worker] logins` name, what stat said of them,
// and the copy the machine holds.
type follower struct {
	model   config.Model
	adapter string
	env     map[string]string
	logins  []string
	seen    []os.FileInfo
	sent    map[string]file
}

// following is the follower of the login the model's adapter lends a turn on cwd with env.
func following(model config.Model, adapter, cwd string, env map[string]string) *follower {
	names, _ := config.Words(model.Harness, "worker", "logins")
	return &follower{model: model, adapter: adapter, env: env, logins: config.ManifestPaths(names, env, cwd)}
}

// lent is the login lent for the turn's parcel, the copy the machine holds first: none where the
// adapter lends none lasting the seconds the harness's `[worker] lent_for` says, else lentFor, as a
// longer turn would end on it expired.  What stat says of its files is read before the lend: a
// renewal as the turn prepares is followed too.
func (f *follower) lent() map[string]file {
	lasting := float64(lentFor)
	worker, _ := config.Section(f.model.Harness, "worker")
	switch seconds := worker["lent_for"].(type) {
	case *big.Int:
		lasting, _ = new(big.Float).SetInt(seconds).Float64()
	case float64:
		lasting = seconds
	}
	f.seen = stamps(f.logins)
	f.sent = lend(f.model, f.adapter, f.env, lasting)
	return f.sent
}

// follow is the stdin of the turn's ssh, and what stops the following, returning once it is over.
// Until then, every look a change of the login files' stamps lends again, with no lasting asked as
// any copy beats a revoked one, and a copy differing from the last sent goes down that connection:
// one line for each file, its bytes in base64, a space, then its path, which mac.sh's `renewals`
// puts there by rename.  A lend that fails or lends nothing sends nothing.
func (f *follower) follow() (*os.File, func(), error) {
	connection, sending, err := os.Pipe()
	if err != nil {
		return nil, nil, err
	}
	done, over := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(over)
		tick := time.NewTicker(look)
		defer tick.Stop()
		for {
			select {
			case <-done:
				return
			case <-tick.C:
			}
			now := stamps(f.logins)
			if slices.EqualFunc(now, f.seen, same) {
				continue
			}
			f.seen = now
			fresh := lend(f.model, f.adapter, f.env, 0)
			if len(fresh) == 0 || maps.EqualFunc(fresh, f.sent, func(a, b file) bool { return bytes.Equal(a.data, b.data) }) {
				continue
			}
			f.sent = fresh
			var lines []byte
			for _, name := range slices.Sorted(maps.Keys(fresh)) {
				lines = fmt.Appendf(lines, "%s %s\n", base64.StdEncoding.EncodeToString(fresh[name].data), name)
			}
			sending.Write(lines)
		}
	}()
	return connection, func() {
		// with the ssh gone, a send left waiting finds its pipe closed, and lands nothing
		connection.Close()
		close(done)
		<-over
		sending.Close()
	}, nil
}

// stamps is what stat says of each of the files, nil for one it cannot: it forks nothing, however
// many turns look at once.
func stamps(paths []string) []os.FileInfo {
	said := make([]os.FileInfo, len(paths))
	for i, at := range paths {
		said[i], _ = os.Stat(at)
	}
	return said
}

// same is whether stat said the same of a file twice: none both times, or the same file, of the
// same time and size.
func same(a, b os.FileInfo) bool {
	if a == nil || b == nil {
		return a == b
	}
	return os.SameFile(a, b) && a.ModTime().Equal(b.ModTime()) && a.Size() == b.Size()
}
