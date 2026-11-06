package helper

import (
	"archive/tar"
	"crypto/sha256"
	"fmt"
	"io"
	"maps"
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
)

// recipe is a repository's recipe where its `suite_image:` names none.
const recipe = "tools/helper/Containerfile"

// A file is one the parcel holds: its header but its name, and its bytes, read as the parcel is
// packed from the file on disk at `from` where it names one, so a big one is never held whole.
type file struct {
	head tar.Header
	data []byte
	from string
}

// made is a file of ak's making the parcel holds: of mode, dated 0.
func made(mode int64, data []byte) file {
	return file{head: tar.Header{Mode: mode, ModTime: time.Unix(0, 0)}, data: data}
}

// write puts f in the parcel as name, a directory's with the slash Python's tarfile gives it.
func (f file) write(out *tar.Writer, name string) error {
	head := f.head
	head.Name = name
	if head.Typeflag == tar.TypeDir {
		head.Name += "/"
	}
	if f.from == "" {
		head.Size = int64(len(f.data))
	}
	if err := out.WriteHeader(&head); err != nil {
		return err
	}
	if f.from == "" {
		_, err := out.Write(f.data)
		return err
	}
	in, err := os.Open(f.from)
	if err != nil {
		return err
	}
	defer in.Close()
	_, err = io.CopyN(out, in, head.Size)
	return err
}

// recipeOf is the image the suite's pieces run in and the parcel's files it is built from, Python's
// _recipe, "" where the repository has no recipe: `image/Containerfile`, the file `suite_image:`
// names, else the recipe, and its build's context under `context/`, each file it copies, as HEAD
// has them.  Tagged by their hash, so a changed recipe or copied file builds anew.  An error: the
// recipe copies something other than files HEAD tracks, named by plain path, which cannot be sent.
func recipeOf(cwd, repo string) (string, map[string]file, error) {
	named := gitcall.Declared(cwd, "suite_image")
	if named == "" {
		if code, _, err := (gitcall.Git{Repo: cwd}).Out("cat-file", "-e", "HEAD:"+recipe); err != nil || code != 0 {
			return "", nil, err
		}
		named = recipe
	}
	containerfile, err := tracked(cwd, named)
	if err != nil {
		return "", nil, err
	}
	files := map[string]file{"image/Containerfile": containerfile}
	for _, line := range config.SplitLines(strings.ReplaceAll(string(containerfile.data), "\\\n", " ")) {
		words := strings.Fields(line)
		if len(words) == 0 || !slices.Contains([]string{"COPY", "ADD"}, strings.ToUpper(words[0])) {
			continue
		}
		var sources []string
		for _, word := range words[1:max(1, len(words)-1)] {
			if !strings.HasPrefix(word, "--chown=") && !strings.HasPrefix(word, "--chmod=") {
				sources = append(sources, word)
			}
		}
		if strings.ToUpper(words[0]) == "ADD" || len(sources) == 0 || slices.ContainsFunc(sources, func(word string) bool {
			return strings.ContainsAny(word[:1], "-/[") || strings.ContainsAny(word, "*?[$<") || slices.Contains(strings.Split(word, "/"), "..")
		}) {
			return "", nil, fmt.Errorf("`%s` copies something other than tracked files", strings.TrimSpace(line))
		}
		for _, source := range sources {
			if files["context/"+source], err = tracked(cwd, source); err != nil {
				return "", nil, err
			}
		}
	}
	digest := sha256.New()
	for _, name := range slices.Sorted(maps.Keys(files)) {
		fmt.Fprintf(digest, "%s\x00%d\x00%d\x00", name, files[name].head.Mode, len(files[name].data))
		digest.Write(files[name].data)
	}
	return fmt.Sprintf("ak-helper-%s:%x", repo, digest.Sum(nil)[:6]), files, nil
}

// tracked is the file HEAD has at name; an error where it has none there, or a link.
func tracked(cwd, name string) (file, error) {
	g := gitcall.Git{Repo: cwd}
	_, entry, _, err := g.Bytes("ls-tree", "-z", "HEAD", "--", name)
	if err != nil {
		return file{}, err
	}
	info, at, _ := strings.Cut(string(entry), "\t")
	mode, blob, _ := strings.Cut(info, " blob ")
	if at != path.Clean(name)+"\x00" || mode != "100644" && mode != "100755" {
		return file{}, fmt.Errorf("%s is not a file HEAD tracks", name)
	}
	code, data, _, err := g.Bytes("cat-file", "blob", blob)
	if err == nil && code != 0 {
		err = fmt.Errorf("git cat-file blob %s failed in %s", blob, cwd)
	}
	bits, _ := strconv.ParseInt(mode[3:], 8, 64)
	return made(bits, data), err
}

// pack writes the parcel: files, the recipe's and a turn's own (turnFiles), the piece's script,
// `heads` (HEAD, then the origin branch the suite compares against) and a bundle of their history
// the machine lacks, the whole history the first time, which can outgrow memory: it goes through a
// file, never held whole.
func (a *Away) pack(cwd string, known []string, files map[string]file, parcel io.Writer) error {
	g := gitcall.Git{Repo: cwd}
	revs := []string{"HEAD"}
	if a.base != "" {
		revs = append(revs, "refs/remotes/origin/"+a.base)
	}
	heads, err := g.Must(append([]string{"rev-parse"}, revs...)...)
	if err != nil {
		return err
	}
	have := []string{"--not"}
	for _, sha := range known {
		if code, _, err := g.Out("cat-file", "-e", sha+"^{commit}"); err == nil && code == 0 {
			have = append(have, sha)
		}
	}
	piece, err := carried.ReadFile("piece.sh")
	if err != nil {
		return err
	}
	files = maps.Clone(files)
	// executable, as tools/helper has it and Python's parcel sends it
	files["piece.sh"] = made(0o755, piece)
	files["heads"] = made(0o644, []byte(strings.Join(strings.Fields(heads), " ")+"\n"))
	out := tar.NewWriter(parcel)
	for _, name := range slices.Sorted(maps.Keys(files)) {
		if err := files[name].write(out, name); err != nil {
			return err
		}
	}
	bundle, err := os.CreateTemp("", "ak-bundle-*")
	if err != nil {
		return err
	}
	defer os.Remove(bundle.Name())
	defer bundle.Close()
	made := exec.Command("git", append(append([]string{"-C", cwd, "bundle", "create", "-"}, revs...), have...)...)
	made.Stdout = bundle
	// `git bundle` refuses one with nothing in it: the machine has every commit already
	if made.Run() == nil {
		size, err := bundle.Seek(0, io.SeekEnd)
		if err == nil {
			_, err = bundle.Seek(0, io.SeekStart)
		}
		if err == nil {
			err = out.WriteHeader(&tar.Header{Name: "repo.bundle", Mode: 0o600, Size: size, ModTime: time.Now()})
		}
		if err == nil {
			_, err = io.Copy(out, bundle)
		}
		if err != nil {
			return err
		}
	}
	return out.Close()
}

// least is the MiB each VM of the repository's suites gets at least, more than one ran out of, as
// Python's helper.short keeps it.
func least(repo string) int {
	data, _ := os.ReadFile(filepath.Join(config.Home(), "state", "helper-memory-"+repo))
	mb, _ := strconv.Atoi(strings.TrimSpace(string(data)))
	return mb
}
