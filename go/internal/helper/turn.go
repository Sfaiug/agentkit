package helper

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"math"
	"math/big"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/uncommitted"
	"agentkit/internal/update"
)

// ak is ak itself, which a turn's container mounts read-only, `bin` on PATH: Python's
// machine_turn.AK.
var ak = []string{"adapters", "agentkit", "bin", "tools"}

// lentFor is the seconds a lent login must last, else the turn runs here, Python's
// machine_turn.LENT_FOR: a longer turn would end on an expired login.  A harness may say fewer
// (`[worker] lent_for`).
const lentFor = 3600

// checkout is where ak runs from, whose ak a turn carries.
var checkout = config.Repo

// told is what of a turn's environment, beside each `AK_` and `BASH_` variable, a turn on a
// machine is told: never the loop's whole environment.
var told = []string{host.Marker, "HOME", "LANG", "SHELL", "TMPDIR"}

// turnFiles is what a model turn adds to its parcel beside a suite's, as Python's machine_turn.call
// has _parcel add it, for the model's turn its adapter runs on the checkout cwd into the out dir
// with env, resuming session where it names one: turn.sh, the out dir, ak, the uncommitted paths
// (`paths` lists them all, `dirty/` holds those the checkout has), info/exclude, and under `home/`
// a .gitconfig naming the checkout's git user, the login lent (`lent` lists its paths, which
// mac.sh's `turn` removes) and the conversation it resumes; then the program (`harness`, and
// `fetch/` where each kind of machine gets it) and the environment's variables a turn there is
// told, in name order, its TMPDIR the machine's.  None, where the turn runs here: its harness keeps
// no conversation a turn there could bring home (`[worker] sessions`), no program for it can be
// fetched, the conversation is nowhere under env's HOME, as here is where a later resume would
// look for it too, or no login is lent lasting long enough.
func turnFiles(model config.Model, adapter, cwd, out string, env map[string]string, session string) (map[string]file, error) {
	places, _ := config.Words(model.Harness, "worker", "sessions")
	if len(places) == 0 {
		return nil, nil
	}
	program, fetch := fetched(model.Harness)
	held := conversation(places, env["HOME"], session)
	if program == "" || session != "" && len(held) == 0 {
		return nil, nil
	}
	lent := lend(model, adapter, env)
	if len(lent) == 0 {
		return nil, nil
	}
	script, err := carried.ReadFile("turn.sh")
	if err != nil {
		return nil, err
	}
	// executable, as tools/helper has it
	files := map[string]file{"turn.sh": made(0o755, script), "harness": made(0o644, []byte(program))}
	if err := add(files, out, "out", true, nil); err != nil {
		return nil, err
	}
	// what this host's Python compiled stays here, unread, as Python's parcel leaves it
	compiled := func(name string) bool { return strings.Contains(name, "__pycache__") }
	for _, name := range ak {
		// a checkout without Python's ak, as Go's keys run from, carries the rest: the machine
		// makes each part's folder, held or not
		from := filepath.Join(checkout(), name)
		if _, err := os.Lstat(from); errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err := add(files, from, "ak/"+name, true, compiled); err != nil {
			return nil, err
		}
	}
	g := gitcall.Git{Repo: cwd}
	paths, err := uncommitted.Paths(g)
	if err != nil {
		return nil, err
	}
	files["paths"] = made(0o644, listed(paths))
	for _, name := range paths {
		at := filepath.Join(cwd, filepath.FromSlash(name))
		if _, err := os.Lstat(at); err == nil {
			if err := add(files, at, "dirty/"+name, false, nil); err != nil {
				return nil, err
			}
		}
	}
	exclude, err := g.Must("rev-parse", "--git-path", "info/exclude")
	if err != nil {
		return nil, err
	}
	if !filepath.IsAbs(exclude) {
		exclude = filepath.Join(cwd, exclude)
	}
	if info, err := os.Stat(exclude); err == nil && info.Mode().IsRegular() {
		if err := add(files, exclude, "exclude", false, nil); err != nil {
			return nil, err
		}
	}
	var who [2]string
	for i, key := range []string{"name", "email"} {
		if _, who[i], err = g.Out("config", "user."+key); err != nil {
			return nil, err
		}
	}
	files["home/.gitconfig"] = made(0o644, fmt.Appendf(nil, "[user]\n\tname = %s\n\temail = %s\n", who[0], who[1]))
	files["lent"] = made(0o644, listed(slices.Sorted(maps.Keys(lent))))
	for name, each := range lent {
		files["home/"+name] = each
	}
	for _, name := range held {
		if err := add(files, filepath.Join(env["HOME"], filepath.FromSlash(name)), "home/"+name, true, nil); err != nil {
			return nil, err
		}
	}
	for machine, url := range fetch {
		files["fetch/"+machine] = made(0o644, []byte(url))
	}
	given := map[string]string{}
	for key, value := range env {
		if strings.HasPrefix(key, "AK_") || strings.HasPrefix(key, "BASH_") || slices.Contains(told, key) {
			given[key] = value
		}
	}
	given["TMPDIR"] = "/var/tmp"
	var pairs []string
	for _, key := range slices.Sorted(maps.Keys(given)) {
		pairs = append(pairs, key+"="+given[key])
	}
	files["env"] = made(0o644, listed(pairs))
	return files, nil
}

// listed is names as the parcel lists them, each ended by a NUL.
func listed(names []string) []byte {
	var list []byte
	for _, name := range names {
		list = append(append(list, name...), 0)
	}
	return list
}

// add puts in files what the disk has at from as name, as Python's tarfile.add does: a link as a
// link, and, deep, a directory with all under it but what skip names, a folder it names never
// opened, as Python's filter leaves it.  A socket goes nowhere, as there.
func add(files map[string]file, from, name string, deep bool, skip func(name string) bool) error {
	return filepath.WalkDir(from, func(at string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		inside, _ := filepath.Rel(from, at)
		inside = path.Join(name, filepath.ToSlash(inside))
		if skip != nil && skip(inside) {
			if entry.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		info, err := entry.Info()
		link := ""
		if err == nil && info.Mode()&fs.ModeSymlink != 0 {
			link, err = os.Readlink(at)
		}
		if err != nil {
			return err
		}
		if head, err := tar.FileInfoHeader(info, link); err == nil {
			each := file{head: *head}
			if head.Typeflag == tar.TypeReg {
				each.from = at
			}
			files[inside] = each
		}
		if !deep && entry.IsDir() {
			return fs.SkipDir
		}
		return nil
	})
}

// fetched is the program a machine runs a turn of that harness with, `<harness>/<version>/
// <program>`, and the URL each kind of machine (`uname -m`) fetches it from, Python's
// machine_turn._program: those its manifest's `[fetch]` names, `{version}` the version `ak
// update` reads here.  "" where it names none, or that version cannot be read.
func fetched(harness string) (string, map[string]string) {
	where, _ := config.Section(harness, "fetch")
	version := ""
	if len(where) > 0 {
		version = update.Version(harness)
	}
	if version == "" {
		return "", nil
	}
	urls := map[string]string{}
	for machine, url := range where {
		text, ok := url.(string)
		if !ok {
			return "", nil
		}
		urls[machine] = strings.ReplaceAll(text, "{version}", version)
	}
	program := harness
	if words, _ := config.Words(harness, "update", "version"); len(words) > 0 && words[0] != "" {
		program = words[0]
	}
	return harness + "/" + version + "/" + program, urls
}

// patterns are the globs under HOME of the conversation session, Python's
// machine_turn._conversation: the harness's `[worker] sessions`, places with `{id}` the id.  None
// for an id with a `/`, which names no file, so an id a turn reported reaches nowhere else, nor
// for one holding what a glob reads as a pattern.
func patterns(places []string, session string) []string {
	if session == "" || strings.ContainsAny(session, `/\*?[`) {
		return nil
	}
	var globs []string
	for _, place := range places {
		globs = append(globs, strings.ReplaceAll(strings.TrimPrefix(place, "~/"), "{id}", session))
	}
	return globs
}

// conversation is the names under home of the conversation session, as Python's glob finds them:
// what its patterns match, and all under them.
func conversation(places []string, home, session string) []string {
	var names []string
	for _, pattern := range patterns(places, session) {
		matches, _ := filepath.Glob(filepath.Join(home, filepath.FromSlash(pattern)))
		for _, at := range matches {
			name, _ := filepath.Rel(home, at)
			names = append(names, filepath.ToSlash(name))
		}
	}
	return names
}

// lend is the login the adapter lends the model's turn for the account env names, Python's
// machine_turn._lend: each file it wrote under a HOME of its own, by its path there, read whole
// before that HOME goes; none where it lends none lasting the seconds the harness's `[worker]
// lent_for` says, else lentFor.  The account is the lend's alone: the machine's adapter runs with
// none, reading the copy where the usual login lives.  Which login it read is the adapter's alone
// too, so it holds one whose renewal no file shows to lentFor itself (`AK_UNFOLLOWED_LASTS`).
func lend(model config.Model, adapter string, env map[string]string) map[string]file {
	lasting := float64(lentFor)
	worker, _ := config.Section(model.Harness, "worker")
	switch seconds := worker["lent_for"].(type) {
	case *big.Int:
		lasting, _ = new(big.Float).SetInt(seconds).Float64()
	case float64:
		lasting = seconds
	}
	home, err := os.MkdirTemp("", "ak-lend-")
	if err != nil {
		return nil
	}
	defer os.RemoveAll(home)
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, adapter, "lend", home)
	for key, value := range env {
		cmd.Env = append(cmd.Env, key+"="+value)
	}
	cmd.Env = append(cmd.Env, "AGENTKIT_PROVIDER="+model.Provider, "AK_UNFOLLOWED_LASTS="+strconv.Itoa(lentFor))
	var said bytes.Buffer
	cmd.Stdout, cmd.WaitDelay = &said, time.Second
	host.AdapterCall(cmd)
	if cmd.Run() != nil {
		return nil
	}
	ends := math.Inf(1)
	if said.Len() > 0 {
		if ends, err = strconv.ParseFloat(strings.TrimFunc(said.String(), config.Space), 64); err != nil {
			return nil
		}
	}
	if ends < float64(time.Now().Unix())+lasting {
		return nil
	}
	lent := map[string]file{}
	err = filepath.WalkDir(home, func(at string, _ fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		// a link reads as what it names, as Python's is_file reads it
		info, err := os.Stat(at)
		if err != nil || !info.Mode().IsRegular() {
			return nil
		}
		data, err := os.ReadFile(at)
		head, _ := tar.FileInfoHeader(info, "")
		name, _ := filepath.Rel(home, at)
		lent[filepath.ToSlash(name)] = file{head: *head, data: data}
		return err
	})
	if err != nil {
		return nil
	}
	return lent
}
