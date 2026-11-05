package seat

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// ownerTag is what a seat's own tmux tags each session it starts with, in that session's
// environment: the seat's name (guard.TMUX_OWNER).
const ownerTag = "AK_TMUX_OWNER"

var (
	sessionID = regexp.MustCompile(`^\$[0-9]+$`)
	digits    = regexp.MustCompile(`^[0-9]+$`)
)

// closeSideSessions is Python's orch.sweep_finished: a session a seat started for a build, a server
// or a long test, which nothing else ever ends, has each pane's screen saved to ~/.agentkit/tmp and
// is closed once every pane has been dead a day, or at once, panes running, once ak holds nothing
// of that seat (forgotten).  A session ak opened, one a record names, Control and one no seat
// tagged stay, and a listing that is not whole proves no pane dead.  Run on a home Looking reads,
// where every session tmux holds that is a seat has a record.
func closeSideSessions(now time.Time, log func(string)) {
	out, err := tmux.Ask(tmux.Own(), "list-panes", "-a", "-F",
		"#{session_id}\t#{session_name}\t#{"+tmux.Mark+"}\t#{pane_id}\t#{pane_dead}\t#{pane_dead_time}\t.")
	if err != nil {
		return
	}
	var order []string
	grouped := map[string][][]string{} // each session's panes: its name, mark, the pane's id, dead and death
	for _, line := range strings.Split(out, "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) != 7 || !sessionID.MatchString(parts[0]) {
			return
		}
		if grouped[parts[0]] == nil {
			order = append(order, parts[0])
		}
		grouped[parts[0]] = append(grouped[parts[0]], parts[1:6])
	}
	cutoff := seconds(now) - 86400
	for _, sid := range order {
		panes := grouped[sid]
		name := panes[0][0]
		if panes[0][1] == "1" || name == config.Control || named(name) ||
			slices.ContainsFunc(panes, func(pane []string) bool { return !paneID.MatchString(pane[2]) }) {
			continue
		}
		finished := !slices.ContainsFunc(panes, func(pane []string) bool {
			died, _ := strconv.ParseFloat(pane[4], 64)
			return pane[3] != "1" || !digits.MatchString(pane[4]) || died <= 0 || died > cutoff
		})
		// the session's own environment: a format falls back to the server's, which holds the
		// tag whenever a process in a tagged pane started this server
		tag, err := tmux.Ask(tmux.Own(), "show-environment", "-t", sid, ownerTag)
		owner, tagged := strings.CutPrefix(tag, ownerTag+"=")
		if err != nil || !tagged || owner == "" || !finished && !forgotten(owner) {
			continue
		}
		path, err := saveScreens(name, owner, panes)
		if err != nil {
			log("WARN could not save the side session " + name + ": " + config.PyError(err))
			continue
		}
		// tmux rechecks every window and pane in the command that kills it: a pane respawned,
		// added or moved during the capture survives, as does a session renamed into a seat or
		// whose tag was cleared or changed, for which show-environment fails and ends the list
		snapshot := owner + "/" + name + "/"
		for _, pane := range panes {
			snapshot += strings.Join(pane[2:], "/") + ";"
		}
		snapshot = strings.NewReplacer("#", "##", ",", "#,", "}", "#}").Replace(snapshot)
		condition := "#{&&:#{!=:#{" + tmux.Mark + "},1},#{==:#{" + ownerTag + "}/#{session_name}/" +
			"#{W:#{P:#{pane_id}/#{pane_dead}/#{pane_dead_time};}}," + snapshot + "}}"
		// a seat opened under the owner's name meanwhile takes its sessions back
		if named(name) || !finished && !forgotten(owner) {
			continue
		}
		tmux.Ask(tmux.Own(), "show-environment", "-t", sid, ownerTag, ";", "if-shell", "-F", "-t", sid, condition, "kill-session -t '"+sid+"'")
		if tmux.Absent(tmux.Own(), sid) { // tmux reads `$1` as session $1, renamed or not
			log("closed " + name + ", a side session " + owner + " started; its screens are in " + path)
		}
	}
}

// named is whether a record or a rename's pointer holds that name.
func named(name string) bool {
	_, err := os.Lstat(filepath.Join(config.Home(), "state", "session-"+name+".json"))
	return err == nil
}

// forgotten is whether ak holds nothing of the seat a side session's tag names (orch.forgotten): no
// record or rename's pointer and no session in tmux, under the tag or where its renames lead.
// Asked afresh each time, as a seat may open under the name meanwhile; a rename chain it cannot
// follow or a failed tmux probe is no proof the seat is gone.
func forgotten(tag string) bool {
	current, _, err := config.ResolveSession(tag)
	if err != nil {
		return false
	}
	names := []string{tag, current}
	listed, said := tmux.Names(tmux.Own())
	return said && !slices.ContainsFunc(names, func(name string) bool { return named(name) || slices.Contains(listed, name) })
}

// saveScreens writes the side session's panes' screens to a new file of ~/.agentkit/tmp, never
// one there already or through a link, and names it.
func saveScreens(name, owner string, panes [][]string) (string, error) {
	if err := config.EnsureDirs(); err != nil {
		return "", err
	}
	dir := filepath.Join(config.Home(), "tmp")
	if info, err := os.Lstat(dir); err != nil || !info.IsDir() {
		return "", fmt.Errorf("%s is no folder", dir)
	}
	token := make([]byte, 16)
	rand.Read(token)
	path := filepath.Join(dir, "tmux-"+hex.EncodeToString(token)+".txt")
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return "", err
	}
	defer file.Close()
	text := name + " (started by " + owner + ")\n"
	for _, pane := range panes {
		shown, err := tmux.AskWithin(5*time.Second, tmux.Own(), "capture-pane", "-p", "-t", pane[2])
		if err != nil {
			return "", fmt.Errorf("could not capture %s", pane[2])
		}
		text += pane[2] + "\n" + shown + "\n"
	}
	_, err = file.WriteString(text)
	return path, err
}
