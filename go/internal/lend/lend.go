// Package lend lends a check's throwaway HOME each harness's login as a copy nothing can renew,
// as Python's lend.into does: on 28 Oct 2026 a check renewed the host's login in the HOME it
// was linked into, retiring the one every seat held, and nothing lent goes back.
package lend

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A Loan is what Into lent: each harness lent, then the paths it placed under home; the epoch
// second the first of them lapses and whose, Whose "" where none does; and {provider: account}
// of each subscription lent by name, in the order lent.
type Loan struct {
	Lent   [][]string
	Ends   int64
	Whose  string
	Named  *run.Object
	placed []string // every link made, taken back where the loan fails
}

// Lenders are the harnesses that lend, in name order, as Python's lend._lenders: each whose
// manifest lists `[worker] logins` and whose adapter is here.
func Lenders() ([]string, error) {
	names, err := config.ManifestNames()
	var lenders []string
	for _, name := range names {
		logins, _ := config.Words(name, "worker", "logins")
		if _, missing := os.Stat(config.AdapterPath(name)); len(logins) > 0 && missing == nil {
			lenders = append(lenders, name)
		}
	}
	return lenders, err
}

// Into lends home, made where missing, each lender's usual login: its adapter's `lend`, told no
// account.  With subscriptions, a harness with none to lend tries next each subscription the
// caller's config lists on a provider it runs, until one lends.  A lend failing, or a place it
// takes in home being taken, fails it all, every link it made taken back: no caller is told
// what to keep out of what it saves.
func Into(ctx context.Context, home string, subscriptions bool) (Loan, error) {
	if err := os.MkdirAll(home, 0o777); err != nil {
		return Loan{}, err
	}
	// the folder the system finds there, so a place joined to it is where Python's lends it, a
	// link's `..` included
	home, err := filepath.EvalSymlinks(home)
	if err != nil {
		return Loan{}, err
	}
	listed := map[string][][2]string{}
	if subscriptions {
		listed = accounts()
	}
	lenders, err := Lenders()
	if err != nil {
		return Loan{}, err
	}
	loan := Loan{Named: run.NewObject()}
	for _, harness := range lenders {
		adapter, err := config.LoginAdapter(harness)
		tries := append([][2]string{{}}, listed[harness]...)
		for lent := false; !lent && err == nil && len(tries) > 0; tries = tries[1:] {
			lent, err = loan.add(ctx, home, harness, adapter, tries[0])
		}
		if err == nil {
			err = ctx.Err() // ended while an adapter that heard it too said it had none
		}
		if err != nil {
			for _, place := range loan.placed {
				os.Remove(place)
			}
			return Loan{}, err
		}
	}
	return loan, nil
}

// add is harness's lend of account, {provider, name}, its usual login where unnamed: false
// where it has none to lend.  It lends into a folder of its own under home, so what it placed
// is known without its harness's layout, and is linked from there into home, refusing a place
// taken.
func (loan *Loan) add(ctx context.Context, home, harness, adapter string, account [2]string) (bool, error) {
	staging, err := os.MkdirTemp(home, ".lend-")
	if err != nil {
		return false, err
	}
	defer os.RemoveAll(staging)
	args := []string{adapter, "lend", staging}
	if account[1] != "" {
		args = append(args, "own")
	}
	call, cancel := context.WithTimeout(ctx, time.Minute) // asking for saved keys boots a server
	defer cancel()
	stdout, stderr, err := within(call, append(os.Environ(), config.AccountEnv(account[1]), "AGENTKIT_PROVIDER="+account[0]), args)
	var exited *exec.ExitError
	switch {
	case err != nil && ctx.Err() != nil:
		return false, ctx.Err()
	case err != nil && call.Err() != nil:
		return false, fmt.Errorf("%s lend took more than a minute", harness)
	case errors.As(err, &exited) && exited.ExitCode() == 1:
		return false, nil // none to lend
	case errors.As(err, &exited):
		return false, fmt.Errorf("%s lend exited %d: %s", harness, exited.ExitCode(), strings.TrimFunc(string(stderr), config.Space))
	case err != nil:
		return false, err
	}
	said := strings.TrimFunc(string(stdout), config.Space)
	ends, unread := strconv.ParseInt(said, 10, 64)
	if !utf8.Valid(stdout) || said != "" && unread != nil {
		return false, fmt.Errorf("%s lend printed %s, not the second its login lapses", harness, strconv.Quote(said))
	}
	placed := []string{harness}
	err = filepath.WalkDir(staging, func(path string, _ fs.DirEntry, err error) error {
		if info, unseen := os.Stat(path); err != nil || unseen != nil || !info.Mode().IsRegular() {
			return err
		}
		rel, _ := filepath.Rel(staging, path)
		place := filepath.Join(home, rel)
		if err := os.MkdirAll(filepath.Dir(place), 0o777); err != nil {
			return err
		}
		if err := os.Link(path, place); err != nil {
			return err
		}
		loan.placed, placed = append(loan.placed, place), append(placed, rel)
		return nil
	})
	if err != nil {
		return false, err
	}
	loan.Lent = append(loan.Lent, placed)
	if said != "" && (loan.Whose == "" || ends < loan.Ends) {
		loan.Ends, loan.Whose = ends, harness
	}
	if account[1] != "" {
		loan.Named.Set(account[0], account[1])
	}
	return true, nil
}

// within is what argv printed on stdout and stderr, and how it ended, all within call, as
// Python's subprocess.run(timeout=...) has it: call's end kills the program and stops reading
// what anything it left holding its output still writes, which os/exec's WaitDelay, timed from
// the program's own exit, would wait for past that end.
func within(call context.Context, env, argv []string) (stdout, stderr []byte, err error) {
	var reads, writes [2]*os.File
	for i := range reads {
		if reads[i], writes[i], err = os.Pipe(); err != nil {
			return nil, nil, err
		}
		defer reads[i].Close()
		defer writes[i].Close()
	}
	command := exec.CommandContext(call, argv[0], argv[1:]...)
	command.Env, command.Stdout, command.Stderr = env, writes[0], writes[1]
	err = command.Start()
	writes[0].Close() // only the program writes them now, so its end is their end
	writes[1].Close()
	if err != nil {
		return nil, nil, err
	}
	defer context.AfterFunc(call, func() {
		reads[0].SetReadDeadline(time.Now())
		reads[1].SetReadDeadline(time.Now())
	})()
	read := make(chan error, 1)
	go func() {
		var err error
		stderr, err = io.ReadAll(reads[1])
		read <- err
	}()
	stdout, err = io.ReadAll(reads[0])
	err = cmp.Or(err, <-read)
	return stdout, stderr, cmp.Or(command.Wait(), err)
}

// accounts is {harness: [{provider, account}]}, each subscription the caller's config lists by
// name, in its order, under each harness its provider runs on, as Python's lend._listed:
// ProviderHarnesses, so one whose models were all removed still counts.  The default account
// is the usual login, and a config that cannot be read lists none.
func accounts() map[string][][2]string {
	listed := map[string][][2]string{}
	providers, _, err := config.ProviderNames()
	if err != nil {
		return listed
	}
	for _, provider := range providers {
		harnesses, _ := config.ProviderHarnesses(provider)
		names, _ := config.Accounts(provider)
		for _, harness := range harnesses {
			for _, name := range names {
				if name != config.DefaultAccount {
					listed[harness] = append(listed[harness], [2]string{provider, name})
				}
			}
		}
	}
	return listed
}
