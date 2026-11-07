package cli

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

func init() { commands["orch look"] = orchLook }

// orchLook keeps a picture of a screen the seat's work changed for its done check, as the file
// is now and beside every one kept before, a later one of the same file included
// (done_check.look).  The seat's, as its plan is: under its lock, which a rename takes too, so
// under the name it goes by now.
func orchLook(args []string, out, errOut io.Writer) int {
	seat, _, err := config.CurrentSession()
	if err != nil {
		fmt.Fprintf(errOut, "ak orch: %v\n", err)
		return 2
	}
	if seat == "" {
		fmt.Fprintln(errOut, "ak orch: ak orch look belongs to a session; run it inside one")
		return 2
	}
	if !utf8.ValidString(args[0]) {
		return notImplemented(errOut, "orch look") // Python writes and says it with lone surrogates
	}
	file, name := pythonPath(args[0])
	current, err := keepPicture(seat, file, name)
	if err != nil {
		fmt.Fprintf(errOut, "ak orch: cannot keep %s: %s\n", args[0], config.Strerror(err))
		return 2
	}
	fmt.Fprintf(out, "%s's done check will see %s as it is now\n", current, name)
	return 0
}

// keepPicture appends a line of the file read whole to the seat's pictures, and is the name the
// seat goes by now.
func keepPicture(seat, file, name string) (current string, err error) {
	data, err := os.ReadFile(file)
	if err != nil {
		return "", err
	}
	kept := run.Line(run.Fields("at", float64(time.Now().UnixNano())/1e9, "name", name,
		"data", base64.StdEncoding.EncodeToString(data))) + "\n"
	if err := config.EnsureDirs(); err != nil {
		return "", err // as Python's session_lock makes them first
	}
	err = notify.Held(context.Background(), seat, func(now string) error {
		current = now
		// written whole beside the pictures, then in their place: a write cut short leaves them
		// as they were, never a torn line the next one is appended to
		pictures := filepath.Join(config.Home(), "state", config.SeatFileNames(now)["pictures"])
		before, err := os.ReadFile(pictures)
		if err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		if err := os.WriteFile(pictures+".new", append(before, kept...), 0o666); err != nil {
			return err
		}
		return os.Rename(pictures+".new", pictures)
	})
	return current, err
}

// pythonPath is a path as Python's Path reads it, and its name (PurePath.name): its empty and
// `.` parts dropped, so `shots/chart.png/` opens chart.png and an empty one opens `.`, named "".
func pythonPath(path string) (string, string) {
	path = filepath.ToSlash(path)
	parts := slices.DeleteFunc(strings.Split(path, "/"), func(part string) bool { return part == "" || part == "." })
	root := ""
	if strings.HasPrefix(path, "/") {
		root = "/"
	}
	if strings.HasPrefix(path, "//") && !strings.HasPrefix(path, "///") {
		root = "//" // POSIX leaves a root of exactly two slashes to the system
	}
	opened, name := root+strings.Join(parts, "/"), ""
	if len(parts) > 0 {
		name = parts[len(parts)-1]
	}
	if opened == "" {
		opened = "."
	}
	return opened, name
}
