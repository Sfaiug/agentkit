package helper

import (
	"archive/tar"
	"bytes"
	"cmp"
	"context"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
)

// A Turn is a model turn a machine took, Python's machine_turn.call once it is sent there: the
// adapter's argv, run on the checkout cwd into the out dir, both at this host's absolute paths,
// and the HOME and harness whose conversation comes home with its results, resuming session.
type Turn struct {
	away                             *Away
	argv                             []string
	cwd, out, home, harness, session string
}

// Placed is the model's turn argv, which its adapter runs on the checkout cwd into the out dir with
// env, resuming session where it names one, sent to the machine with the least room that takes
// turns (Start); nil where it runs here, as turnFiles finds nothing to send, no machine takes it,
// or either fails.
func Placed(model config.Model, argv []string, cwd, out string, env map[string]string, session string) *Turn {
	cwd, err := filepath.Abs(cwd)
	if err != nil {
		return nil
	}
	if out, err = filepath.Abs(out); err != nil {
		return nil
	}
	files, err := turnFiles(model, argv[0], cwd, out, env, session)
	if err != nil || files == nil {
		return nil
	}
	// 2048: twice this is 4 GiB, as on 30 Oct 2026 this host's runs peaked at a median of 768 MiB
	// and p90 of 1868 MiB, test pieces included, with one at 5438 MiB.
	away, _, err := start(cwd, 2, 2048, commandhelp.ShellJoin(argv), files, false, func(string) {})
	if err != nil || away == nil {
		return nil
	}
	return &Turn{away, argv, cwd, out, env["HOME"], model.Harness, session}
}

// Run runs the turn there until it ends or ctx does, then takes it off the machine: its events
// stream into the out dir's events.jsonl and the harness's stderr into its stderr.log, as a turn
// here writes them, and once it ended of itself its results come home (back).  Its exit and the
// conversation it leaves; ran false where its room went to another before it started, so it runs
// here.  One ctx ended, one on a machine lost mid-turn and one whose results did not come home
// whole leave the conversation it was given, an id it streamed naming one that is nowhere here,
// the last two failing with `lost`.
func (t *Turn) Run(ctx context.Context, recorded func(out string) string) (code int, session string, ran bool) {
	defer t.away.Finish()
	volumes := []string{"home:" + t.home, "work:" + t.cwd, "out:" + t.out}
	for _, name := range ak {
		volumes = append(volumes, "ak/"+name+":"+filepath.Join(checkout(), name)+":ro")
	}
	args := append([]string{t.away.key, t.away.image, strconv.Itoa(t.away.MemoryMB), t.away.repo}, volumes...)
	cmd := remote(ctx, t.away.Alias, "turn", append(append(args, "--", t.cwd, checkout(), t.away.branch, t.away.base), t.argv...)...)
	// the turn's container ends with the ssh session ctx ends
	host.Group(cmd)
	// the connection, which mac.sh's `renewals` reads for as long as the turn runs
	connection, held, err := os.Pipe()
	if err != nil {
		return lost, t.session, true
	}
	defer held.Close()
	defer connection.Close()
	events, err := os.OpenFile(filepath.Join(t.out, "events.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666)
	if err != nil {
		return lost, t.session, true
	}
	defer events.Close()
	log, err := os.OpenFile(filepath.Join(t.out, "stderr.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666)
	if err != nil {
		return lost, t.session, true
	}
	defer log.Close()
	cmd.Stdin, cmd.Stdout, cmd.Stderr = connection, events, log
	cmd.Run()
	code = lost
	if cmd.ProcessState != nil {
		code = cmd.ProcessState.ExitCode()
	}
	switch {
	case ctx.Err() != nil:
		return code, t.session, true
	case code == full:
		return 0, "", false
	case code == 0:
		if code, session, ok := t.back(recorded); ok {
			return code, session, true
		}
	}
	return lost, t.session, true
}

// back brings the ended turn's results home, Python's machine_turn._home, all of them read before
// any applies: its commits, HEAD moved to its last, the checkout made the commit it left of what it
// left uncommitted and the index HEAD, so that stays uncommitted; then the out dir, but the events
// and stderr streamed here already; last the conversation recorded reads the out dir to name, each
// file whole, which is all of its HOME that comes home: from the folders the harness's `sessions`
// start from, so its caches do not travel.  The turn's exit and that conversation; false where any
// of it did not come.
func (t *Turn) back(recorded func(out string) string) (int, string, bool) {
	places, _ := config.Words(t.harness, "worker", "sessions")
	var folders []string
	for _, place := range places {
		place = strings.TrimPrefix(place, "~/")
		if glob := strings.IndexAny(place, "*?[{"); glob >= 0 {
			place = place[:glob]
		}
		if folder := place[:max(0, strings.LastIndex(place, "/"))]; !slices.Contains(folders, folder) {
			folders = append(folders, folder)
		}
	}
	code, said := ask(t.away.Alias, 10*time.Minute, nil, "collect", append([]string{t.away.key}, folders...)...)
	if code != 0 {
		return 0, "", false
	}
	// Its regular files by relative name alone, each part a name: nothing it sends reaches past the
	// out dir, nor lands elsewhere than the name a glob matched.
	files, names := map[string][]byte{}, []string(nil)
	for in := tar.NewReader(strings.NewReader(said)); ; {
		head, err := in.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return 0, "", false
		}
		if head.Typeflag != tar.TypeReg || slices.ContainsFunc(strings.Split(head.Name, "/"), func(part string) bool {
			return part == "" || part == "." || part == ".."
		}) {
			continue
		}
		if files[head.Name], err = io.ReadAll(in); err != nil {
			return 0, "", false
		}
		names = append(names, head.Name)
	}
	exit, err := strconv.Atoi(strings.TrimFunc(string(files["code"]), config.Space))
	if _, sent := files["back.bundle"]; err != nil || !sent {
		return 0, "", false
	}
	if !t.commits(files["back.bundle"]) {
		return 0, "", false
	}
	for _, name := range names {
		inside, ok := strings.CutPrefix(name, "out/")
		at := filepath.Join(t.out, filepath.FromSlash(inside))
		if !ok || inside == "events.jsonl" || inside == "stderr.log" {
			continue
		}
		// a file that came home unchanged keeps its time: the `harness` receipt's is when the turn
		// began
		if have, err := os.ReadFile(at); err == nil && bytes.Equal(have, files[name]) {
			continue
		}
		if os.MkdirAll(filepath.Dir(at), 0o777) != nil || os.WriteFile(at, files[name], 0o666) != nil {
			return 0, "", false
		}
	}
	session := recorded(t.out)
	globs := patterns(places, session)
	real, err := filepath.EvalSymlinks(t.home)
	if err != nil {
		return 0, "", false
	}
	for _, name := range names {
		inside, ok := strings.CutPrefix(name, "home/")
		parts := strings.Split(inside, "/")
		if !ok || linked(real, parts) || !slices.ContainsFunc(globs, func(glob string) bool { return matches(parts, glob) }) {
			continue
		}
		at := filepath.Join(real, filepath.FromSlash(inside))
		if os.MkdirAll(filepath.Dir(at), 0o777) != nil || !whole(at, files[name]) {
			return 0, "", false
		}
	}
	return exit, session, true
}

// commits applies the bundle the turn left, its refs/ak/left a commit on its last of what it left
// uncommitted: HEAD goes to its last commit, the checkout to that one, and the index to HEAD, by an
// index of their own so nothing here is staged or lost on the way.
func (t *Turn) commits(bundle []byte) bool {
	back, err := os.MkdirTemp("", "ak-back-")
	if err != nil {
		return false
	}
	defer os.RemoveAll(back)
	file := filepath.Join(back, "back.bundle")
	if os.WriteFile(file, bundle, 0o600) != nil {
		return false
	}
	g := gitcall.Git{Repo: t.cwd}
	heads, err := g.Must("bundle", "list-heads", file, "refs/ak/left")
	if left := strings.Fields(heads); err == nil && len(left) > 0 {
		index := gitcall.Git{Repo: t.cwd, Env: []string{"GIT_INDEX_FILE=" + filepath.Join(back, "index")}}
		for _, step := range []struct {
			git  gitcall.Git
			args []string
		}{{g, []string{"bundle", "unbundle", file}}, {index, []string{"read-tree", "HEAD"}}, {index, []string{"add", "-A"}},
			{g, []string{"update-ref", "HEAD", left[0] + "^"}}, {index, []string{"read-tree", "--reset", "-u", left[0]}}, {g, []string{"read-tree", "HEAD"}}} {
			if _, err := step.git.Must(step.args...); err != nil {
				return false
			}
		}
		return true
	}
	return false
}

// matches is whether the name under HOME, by its parts, is a glob's or under one, as Python's
// fnmatchcase reads each part.
func matches(parts []string, glob string) bool {
	each := strings.Split(glob, "/")
	if len(parts) < len(each) {
		return false
	}
	for i, pattern := range each {
		if ok, err := path.Match(pattern, parts[i]); err != nil || !ok {
			return false
		}
	}
	return true
}

// linked is whether a link lies on the way from root to the folder of the name under it, by its
// parts, which a turn run here could leave to lead out of HOME.
func linked(root string, parts []string) bool {
	at := root
	for _, part := range parts[:len(parts)-1] {
		at = filepath.Join(at, part)
		info, err := os.Lstat(at)
		if err != nil {
			return false // nothing further down is there yet
		}
		if info.Mode()&fs.ModeSymlink != 0 {
			return true
		}
	}
	return false
}

// whole writes data at path as a reader sees either the old file or the whole new one: written
// under a name no glob matches, 0600, then renamed over it.
func whole(at string, data []byte) bool {
	part, err := os.CreateTemp(filepath.Dir(at), ".")
	if err != nil {
		return false
	}
	_, err = part.Write(data)
	if err = cmp.Or(err, part.Close()); err == nil {
		err = os.Rename(part.Name(), at)
	}
	if err != nil {
		os.Remove(part.Name())
	}
	return err == nil
}
