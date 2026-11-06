package harness

import (
	"context"
	"encoding/json"
	"time"

	"agentkit/internal/run"
)

// codexSettingsFollowed has the seat looked at each time its thread's settings change, as
// codex-seat.py's `settings_changed` does: Codex 0.166 tells a client subscribed to the thread of a
// `/model` or effort set inside the seat before any answer shows it.  The subscription is a resume
// that leaves the turns out, off the seat's own path and retried each second until ctx ends, as a
// new thread may have no rollout to resume yet; once in, a look catches a change made before it.
func codexSettingsFollowed(ctx context.Context, socket, launch string, changed func()) {
	record := run.Fields(codexLaunch, launch)
	for {
		if thread, _ := codexThread(record); thread != "" {
			codexSubscribed(ctx, socket, thread, changed)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Second):
		}
	}
}

// codexSubscribed follows that thread's settings on one connection, until it or ctx ends.
func codexSubscribed(ctx context.Context, socket, thread string, changed func()) {
	client, err := codexDial(socket)
	if err != nil {
		return
	}
	defer context.AfterFunc(ctx, func() { client.conn.Close() })()
	defer client.conn.Close()
	if _, err := client.call("thread/resume", map[string]any{"threadId": thread, "excludeTurns": true}); err != nil {
		return
	}
	changed()
	client.conn.SetDeadline(time.Time{})
	for ctx.Err() == nil {
		message, err := client.receive()
		if err != nil {
			return
		}
		var method string
		var params struct {
			Thread string `json:"threadId"`
		}
		json.Unmarshal(message["method"], &method)
		json.Unmarshal(message["params"], &params)
		if method == "thread/settings/updated" && params.Thread == thread {
			changed()
		}
	}
}
