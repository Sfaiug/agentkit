//go:build !windows

package cli

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// `ak orch look FILE` keeps the file byte for byte as one line beside every picture kept before,
// a later one of the same file included, under the name its seat goes by now, and looks at once
// each stand; a file it cannot read, or a write that fails, leaves the pictures as they were.
func TestOrchLookKeepsEachPictureWhole(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "session-acme.json"), `{"renamed": "quay"}`)
	write(t, filepath.Join(state, "session-quay.json"), `{"cwd": "/code/acme"}`)
	shots := t.TempDir()
	chart := filepath.Join(shots, "chart.png")
	every := make([]byte, 256)
	for i := range every {
		every[i] = byte(i)
	}
	write(t, chart, string(every))

	// refused, writing nothing
	assertCall(t, []string{"orch", "look"}, 2, "", "ak orch: usage: ak orch look FILE\n")
	assertCall(t, []string{"orch", "look", chart, chart}, 2, "", "ak orch: usage: ak orch look FILE\n")
	assertCall(t, []string{"orch", "look", chart}, 2, "", "ak orch: ak orch look belongs to a session; run it inside one\n")
	t.Setenv("AGENTKIT_SESSION", "acme")
	assertCall(t, []string{"orch", "look", filepath.Join(shots, "\xff.png")}, 3, "", "ak orch look: not implemented in Go yet\n")

	pictures := filepath.Join(state, "pictures-quay.jsonl")
	var want []string // each line's name and data, in the order kept
	look := func(file, name string, data []byte) {
		t.Helper()
		var out, errOut bytes.Buffer
		if code := Main([]string{"orch", "look", file}, &out, &errOut); code != 0 || errOut.Len() != 0 ||
			out.String() != "quay's done check will see "+name+" as it is now\n" {
			t.Fatalf("%s: got (%d, %q, %q)", file, code, out.String(), errOut.String())
		}
		want = append(want, fmt.Sprintf(`, "name": %q, "data": %q}`, name, base64.StdEncoding.EncodeToString(data)))
	}
	kept := func() string {
		t.Helper()
		data, err := os.ReadFile(pictures)
		if err != nil {
			t.Fatal(err)
		}
		return string(data)
	}
	since := float64(time.Now().UnixNano()) / 1e9
	look(chart, "chart.png", every)
	write(t, chart, "a later chart")
	look(chart+"/.", "chart.png", []byte("a later chart")) // as Python's Path reads it

	before := kept()
	gone := filepath.Join(shots, "gone.png")
	assertCall(t, []string{"orch", "look", gone}, 2, "", "ak orch: cannot keep "+gone+": No such file or directory\n")
	if err := os.Mkdir(pictures+".new", 0o700); err != nil {
		t.Fatal(err)
	}
	assertCall(t, []string{"orch", "look", chart}, 2, "", "ak orch: cannot keep "+chart+": Is a directory\n")
	if err := os.Remove(pictures + ".new"); err != nil {
		t.Fatal(err)
	}
	if kept() != before {
		t.Fatal("a look that failed changed the pictures")
	}

	var wg sync.WaitGroup
	at := map[string]bool{} // what looks at once keep, in whatever order they take the lock
	for i := range 8 {
		shot, data := filepath.Join(shots, fmt.Sprintf("shot-%d.txt", i)), strings.Repeat(strconv.Itoa(i), 4096)
		write(t, shot, data)
		at[fmt.Sprintf(`, "name": %q, "data": %q}`, filepath.Base(shot), base64.StdEncoding.EncodeToString([]byte(data)))] = true
		wg.Add(1)
		go func() {
			defer wg.Done()
			var out, errOut bytes.Buffer
			if code := Main([]string{"orch", "look", shot}, &out, &errOut); code != 0 {
				t.Errorf("%s: got (%d, %q, %q)", shot, code, out.String(), errOut.String())
			}
		}()
	}
	wg.Wait()

	line := regexp.MustCompile(`^\{"at": (\d+\.\d+)(, .*)$`)
	lines := strings.Split(strings.TrimSuffix(kept(), "\n"), "\n")
	if len(lines) != len(want)+len(at) {
		t.Fatalf("%d pictures kept, want %d", len(lines), len(want)+len(at))
	}
	for i, each := range lines {
		found := line.FindStringSubmatch(each)
		if found == nil {
			t.Fatalf("picture %d is not one line as json.dumps writes it: %.80q", i+1, each)
		}
		when, _ := strconv.ParseFloat(found[1], 64)
		if when < since-1 || when > float64(time.Now().UnixNano())/1e9+1 {
			t.Errorf("picture %d kept at %s, not now", i+1, found[1])
		}
		if i < len(want) && found[2] != want[i] || i >= len(want) && !at[found[2]] {
			t.Errorf("picture %d is not a file as it was: %.80q", i+1, found[2])
		}
		delete(at, found[2])
	}
}
