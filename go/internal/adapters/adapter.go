// Package adapters carries out the adapter verbs that launch a harness, from its manifest's
// `[launch]` and `[account]` tables, as the Python adapters do: `interactive` prints the line a
// seat opens on, `seat` is Go's wrapper on that line, and `run` is one worker's turn.  It hides
// how a named login shares the usual one's conversations and settings, and how the words of a
// line or a turn are put together; no harness is named here.
package adapters

import (
	"crypto/rand"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/hooks"
)

// Interactive prints the line `ak orch` opens a seat on, for `interactive <model> <effort> [<id>
// [new]]`: the env words, Go's wrapper, then the harness's words, its first prompt last, after a
// `--`, as one word.  On a named login it shares the usual one's conversations and settings
// first, and writes ak's hooks in that login's home where each login keeps its own.  It answers
// the exit code: 2 where it prints no line, as with settings its `[prep]` cannot read, or no
// rulebook to hand over, since a seat opened without the rules it was asked for is worse than
// one that does not open.
func Interactive(root, name string, args []string, out, errOut io.Writer) int {
	if len(args) < 2 {
		fmt.Fprintf(errOut, "%s interactive needs <model> <effort> [session-id [new]]\n", name)
		return 2
	}
	if launch, err := config.Section(name, "launch"); err != nil || launch["seat"] == nil {
		return refused(name, "interactive", err, errOut)
	}
	if _, _, err := answered(name); err != nil {
		fmt.Fprintf(errOut, "%s interactive: %s\n", name, err)
		return 2
	}
	login, _, err := config.Account(name)
	if err == nil && login.Account != "" {
		err = share(login)
	}
	if err != nil {
		fmt.Fprintf(errOut, "%s interactive: %s\n", name, err)
		return 2
	}
	if login.Account != "" {
		if table, ok, _ := config.Hooks(name); ok && table.Login && hooks.Install(table, root, io.Discard, errOut) != 0 {
			return 2
		}
	}
	rulebook := os.Getenv("AGENTKIT_RULEBOOK")
	rules, err := os.ReadFile(rulebook)
	if rulebook == "" || err != nil {
		fmt.Fprintf(errOut, "%s interactive: no rulebook for this seat\n", name)
		return 2
	}
	id := ""
	if len(args) > 2 {
		id = args[2]
	}
	call, err := conversation(name, id, id != "" && len(args) > 3 && args[3] == "new")
	for key, value := range map[string]string{"model": args[0], "effort": args[1],
		"session": os.Getenv("AGENTKIT_SESSION"), "rulebook": rulebook, "rules": string(rules)} {
		call[key] = []string{value}
	}
	seat, env := []string(nil), []string(nil)
	if err == nil {
		seat, _, err = config.Launch(name, "seat", call)
	}
	if err == nil {
		env, _, err = config.Launch(name, "env", call)
	}
	if err != nil {
		return refused(name, "interactive", err, errOut)
	}
	if login.Line && login.Account != "" {
		var own []string
		for _, variable := range login.Unset {
			own = append(own, "-u", variable)
		}
		env = append(append(own, login.Env+"="+login.Home), env...)
	}
	var line []string
	if len(env) > 0 {
		line = append([]string{"env"}, env...)
	}
	line = append(line, filepath.Join(root, "bin", "ak"), "adapter", root, name, "seat", "--")
	line = append(line, seat...)
	launch, _ := config.Section(name, "launch")
	if first := os.Getenv("AGENTKIT_FIRST_PROMPT"); first != "" && launch["first_prompt"] == true {
		line = append(line, "--", first) // after a `--`, so a prompt starting with `-` is no option
	}
	fmt.Fprintln(out, commandhelp.ShellJoin(line))
	return 0
}

// conversation is a call's words for `{conversation}` and `{resume}`: the id's conversation
// resumed, or where fresh a new one opened under it, under a new id where none is given.
func conversation(name, id string, fresh bool) (map[string][]string, error) {
	call := map[string][]string{"conversation": nil, "resume": nil}
	key := "resume"
	if fresh {
		key = "new"
		if id == "" {
			id = uuid()
		}
	}
	if id == "" {
		return call, nil
	}
	words, _, err := config.Launch(name, key, map[string][]string{"id": {id}})
	call["conversation"] = words
	if !fresh {
		call["resume"] = words
	}
	return call, err
}

// refused says why a verb gets no words, and answers 2.
func refused(name, verb string, err error, errOut io.Writer) int {
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
	} else {
		fmt.Fprintf(errOut, "ak adapter: %s %s is not carried out in Go yet\n", name, verb)
	}
	return 2
}

// environ is words with their leading `env` words, each `-u NAME` and `NAME=value`, applied to
// environ, as `env` runs what is left.
func environ(words, environ []string) ([]string, []string) {
	for len(words) > 0 && words[0] == "env" {
		words = words[1:]
		for len(words) > 0 {
			name, _, set := strings.Cut(words[0], "=")
			pair := words[0]
			if words[0] == "-u" && len(words) > 1 {
				name, pair, set, words = words[1], "", true, words[1:]
			}
			if !set || name == "" {
				break
			}
			words = words[1:]
			environ = slices.DeleteFunc(slices.Clone(environ), func(each string) bool {
				key, _, _ := strings.Cut(each, "=")
				return key == name
			})
			if pair != "" {
				environ = append(environ, pair)
			}
		}
	}
	return words, environ
}

// uuid is a new random UUID, as uuidgen writes one.
func uuid() string {
	var b [16]byte
	rand.Read(b[:])
	b[6], b[8] = b[6]&0x0f|0x40, b[8]&0x3f|0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}
