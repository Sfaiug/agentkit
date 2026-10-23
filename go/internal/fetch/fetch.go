// Package fetch prints where a named file can be read on this host: a file already here at
// once, a Mac file once the Mac's bridge delivers it through ~/.agentkit/macbridge.
package fetch

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

var decimal = regexp.MustCompile(`^[+-]?(?:[0-9](?:_?[0-9])*(?:\.(?:[0-9](?:_?[0-9])*)?)?|\.[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?$`)

const (
	invalidPath = "a file path must be non-empty and contain no tabs or newlines"
	poll        = 100 * time.Millisecond
)

func Validate(args []string) string {
	if len(args) == 1 && args[0] == "--serve" {
		return ""
	}
	if len(args) > 0 && args[0] == "--" {
		args = args[1:]
	}
	if len(args) == 0 {
		return commandhelp.Usage("fetch")
	}
	for _, arg := range args {
		if arg == "--serve" {
			return commandhelp.Usage("fetch")
		}
	}
	if _, ok := timeout(); !ok {
		return "AK_FETCH_TIMEOUT must be a finite, non-negative number"
	}
	return ""
}

// timeout is how many seconds a Mac fetch waits, written as Python's float() reads it.
func timeout() (float64, bool) {
	raw, ok := os.LookupEnv("AK_FETCH_TIMEOUT")
	if !ok {
		return 25, true
	}
	raw = strings.TrimSpace(raw)
	value, err := strconv.ParseFloat(strings.ReplaceAll(raw, "_", ""), 64)
	return value, decimal.MatchString(raw) && err == nil && value >= 0
}

// Main runs arguments Validate accepted.
func Main(args []string, out, errOut io.Writer) int {
	if len(args) == 1 && args[0] == "--serve" {
		return serve(os.Stdin, out, errOut)
	}
	if args[0] == "--" {
		args = args[1:]
	}
	wait, _ := timeout()
	code := 0
	for _, arg := range args {
		found, err := one(arg, wait)
		if err != nil {
			fmt.Fprintln(errOut, "ak fetch: "+err.Error())
			code = 1
			continue
		}
		fmt.Fprintln(out, found)
	}
	return code
}

func normalize(value string) (string, string) {
	if value == "" || strings.ContainsAny(value, "\x00\r\n\t") {
		return "", invalidPath
	}
	if _, err := os.Stat(config.Expand(value)); err == nil {
		return config.Expand(value), ""
	}
	value = strings.TrimSpace(value)
	if len(value) > 1 && value[0] == value[len(value)-1] && (value[0] == '\'' || value[0] == '"') {
		value = value[1 : len(value)-1]
	}
	// Terminal and Finder escape punctuation when a path is dropped into a shell.
	runes := []rune(value)
	var out strings.Builder
	for i := 0; i < len(runes); i++ {
		if runes[i] == '\\' && i+1 < len(runes) && (unicode.IsSpace(runes[i+1]) || strings.ContainsRune("\\'\"()[]{}<>|;&!$`*?#~", runes[i+1])) {
			i++
		}
		out.WriteRune(runes[i])
	}
	value = out.String()
	if value == "" || strings.ContainsAny(value, "\x00\r\n\t") {
		return "", invalidPath
	}
	return config.Expand(value), ""
}

func one(value string, wait float64) (string, error) {
	found, problem := normalize(value)
	if problem != "" {
		return "", errors.New(problem)
	}
	if _, err := os.Stat(found); err == nil {
		return filepath.Abs(found)
	}
	return ask(found, wait)
}

// bridge makes the folders the bridge exchanges files in, the owner's alone, and returns its root.
func bridge() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	root := filepath.Join(home, ".agentkit", "macbridge")
	for _, folder := range []string{"requests", "inbox"} {
		if err := os.MkdirAll(filepath.Join(root, folder), 0700); err != nil {
			return "", err
		}
	}
	return root, nil
}

var unsafe = regexp.MustCompile(`[^A-Za-z0-9._-]`)

// basename is the Mac path's file name as safe for a remote shell; the bridge sends it as is.
func basename(mac string) string {
	name := path.Base(mac)
	if name == "/" || name == "." {
		return "file"
	}
	return unsafe.ReplaceAllString(name, "_")
}

// extension is Python's Path.suffix: a name's last dot, never its first character or its last.
func extension(name string) string {
	if i := strings.LastIndex(name, "."); i > 0 && i < len(name)-1 {
		return name[i:]
	}
	return ""
}

func exists(name string) bool {
	_, err := os.Stat(name)
	return err == nil
}

// ask leaves a request for the Mac and waits for its answer in the inbox: the file, an
// error, or a mark that the file is gone. Whatever happens, no request or mark stays behind.
func ask(mac string, wait float64) (string, error) {
	root, err := bridge()
	if err != nil {
		return "", err
	}
	var random [8]byte
	if _, err := rand.Read(random[:]); err != nil {
		return "", err
	}
	ident := hex.EncodeToString(random[:])
	name := basename(mac)
	request := filepath.Join(root, "requests", ident)
	temp := filepath.Join(root, "requests", "."+ident+".tmp")
	inbox := filepath.Join(root, "inbox")
	dest := filepath.Join(inbox, ident+extension(name))
	missing := filepath.Join(inbox, ident+".missing")
	ready := filepath.Join(inbox, "."+ident+".ready")
	failed := filepath.Join(inbox, "."+ident+".error")
	delivered := ""
	defer func() {
		for _, leftover := range []string{temp, request, ready, failed} {
			os.Remove(leftover)
		}
		// A delivered file may itself be named <ident>.missing.
		if missing != delivered {
			os.Remove(missing)
		}
	}()
	data, _ := json.Marshal(struct {
		Path     string `json:"path"`
		Basename string `json:"basename"`
	}{mac, name})
	if err := os.WriteFile(temp, append(data, '\n'), 0600); err != nil {
		return "", err
	}
	if err := os.Rename(temp, request); err != nil {
		return "", err
	}
	start := time.Now()
	for {
		if text, err := os.ReadFile(failed); err == nil {
			reason := strings.TrimSpace(string(text))
			if reason == "" {
				reason = "the Mac could not send that file"
			}
			return "", fmt.Errorf("%s: %s", mac, reason)
		}
		// .missing is also a legal file extension. The Mac publishes a receipt first
		// for that case, so even an empty file can be distinguished from a failure.
		if info, err := os.Stat(dest); err == nil && info.Mode().IsRegular() && (dest != missing || exists(ready)) {
			delivered = dest
			return dest, nil
		}
		if exists(missing) {
			return "", fmt.Errorf("the Mac no longer has that file: %s", mac)
		}
		remaining := wait - time.Since(start).Seconds()
		if remaining <= 0 {
			return "", fmt.Errorf("%s: no answer from the Mac bridge in %.6gs; the Mac may be asleep or offline, or ak macbridge is not running there (open ak on the Mac)", mac, wait)
		}
		time.Sleep(time.Duration(math.Min(poll.Seconds(), remaining) * float64(time.Second)))
	}
}
