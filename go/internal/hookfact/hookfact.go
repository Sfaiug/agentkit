// Package hookfact keeps what a seat's own harness hooks say it is doing, Python's
// config.record_hook_fact, and every fact Go writes goes through it.  It hides the fact's file,
// `hook-<name>.json` under the seat's folded name; its lock, `.hook-<name>.lock`, which Python's
// writers flock too, so one reads, judges and replaces the fact at a time; newest-wins, since an
// event its harness does not wait on can finish after a newer one and is never put back over it;
// and what a fact carries over: the background work the standing one holds, which no event but
// the next Stop, listing that work again, ends.
package hookfact

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// A Fact is one event a seat's hooks heard, its keys in the order Python writes them.
type Fact struct {
	Session string   `json:"session"` // the launch name the harness carries, as it hands it over
	Event   string   `json:"event"`
	Kind    string   `json:"kind"`
	Text    string   `json:"text"`
	At      float64  `json:"at"`
	Holds   []string `json:"holds,omitempty"`
}

// Record puts the fact in place of the seat's standing one, unless that one was heard later.
func Record(name string, fact Fact) error {
	session, err := config.SessionPath(name)
	if err != nil {
		return err
	}
	dir, stem := filepath.Dir(session), "hook-"+config.Fold(name)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "."+stem+".lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	path := filepath.Join(dir, stem+".json")
	data, _ := os.ReadFile(path) // a fact unread, or no object, is none standing
	read, _ := run.Decode(data)
	standing, ok := read.(*run.Object)
	if !ok {
		standing = run.NewObject()
	}
	if at, ok := run.Num(standing.Get("at")); ok && at > fact.At {
		return nil
	}
	if fact.Event != "Stop" {
		for _, task := range standing.List("holds") {
			if task, ok := task.(string); ok { // each writer puts a task's type down as a string
				fact.Holds = append(fact.Holds, task)
			}
		}
	}
	data, err = json.Marshal(fact)
	if err != nil {
		return err
	}
	tmp := filepath.Join(dir, stem+".tmp")
	if err := os.WriteFile(tmp, append(data, '\n'), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
