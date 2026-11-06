// Package guard is what a seat's own tmux, gh, git, scp, rsync, sftp and ssh may do, as Python's
// agentkit/guard.py decides it, and it hides everything behind that answer: how much of each
// tool's arguments must be read to tell, which session a tmux target falls on, asked of the real
// tmux, which seats ak keeps, where `~/code` and the live host are, the file that says a seat's
// ssh reached that host, and which project a checkout is and how many lines its branch adds.  Its
// one call is Decide.
//
// It reads a call's final argv, so it guards a seat's mistakes, not a seat that means to get
// round it: guard.py's opening names what is out of reach, by design, and every line of that
// holds here.
package guard

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
)

// refusals are what each tool asks: why this call may not run, "" where it may, or an error where
// the guard could not tell.
var refusals = map[string]func(args []string, real string) (string, error){
	"tmux": tmuxRefusal, "gh": ghRefusal, "git": worktreeRefusal,
	"scp": transferRefusal, "rsync": transferRefusal, "sftp": transferRefusal, "ssh": liveReach,
}

// Decide is what to do with this seat's call of the tool by that name, its argv after the name
// and the real binary's path: why it is refused, or else the arguments to run the real tool with.
// A guard that fails in any way runs the call untouched: a broken guard takes no seat's git with it.
func Decide(name, real string, args []string) (refusal string, run []string) {
	defer func() {
		if recover() != nil {
			refusal, run = "", args
		}
	}()
	if ask, guarded := refusals[name]; guarded {
		reason, err := ask(args, real)
		if err != nil {
			return "", args
		}
		if reason != "" {
			return reason, nil
		}
	}
	if name == "tmux" {
		owned, err := tmuxOwned(args)
		if err != nil {
			return "", args
		}
		return "", owned
	}
	return "", args
}

var (
	ends   = []string{"kill-server", "kill-session", "kill-window", "kill-pane"}
	types  = []string{"send-keys", "paste-buffer", "send-prefix", "pipe-pane"}
	starts = []string{"new-session", "new-window", "split-window", "respawn-pane", "respawn-window"}
	// the options besides -t that take a value
	valued = map[string]string{"send-keys": "cN", "paste-buffer": "bs"}
	// pipe-pane types into the pane only with -I: else it reads out
	requires = map[string]byte{"pipe-pane": 'I'}
	aliases  = map[string]string{"killp": "kill-pane", "killw": "kill-window", "send": "send-keys", "pasteb": "paste-buffer",
		"pipep": "pipe-pane", "new": "new-session", "neww": "new-window", "splitw": "split-window", "respawnp": "respawn-pane",
		"respawnw": "respawn-window"}
)

// the tmux server options that take a value
const serverValued = "fLScT"

// tmuxOwned is the call with what it starts speaking for the seat: tmux starts a pane's process in
// its server's environment, not the caller's, so each command that starts one gets the seat's
// name, and each new session its maker's for the tick's cleanup, `-e` belonging to the
// new-session itself, so `-A` attaching an existing one leaves its owner alone.  A `-e` of the
// seat's own later in the command wins, as tmux takes the last.
func tmuxOwned(args []string) ([]string, error) {
	own, _, err := config.CurrentSession()
	if err != nil || own == "" {
		return args, err
	}
	_, first := serverOptions(args)
	result := slices.Clone(args[:first])
	changed := false
	for _, cmd := range commands(args[first:]) {
		if len(result) > first {
			result = append(result, ";")
		}
		var given []string
		command := knownCommand(cmd[0], starts)
		if command != "" {
			given = append(given, "-e", "AGENTKIT_SESSION="+own)
			changed = true
		}
		if command == "new-session" {
			given = append(given, "-e", "AK_TMUX_OWNER="+own)
		}
		result = append(append(append(result, cmd[0]), given...), cmd[1:]...)
	}
	if !changed {
		return args, nil
	}
	return result, nil
}

// knownCommand is the command of that list a word runs: its full name, an alias, or a unique
// prefix of one, as tmux takes any unambiguous prefix and refuses the rest, running nothing.
func knownCommand(word string, known []string) string {
	word = cmp.Or(aliases[word], word)
	if slices.Contains(known, word) {
		return word
	}
	var hits []string
	for _, each := range known {
		if word != "" && strings.HasPrefix(each, word) {
			hits = append(hits, each)
		}
	}
	if len(hits) == 1 {
		return hits[0]
	}
	return ""
}

// serverOptions is the -L/-S server a tmux call names and the index of its first word that is no
// option, read as getopt: bundled booleans and a valued option's value in the same word.
func serverOptions(args []string) (server []string, first int) {
	i := 0
	for i < len(args) && strings.HasPrefix(args[i], "-") && args[i] != "--" {
		flags := args[i][1:]
		i++
		for at := 0; at < len(flags); at++ {
			if !strings.Contains(serverValued, flags[at:at+1]) {
				continue
			}
			value := flags[at+1:]
			if value == "" && i < len(args) {
				value = args[i]
				i++
			}
			if flags[at] == 'L' || flags[at] == 'S' {
				server = append(server, "-"+flags[at:at+1], value)
			}
			break
		}
	}
	if i < len(args) && args[i] == "--" {
		i++
	}
	return server, i
}

// hasFlag is whether that boolean flag is among a command's option clusters, read as getopt: a
// letter after a valued option, or after -t, is that option's value.
func hasFlag(args []string, letter byte, valued string) bool {
	for _, arg := range args {
		if arg == "--" {
			break
		}
		if !strings.HasPrefix(arg, "-") || strings.HasPrefix(arg, "--") {
			continue
		}
		for at := 1; at < len(arg); at++ {
			if arg[at] == letter {
				return true
			}
			if arg[at] == 't' || strings.IndexByte(valued, arg[at]) >= 0 {
				break
			}
		}
	}
	return false
}

// options are a command's -t target, -a and -C, read as tmux's getopt: a valued option's value may
// ride in the same word or be the next.
func options(args []string, valued string) (target string, every, clear bool) {
	i := 0
	for i < len(args) && strings.HasPrefix(args[i], "-") && args[i] != "--" {
		flags := args[i][1:]
		i++
		for at := 0; at < len(flags); at++ {
			switch {
			case flags[at] == 'a':
				every = true
			case flags[at] == 'C':
				clear = true
			case flags[at] == 't' || strings.IndexByte(valued, flags[at]) >= 0:
				value := flags[at+1:]
				if value == "" && i < len(args) {
					value = args[i]
					i++
				}
				if flags[at] == 't' {
					target = value
				}
				at = len(flags)
			}
		}
	}
	return target, every, clear
}

// commands are each tmux command of one call's args: tmux ends one only at a word whose last
// character is an unescaped `;`, any other `;` being literal.
func commands(args []string) [][]string {
	var found [][]string
	var current []string
	for _, word := range args {
		if !strings.HasSuffix(word, ";") || strings.HasSuffix(word, `\;`) {
			current = append(current, word)
			continue
		}
		if head := word[:len(word)-1]; head != "" {
			current = append(current, head)
		}
		if len(current) > 0 {
			found = append(found, current)
		}
		current = nil
	}
	if len(current) > 0 {
		found = append(found, current)
	}
	return found
}

// asked is what the real tmux answers a read-only question, "" where it refuses or takes too long.
func asked(real string, server []string, question ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, real, slices.Concat(server, question)...).Output()
	if err != nil {
		return ""
	}
	return string(out)
}

// sessions are the sessions on that server, ak's control session aside; none with no server to ask.
func sessions(real string, server []string) []string {
	var names []string
	for _, line := range strings.Split(asked(real, server, "list-sessions", "-F", "#{session_id}\t#{session_name}"), "\n") {
		if _, name, ok := strings.Cut(line, "\t"); ok && name != config.Control {
			names = append(names, name)
		}
	}
	return names
}

// targetSession is the session a command's -t falls on, "" for none, asked of the real tmux with a
// read-only command of the SAME target type, so the answer is the command's own and none of tmux's
// lookup is copied here; inheriting the seat's $TMUX, it reads a current-relative target as the
// seat's own session.
func targetSession(real string, server []string, command, target string) string {
	question := []string{"display-message", "-p", "-t", target, "#{session_name}"}
	switch command {
	case "kill-session":
		question = []string{"list-windows", "-t", target, "-F", "#{session_name}"}
	case "kill-window":
		question = []string{"list-panes", "-t", target, "-F", "#{session_name}"}
	}
	for _, line := range strings.Split(asked(real, server, question...), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			return line
		}
	}
	return ""
}

// isSeat is whether ak keeps a record of that tmux session.
func isSeat(name string) bool {
	path, err := config.SessionPath(name)
	if err != nil {
		return false
	}
	_, err = os.Stat(path)
	return err == nil
}

// nameNow is the name a session goes by now, following a rename.
func nameNow(name string) string {
	now, _, err := config.ResolveSession(name)
	if err != nil {
		return config.Fold(name)
	}
	return now
}

// tmuxRefusal is why the seat may not run this tmux call.  Every command the call holds is
// checked, since tmux runs each, and a refused one takes the whole call with it.
func tmuxRefusal(args []string, real string) (string, error) {
	own, _, err := config.CurrentSession()
	if err != nil || own == "" {
		return "", err
	}
	server, first := serverOptions(args)
	onServer := sync.OnceValue(func() []string { return sessions(real, server) })
	for _, cmd := range commands(args[first:]) {
		command := knownCommand(cmd[0], slices.Concat(ends, types))
		if command == "" {
			continue
		}
		rest := cmd[1:]
		if letter, needs := requires[command]; needs && !hasFlag(rest, letter, valued[command]) {
			continue
		}
		var hit []string
		if command == "kill-server" {
			hit = slices.Clone(onServer())
		} else {
			target, every, clear := options(rest, valued[command])
			switch {
			case command == "kill-session" && clear: // it clears alerts; the session lives
				continue
			case command == "kill-session" && every: // it ends every session but the one kept
				keep := own
				if target != "" {
					keep = targetSession(real, server, command, target)
				}
				hit = slices.DeleteFunc(slices.Clone(onServer()), func(name string) bool { return name == keep })
			case target == "": // the current pane, this seat's own on its server
				continue
			default:
				hit = []string{targetSession(real, server, command, target)}
			}
		}
		others := slices.DeleteFunc(hit, func(name string) bool { return name == "" || nameNow(name) == own || !isSeat(name) })
		if len(others) == 0 {
			continue
		}
		slices.Sort(others)
		whose := "other sessions' seats"
		if len(others) == 1 {
			whose = "another session's seat"
		}
		named := strings.Join(others, ", ")
		if slices.Contains(types, command) {
			return fmt.Sprintf("ak refused `tmux %s`: it would type into %s, %s. Nothing a seat writes is typed into another seat.", command, named, whose), nil
		}
		return fmt.Sprintf("ak refused `tmux %s`: it would end %s, %s. A seat never ends another seat; ask the owner.", command, named, whose), nil
	}
	return "", nil
}

// ghCommand is a gh call's first two command words (`pr merge`, `pr create`), past the options
// between them and -R/--repo's value, gh's one persistent value flag before a subcommand.
func ghCommand(args []string) []string {
	var words []string
	for i := 0; i < len(args) && len(words) < 2; i++ {
		switch {
		case args[i] == "-R" || args[i] == "--repo":
			i++
		case !strings.HasPrefix(args[i], "-"):
			words = append(words, args[i])
		}
	}
	return words
}

// ghRefusal is why the seat may not run this gh call: merging is ak's job once a PR passes review
// with green checks, and a `gh pr create` too big for the seat is refused (prCreateRefusal).  The
// one seat that may merge is the inbox, which `ak watch` asks before merging someone else's PR.
func ghRefusal(args []string, _ string) (string, error) {
	own, _, err := config.CurrentSession()
	if err != nil || own == "" {
		return "", err
	}
	command := ghCommand(args)
	if slices.Equal(command, []string{"pr", "create"}) {
		return prCreateRefusal(args)
	}
	if !slices.Equal(command, []string{"pr", "merge"}) || own == nameNow(cmp.Or(os.Getenv("AGENTKIT_INBOX_SESSION"), "inbox")) {
		return "", nil
	}
	return "ak refused `gh pr merge`: merging is ak's job once a PR passes review with green " +
		"checks. Leave it to land through the line; a seat runs no `gh pr merge` of its own.", nil
}

// git's options before its command that take the next word as their value
var gitValued = []string{"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix", "--attr-source"}

// worktreeRefusal is why the seat's git may not run: a `git worktree add` whose new checkout lands
// in ~/code, which holds only the owner's.  The path is read as git reads it: from the working
// directory and every -C before the command, past `worktree add`'s options, of which -b, -B and
// --reason take a value.
func worktreeRefusal(args []string, _ string) (string, error) {
	base, err := os.Getwd()
	if err != nil {
		return "", err
	}
	i := 0
	for i < len(args) && strings.HasPrefix(args[i], "-") {
		if args[i] == "-C" && i+1 < len(args) {
			base = joined(base, args[i+1])
		}
		i++
		if slices.Contains(gitValued, args[i-1]) {
			i++
		}
	}
	if i+2 > len(args) || args[i] != "worktree" || args[i+1] != "add" {
		return "", nil
	}
	rest, j := args[i+2:], 0
	for j < len(rest) && strings.HasPrefix(rest[j], "-") && rest[j] != "-" && rest[j] != "--" {
		word := rest[j]
		j++
		if word == "--reason" {
			j++
		} else if !strings.HasPrefix(word, "--") {
			if at := strings.IndexAny(word, "bB"); at >= 0 && at == len(word)-1 { // or it rides in this word
				j++
			}
		}
	}
	if j < len(rest) && rest[j] == "--" {
		j++
	}
	if j >= len(rest) || !config.UnderCode(joined(base, rest[j])) {
		return "", nil
	}
	return fmt.Sprintf("ak refused `git worktree add %s`: ~/code holds only the owner's checkouts. "+
		"Make a seat's checkout under ~/.agentkit/wt/ instead: `git worktree add ~/.agentkit/wt/<name> ...`.", rest[j]), nil
}

// joined is a path from base as the system walks it: never cleaned, as `..` after a link leads
// out of the link's target.
func joined(base, path string) string {
	if filepath.IsAbs(path) {
		return path
	}
	return base + string(filepath.Separator) + path
}

// the URI schemes a remote spec may carry
var transferSchemes = []string{"scp://", "sftp://", "rsync://", "ssh://"}

// argHost is the remote host an scp, rsync or sftp argument names, "" for none: a URI, an
// `[user@]host:path`, or for sftp, whose operand is itself a host, a bare `[user@]host`.
func argHost(arg, tool string) string {
	bare := func(spec string) string { return spec[strings.LastIndexByte(spec, '@')+1:] }
	for _, scheme := range transferSchemes {
		if rest, is := strings.CutPrefix(arg, scheme); is {
			authority, _, _ := strings.Cut(rest, "/")
			host, _, _ := strings.Cut(bare(authority), ":")
			return host
		}
	}
	if strings.Contains(arg, ":") && !strings.HasPrefix(arg, "/") && !strings.HasPrefix(arg, "./") && !strings.HasPrefix(arg, "../") {
		spec, _, _ := strings.Cut(arg, ":")
		return bare(spec)
	}
	if tool == "sftp" {
		return bare(arg)
	}
	return ""
}

// transferRefusal is why the seat may not run this scp, rsync or sftp: a file reaches the live host
// only through the repo.  scp and rsync write to an operand after the first, the first being a
// download's source, tested by position so a trailing option hides no write and no list of each
// tool's options is needed; sftp connects to its host operand and can put files.
func transferRefusal(args []string, real string) (string, error) {
	own, _, err := config.CurrentSession()
	alias := config.LiveHost()
	if err != nil || own == "" || alias == "" {
		return "", err
	}
	tool := filepath.Base(real)
	operands := slices.DeleteFunc(slices.Clone(args), func(arg string) bool { return strings.HasPrefix(arg, "-") })
	if tool != "sftp" && len(operands) > 0 {
		operands = operands[1:]
	}
	if !slices.ContainsFunc(operands, func(arg string) bool { return argHost(arg, tool) == alias }) {
		return "", nil
	}
	return fmt.Sprintf("ak refused `%s` to %s: a file reaches the live host only through the repo. "+
		"Commit the change and let it deploy; a seat writes nothing onto %s by hand.", tool, alias, alias), nil
}

// liveReach refuses nothing: a seat's ssh runs wherever it goes.  One naming the live host in any
// argument is written down as reaching it, the moment kept under the name its harness was launched
// with, as its hooks keep its turn (plan.ReachedLive).
func liveReach(args []string, _ string) (string, error) {
	alias, launched := config.LiveHost(), os.Getenv("AGENTKIT_SESSION")
	if alias == "" || !slices.ContainsFunc(args, func(arg string) bool { return argHost(arg, "sftp") == alias }) {
		return "", nil
	}
	record, err := config.SessionPath(launched)
	if err != nil {
		return "", err
	}
	path := filepath.Join(filepath.Dir(record), config.SeatFileNames(config.Fold(launched))["live"])
	tmp := path + "." + strconv.Itoa(os.Getpid())
	moment := strconv.FormatFloat(float64(time.Now().UnixNano())/1e9, 'f', -1, 64)
	return "", errors.Join(os.WriteFile(tmp, []byte(moment+"\n"), 0o666), os.Rename(tmp, path))
}
