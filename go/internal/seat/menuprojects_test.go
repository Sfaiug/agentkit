package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestMenuFilesProjectlessRecordsBeforeNumbering(t *testing.T) {
	for _, each := range []struct {
		name, want                 string
		repo                       any
		missing, filed, unattended bool
	}{
		{name: "missing", missing: true, want: "atoll"},
		{name: "null", want: "acme"},
		{name: "empty", repo: "", want: "acme"},
		{name: "filed", filed: true},
		{name: "assigned", repo: "atoll", want: "atoll"},
		{name: "missing with unattended run", missing: true, unattended: true, want: "atoll"},
		{name: "null with unattended run", unattended: true},
	} {
		t.Run(each.name, func(t *testing.T) {
			home := sandbox(t)
			acme, atoll := filepath.Join(home, "code", "acme"), filepath.Join(home, "code", "atoll")
			for _, path := range []string{acme, atoll} {
				if err := os.MkdirAll(filepath.Join(path, ".git"), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			record(t, home, "acme", map[string]any{"filed": each.filed})
			path := stateFile(home, "session-acme.json")
			before, _ := run.ReadJSON(path)
			if !each.missing {
				repo := each.repo
				if repo == "atoll" {
					repo = atoll
				}
				before.Set("repo", repo)
				write(t, path, run.Encode(before))
			}
			file := runRecord(t, home, "a", map[string]any{"state": "pass", "merged": true, "repo": atoll, "project": acme, "unattended": each.unattended})
			untouched, _ := os.ReadFile(file)
			found, known := Menu(moment)
			want := map[string]string{"acme": acme, "atoll": atoll}[each.want]
			if !known || len(found.Seats) != 1 || found.Seats[0].Checkout() != want {
				t.Fatalf("known %v: %+v, want %s", known, found.Seats, want)
			}
			after, _ := run.ReadJSON(path)
			if after.Str("repo") != want || !after.Has("repo") {
				t.Fatal(run.Encode(after))
			}
			before.Delete("repo")
			after.Delete("repo")
			data, _ := os.ReadFile(file)
			if !run.Equal(before, after) || string(data) != string(untouched) {
				t.Fatal("filing changed fields beyond the seat's repo")
			}
		})
	}
}
