package gc

import (
	"bytes"
	"compress/zlib"
	"context"
	"crypto/sha1"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// What the collector proves of a checkout before it plans to take it.

// staleWorktrees is each checkout under ~/.agentkit/wt nothing comes back for (gc.stale_worktrees).
func (r *reads) staleWorktrees() []Item {
	if !safe(wtDir()) {
		return nil
	}
	var found []Item
	for _, wt := range children(wtDir()) {
		if item, ok := r.staleWorktree(wt); ok {
			found = append(found, item)
		}
	}
	return found
}

// staleWorktree is a checkout whose run left no record, a day after its last use, holding no
// work; or one whose run passed and whose delivery ended without a merge, a week after it ended.
// Never one gc reported left behind, one somebody is in, or one not clearable (gc.stale_worktree).
func (r *reads) staleWorktree(wt string) (Item, bool) {
	if r.left[wt] || !clearable(wt) || busy(wt, r.paths) {
		return Item{}, false
	}
	dir := filepath.Join(runsDir(), filepath.Base(wt))
	if !present(filepath.Join(dir, "run.json")) {
		orphan := !run.Writing(dir) && !busy(dir, r.paths) && expired(lastUsed(wt), r.now, day) && !holdsWork(wt)
		return Item{"remove", "orphan-worktree", wt, "no run record", takeStale(wt, true)}, orphan
	}
	record := r.record(dir)
	if record == nil || record.Get("worktree") != wt || record.Str("state") != "pass" || record.Truthy("merged") ||
		!record.Truthy("merge_note") && !record.Truthy("no_merge") || record.Truthy("scratch") || !provablyFinal(record) ||
		!expired(record.Get("finished_at"), r.now, gcAge) || run.Writing(dir) {
		return Item{}, false
	}
	finished, _ := run.Num(record.Get("finished_at"))
	why := fmt.Sprintf("passed, never merged, ended %d days ago", int(math.Floor((r.now-finished)/day)))
	return Item{"remove", "unmerged-worktree", wt, why, takeStale(wt, false)}, true
}

// clearable is a tree gc may empty by hand: straight under ~/.agentkit/wt, work or tmp, this
// user's, reached through no link, and nowhere under ~/code.
func clearable(tree string) bool {
	parent := filepath.Dir(tree)
	return (parent == wtDir() || parent == filepath.Join(config.Home(), "work") || parent == tmpDir()) &&
		safe(tree) && isDir(tree) && !config.UnderCode(tree)
}

// lastUsed is the newest of the checkout's own change, git's write of its index and its HEAD's
// last move by its reflog (gc.last_used).
func lastUsed(wt string) float64 {
	info, _ := os.Lstat(wt)
	newest := mtime(info)
	if code, out := gitIn(wt, "rev-parse", "--path-format=absolute", "--git-path", "index"); code == 0 {
		if info, err := os.Lstat(strings.TrimSuffix(string(out), "\n")); err == nil {
			newest = max(newest, mtime(info))
		}
	}
	if code, out := gitIn(wt, "log", "-g", "-1", "--date=unix", "--format=%gd"); code == 0 {
		moved := strings.TrimRight(string(out), "}\n")
		if at, err := strconv.ParseInt(strings.TrimSpace(moved[strings.LastIndex(moved, "{")+1:]), 10, 64); err == nil {
			newest = max(newest, float64(at))
		}
	}
	return newest
}

// holdsWork is whether removing a checkout no run owns could lose work not yet committed, as git
// sees it (gc.holds_work).
func holdsWork(wt string) bool {
	if !present(filepath.Join(wt, ".git")) {
		return false
	}
	_, linked, ok := gitDirs(wt)
	code, out := gitIn(wt, "rev-parse", "--absolute-git-dir")
	if !ok || !linked || code != 0 {
		return true
	}
	private := strings.TrimSuffix(string(out), "\n")
	locked := present(filepath.Join(private, "locked"))
	if locked {
		reason, err := readBytes(filepath.Join(private, "locked"))
		if err != nil {
			return true
		}
		if string(bytes.TrimRight(reason, "\n")) == gitcall.Making {
			return false
		}
	}
	code, _ = gitIn(wt, "symbolic-ref", "-q", "HEAD")
	if code == 1 {
		return !isFile(filepath.Join(private, gitcall.ScratchMark))
	}
	if code != 0 || locked || submoduleSetUp(wt, private) {
		return true
	}
	code, out = gitIn(wt, "--work-tree="+wt, "--no-optional-locks", "-c", "core.fsmonitor=false", "status", "--porcelain",
		"--untracked-files=all", "--ignore-submodules=none")
	return code != 0 || len(out) > 0
}

// submoduleSetUp is a submodule set up in the checkout, a repository of its own.
func submoduleSetUp(wt, private string) bool {
	if present(filepath.Join(private, "modules")) {
		return true
	}
	code, staged := gitIn(wt, "ls-files", "-s", "-z")
	return code != 0 || slices.ContainsFunc(strings.Split(string(staged), "\x00"), func(entry string) bool {
		_, name, _ := strings.Cut(entry, "\t")
		return strings.HasPrefix(entry, "160000 ") && present(filepath.Join(wt, name, ".git"))
	})
}

// gitIn is git's exit code and output in the checkout at that path, looking no higher and
// carrying none of git's own environment; -1 where it could not run (orch.git_in).
func gitIn(dir string, args ...string) (int, []byte) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	git := exec.CommandContext(ctx, "git", args...)
	git.Dir = dir
	absolute, _ := filepath.Abs(dir)
	git.Env = append(slices.DeleteFunc(os.Environ(), func(pair string) bool { return strings.HasPrefix(pair, "GIT_") }),
		"GIT_CEILING_DIRECTORIES="+filepath.Dir(absolute))
	out, err := git.Output()
	var exit *exec.ExitError
	switch {
	case err == nil:
		return 0, out
	case errors.As(err, &exit) && ctx.Err() == nil:
		return exit.ExitCode(), out
	}
	return -1, nil
}

// gitDirs is the repository's common git directory and whether the path is a worktree added
// from another checkout; false where it is no checkout (orch.git_dirs).
func gitDirs(dir string) (common string, linked, ok bool) {
	dot := filepath.Join(dir, ".git")
	if !present(dot) {
		return "", false, false
	}
	if _, err := os.Stat(filepath.Join(dot, "commondir")); isDir(dot) && !isLink(dot) && err != nil {
		return config.Resolve(dot), false, true
	}
	ask := func(flags ...string) []string {
		code, out := gitIn(dir, append([]string{"rev-parse", "--path-format=absolute"}, flags...)...)
		if code != 0 {
			return nil
		}
		return strings.Split(strings.TrimSuffix(string(out), "\n"), "\n")
	}
	lines := ask("--git-dir", "--git-common-dir")
	if lines != nil && len(lines) != 2 { // a path holding a newline: one at a time
		gitdir, common := ask("--git-dir"), ask("--git-common-dir")
		if gitdir == nil || common == nil {
			return "", false, false
		}
		lines = []string{strings.Join(gitdir, "\n"), strings.Join(common, "\n")}
	}
	if lines == nil {
		return "", false, false
	}
	gitdir, common := config.Resolve(lines[0]), config.Resolve(lines[1])
	return common, gitdir != common, true
}

// collectible is the run's own registered checkout holding its delivered commit and nothing
// else, or one already gone (gc.collectible_worktree).
func collectible(dir string, record *run.Object) bool {
	repo, wt := record.Str("repo"), record.Str("worktree")
	if repo == "" || wt == "" || config.Pure(wt) != filepath.Join(wtDir(), filepath.Base(dir)) || !safe(repo) || !safe(wtDir()) {
		return false
	}
	if wt = config.Pure(wt); !present(wt) {
		return true
	}
	return cleanWorktree(config.Pure(repo), wt, record)
}

// sha40 is a full commit id.
var sha40 = regexp.MustCompile(`^[0-9a-f]{40}$`)

// cleanWorktree proves with reads alone that the checkout is the repository's registered
// worktree at the run's delivered commit, every tracked file as committed and nothing else in it
// but build junk (retention.clean_worktree).  Git is never run: it would refresh the index.
func cleanWorktree(repo, wt string, record *run.Object) bool {
	common, err := commonDirectory(repo)
	if err != nil {
		return false
	}
	private, err := gitDirectory(wt)
	if err != nil || !safe(wt) || filepath.Dir(private) != filepath.Join(common, "worktrees") {
		return false
	}
	if named, err := text(filepath.Join(private, "gitdir")); err != nil || named != filepath.Join(wt, ".git") {
		return false
	}
	raw, err := text(filepath.Join(private, "HEAD"))
	if err != nil || !strings.HasPrefix(raw, "ref: ") {
		return false
	}
	head, err := gitRef(common, raw[5:])
	if err != nil || !sha40.MatchString(head) {
		return false
	}
	review := record.Dict("review")
	if review == nil {
		if record.Truthy("review") {
			return false
		}
		review = run.NewObject()
	}
	if delivered := first(record, "delivery_sha"); delivered != nil || review.Truthy("head_sha") {
		if delivered == nil {
			delivered = review.Get("head_sha")
		}
		if delivered != head {
			return false
		}
	} else {
		branch := "main"
		if named := first(record, "target", "base"); named != nil {
			if branch, _ = named.(string); branch == "" {
				return false
			}
		}
		if tip, err := gitRef(common, "refs/heads/"+branch); err != nil || tip != head {
			return false
		}
	}
	var expected any
	if review.Get("head_sha") == head && review.Truthy("tree_sha") {
		expected = review.Get("tree_sha")
	} else {
		// an older record saved no tree: its loose commit object names one
		commit, err := looseCommit(common, head)
		if err != nil {
			return false
		}
		expected = commit
	}
	entries, err := indexEntries(filepath.Join(private, "index"))
	if err != nil {
		return false
	}
	if root, err := indexTree(entries); err != nil || expected != root {
		return false
	}
	tracked, parents := map[string]bool{}, map[string]bool{}
	for _, each := range entries {
		name := filepath.Join(wt, each.name)
		tracked[name] = true
		for parent := filepath.Dir(name); parent != wt && below(parent, wt); parent = filepath.Dir(parent) {
			parents[parent] = true
		}
	}
	permitted := func(at string) bool {
		if at == wt || at == filepath.Join(wt, ".git") || tracked[at] || parents[at] {
			return true
		}
		relative, _ := filepath.Rel(wt, at)
		for _, part := range strings.Split(relative, "/") {
			for _, pattern := range gitcall.Junk {
				name := part
				if strings.HasSuffix(pattern, "/") {
					name += "/" // a folder's pattern
				}
				if matched, _ := path.Match(pattern, name); matched {
					return true
				}
			}
		}
		return false
	}
	// tracked folders first: unknown output makes the checkout ineligible before any hashing
	folders := []string{wt}
	for parent := range parents {
		folders = append(folders, parent)
	}
	for _, folder := range folders {
		names, err := listdir(folder)
		if !safe(folder) || err != nil || slices.ContainsFunc(names, func(name string) bool { return !permitted(filepath.Join(folder, name)) }) {
			return false
		}
	}
	snapshot, ok := tree(wt, nil, permitted)
	if !ok {
		return false
	}
	for _, each := range entries {
		file := filepath.Join(wt, each.name)
		info, err := os.Stat(file)
		if !safe(file) || err != nil || !info.Mode().IsRegular() || (info.Mode().Perm()&0o111 != 0) != (each.mode == 0o100755) {
			return false
		}
		data, err := readBytes(file)
		if err != nil || !bytes.Equal(gitHash("blob", data), each.oid) {
			return false
		}
	}
	again, ok := tree(wt, nil, permitted)
	return ok && slices.Equal(snapshot, again)
}

// text is a safe file's UTF-8 text, its surrounding space cut.
func text(file string) (string, error) {
	data, err := readBytes(file)
	if err == nil && !utf8.Valid(data) {
		err = errors.New("not UTF-8")
	}
	return strings.TrimSpace(string(data)), err
}

// gitDirectory is a checkout's own git directory: its .git folder, or the one its .git file
// names (retention.git_directory).
func gitDirectory(checkout string) (string, error) {
	dot := filepath.Join(checkout, ".git")
	if !safe(dot) {
		return "", errors.New("unsafe git directory")
	}
	if isFile(dot) {
		pointer, err := text(dot)
		prefix, value, found := strings.Cut(pointer, ": ")
		if err != nil || prefix != "gitdir" || !found {
			return "", errors.New("invalid git pointer")
		}
		if !filepath.IsAbs(value) {
			value = filepath.Join(checkout, value)
		}
		dot = filepath.Clean(value)
	}
	if !safe(dot) {
		return "", errors.New("unsafe git directory")
	}
	return dot, nil
}

// commonDirectory is the repository a checkout is of (retention.common_directory).
func commonDirectory(repo string) (string, error) {
	dir, err := gitDirectory(repo)
	if err != nil || !present(filepath.Join(dir, "commondir")) {
		return dir, err
	}
	named, err := text(filepath.Join(dir, "commondir"))
	if err != nil {
		return "", err
	}
	if !filepath.IsAbs(named) {
		named = filepath.Join(dir, named)
	}
	if dir = filepath.Clean(named); !safe(dir) {
		return "", errors.New("unsafe git directory")
	}
	return dir, nil
}

// gitRef is a branch's commit, loose or packed, "" for none (retention.git_ref).
func gitRef(common, ref string) (string, error) {
	if !strings.HasPrefix(ref, "refs/heads/") || climbs(config.Pure(ref)) {
		return "", nil
	}
	if loose := filepath.Join(common, ref); present(loose) {
		return text(loose)
	}
	packed := filepath.Join(common, "packed-refs")
	if !safe(packed) {
		return "", nil
	}
	refs, err := text(packed)
	if err != nil {
		return "", err
	}
	for _, line := range config.SplitLines(refs) {
		if sha, name, _ := strings.Cut(line, " "); name == ref {
			return sha, nil
		}
	}
	return "", nil
}

// looseCommit is the tree a loose commit object names, once its bytes prove its id.
func looseCommit(common, head string) (string, error) {
	data, err := readBytes(filepath.Join(common, "objects", head[:2], head[2:]))
	if err != nil {
		return "", err
	}
	inflate, err := zlib.NewReader(bytes.NewReader(data))
	if err != nil {
		return "", err
	}
	object, err := io.ReadAll(inflate)
	_, body, found := bytes.Cut(object, []byte{0})
	if err != nil || !found || hex.EncodeToString(gitHash("commit", body)) != head {
		return "", errors.New("not that commit")
	}
	line, _, _ := bytes.Cut(bytes.ReplaceAll(body, []byte("\r"), []byte("\n")), []byte("\n"))
	if len(body) == 0 || !utf8.Valid(line) {
		return "", errors.New("no tree")
	}
	return strings.TrimPrefix(string(line), "tree "), nil
}

// indexed is one entry of a git index.
type indexed struct {
	name string
	mode uint32
	oid  []byte
}

// indexEntries reads an ordinary SHA-1 git index, versions 2 and 3; split and sparse indexes,
// conflicts, links, submodules and odd names are refused (retention.index_entries).
func indexEntries(file string) ([]indexed, error) {
	data, err := readBytes(file)
	if err != nil {
		return nil, err
	}
	unsupported := errors.New("unsupported index")
	if len(data) < 32 {
		return nil, unsupported
	}
	sum := sha1.Sum(data[:len(data)-20])
	version := binary.BigEndian.Uint32(data[4:])
	if string(data[:4]) != "DIRC" || version != 2 && version != 3 || !bytes.Equal(sum[:], data[len(data)-20:]) {
		return nil, unsupported
	}
	var entries []indexed
	seen := map[string]bool{}
	offset := 12
	for range binary.BigEndian.Uint32(data[8:]) {
		start := offset
		if offset+62 > len(data) {
			return nil, unsupported
		}
		mode := binary.BigEndian.Uint32(data[offset+24:])
		oid := data[offset+40 : offset+60]
		flags := binary.BigEndian.Uint16(data[offset+60:])
		if offset += 62; flags&0x4000 != 0 {
			offset += 2
		}
		end := -1
		if offset <= len(data) {
			end = bytes.IndexByte(data[offset:], 0)
		}
		if end < 0 {
			return nil, unsupported
		}
		end += offset
		name := string(data[offset:end])
		offset = start + (end-start+8)/8*8
		if flags&0x3000 != 0 || mode != 0o100644 && mode != 0o100755 || name == "" || name[0] == '/' ||
			slices.Contains(strings.Split(name, "/"), "..") || seen[name] {
			return nil, unsupported
		}
		seen[name] = true
		entries = append(entries, indexed{name, mode, oid})
	}
	// only optional extensions, whose signatures are uppercase: `link` is a split index
	for offset < len(data)-20 {
		if offset+8 > len(data) || data[offset] < 'A' || data[offset] > 'Z' {
			return nil, unsupported
		}
		offset += 8 + int(binary.BigEndian.Uint32(data[offset+4:]))
	}
	if offset != len(data)-20 {
		return nil, unsupported
	}
	return entries, nil
}

// indexTree is the id of the tree an index's entries make (retention.index_tree).
func indexTree(entries []indexed) (string, error) {
	type folder map[string]any // a name's entry, or the folder it is
	root := folder{}
	for _, each := range entries {
		parts := strings.Split(each.name, "/")
		at := root
		for _, part := range parts[:len(parts)-1] {
			if _, held := at[part]; !held {
				at[part] = folder{}
			}
			sub, ok := at[part].(folder)
			if !ok {
				return "", errors.New("a file where a folder is")
			}
			at = sub
		}
		at[parts[len(parts)-1]] = each
	}
	var digest func(folder) []byte
	digest = func(node folder) []byte {
		names := make([]string, 0, len(node))
		for name := range node {
			names = append(names, name)
		}
		key := func(name string) string {
			if _, ok := node[name].(folder); ok {
				return name + "/"
			}
			return name
		}
		slices.SortFunc(names, func(a, b string) int { return strings.Compare(key(a), key(b)) })
		var data []byte
		for _, name := range names {
			mode, oid := uint32(0o40000), []byte(nil)
			if sub, ok := node[name].(folder); ok {
				oid = digest(sub)
			} else {
				each := node[name].(indexed)
				mode, oid = each.mode, each.oid
			}
			data = append(append(append(fmt.Appendf(data, "%o ", mode), name...), 0), oid...)
		}
		return gitHash("tree", data)
	}
	return hex.EncodeToString(digest(root)), nil
}

func gitHash(kind string, data []byte) []byte {
	sum := sha1.Sum(append(fmt.Appendf(nil, "%s %d\x00", kind, len(data)), data...))
	return sum[:]
}
