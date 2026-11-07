package seat

import (
	"context"
	"fmt"
	"io"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// Ended is `ak orch ended NAME WHEN` (orch.cmd_ended), tmux's pane-died hook (tmux.Hooks): a seat
// whose harness ended without ak ending it, at WHEN by tmux's clock, comes back in its pane as its
// number opens it, on the conversation its record holds or fresh, told what the end cut off
// (orch.reopen, goesOn): as the line its conversation opens on, or owed with the fresh note where it comes
// back with no past, as the tick's revival owes it.  One the owner stopped ended on purpose and is
// told nothing.
//
// Decided and done under the lock a stop decides under, so a stop finds it back or this finds it
// gone.  Left as it is with no record, closed by the owner, live again or gone, or ended inside its
// warm-up, so a harness that cannot start never loops.  A launch under way writes its moment under
// the seat's lock, so it is read under that lock too.  False, before anything is written, where Go
// does not carry the comeback, as for a reboot's (AfterBoot).
func Ended(name string, died float64, out io.Writer) (bool, error) {
	if err := config.EnsureDirs(); err != nil {
		return true, err
	}
	state := filepath.Join(config.Home(), "state")
	carried := true
	err := under(filepath.Join(state, "watch.lock"), func() error {
		if record, _ := run.ReadJSON(ownFile("session", name)); record == nil || record.Has(config.Renamed) {
			return nil // no seat of ak's: nothing of it to lock
		}
		var fields map[string]any
		if err := notify.Held(context.Background(), name, func(current string) error {
			name = current
			_, fields, _ = config.ResolveSession(current)
			return nil
		}); err != nil {
			return err
		}
		file := revivalFile(name)
		launched, _ := fields["launched"].(float64)
		if fields == nil || file.Truthy("closed_by_owner") || died-launched < Warmup.Seconds() {
			return nil
		}
		held, exited, known := find(name, fields)
		if known && (!held || !exited) {
			return nil
		}
		back, ready := comingBack(state, name, fields, true, true)
		line := ""
		if known && ready {
			line, known = back.goesOn(How{Owner: true})
		}
		if !known || !ready || !back.launchable(fields) || !owedReadable(file) {
			carried = false
			return nil
		}
		var err error
		comeback := Comeback{Name: name, Cwd: back.cwd, Line: line, back: back}
		if carried, err = comeback.Resume(host.BootID(), func() error { return nil }); !carried || err != nil {
			return err
		}
		fmt.Fprintln(out, back.said())
		if line == "" || back.line != "" {
			return nil
		}
		return OweLine(name, line+freshContinue)
	})
	return carried, err
}
