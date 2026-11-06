package tick

import (
	"fmt"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// bootResume is the boot resume row (watch.resume_after_boot): the first tick after a reboot
// reopens each seat that owes work, each claimed in watch.json before its launch, so a pass cut
// off midway never reopens one twice on that boot.  A dry tick only says which it would reopen.
func (t *ticking) bootResume() error {
	return afterBoot(t.dry, func(state *run.Object, boot string, back []seat.Comeback) error {
		for _, each := range back {
			if t.dry {
				t.log.line(fmt.Sprintf("would resume %s after reboot in %s", each.Name, each.Cwd))
				continue
			}
			// a failed or interrupted launch is never repeated this boot
			carried, err := each.Resume(boot, func() error {
				attempted, _ := claims(state, boot)
				state.Set("boot_resume", run.Fields("id", boot, "attempted", append(attempted, each.Name)))
				return writeState(state)
			})
			if !carried {
				return errLeft
			}
			if err != nil {
				t.log.line(fmt.Sprintf("WARN could not resume %s after reboot: %s", each.Name, config.PyError(err)))
				continue
			}
			t.log.line("resumed " + each.Name + " after reboot")
		}
		return nil
	})
}

// afterBoot is resume_after_boot around its reopening: the first pass ever, or the first after a
// reboot once `reopen` has had the seats that boot owes a comeback, records the boot.  Under
// watch.json's lock, which the tick and the menu share; a dry pass takes none and records nothing.
func afterBoot(dry bool, reopen func(state *run.Object, boot string, back []seat.Comeback) error) error {
	boot := host.BootID()
	if boot == "" {
		return nil
	}
	pass := func() error {
		state, ok := loadState()
		if !ok {
			return errUnwritable
		}
		if state.Get("boot_id") == boot {
			return nil
		}
		if state.Truthy("boot_id") {
			attempted, known := claims(state, boot)
			home, read := seat.TickHome(time.Now())
			if !known || !read {
				return errLeft
			}
			back, known := home.AfterBoot(attempted)
			if !known {
				return errLeft
			}
			if err := reopen(state, boot, back); err != nil {
				return err
			}
		}
		if dry {
			return nil
		}
		state.Set("boot_id", boot)
		return writeState(state)
	}
	if dry {
		return pass()
	}
	return locked(pass)
}

// claims are the seats a pass already tried on this boot, as boot_resume holds them; one on the
// boot before claims nothing.  False for claims Go cannot read as names.
func claims(state *run.Object, boot string) ([]any, bool) {
	recovery := state.Dict("boot_resume")
	if recovery == nil || recovery.Get("id") != boot || !recovery.Has("attempted") {
		return []any{}, true
	}
	attempted, listed := recovery.Get("attempted").([]any)
	return attempted, listed && !slices.ContainsFunc(attempted, func(name any) bool { _, named := name.(string); return !named })
}
