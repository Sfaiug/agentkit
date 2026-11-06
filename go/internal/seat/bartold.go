package seat

import (
	"crypto/sha256"
	"encoding/hex"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/tmux"
)

// What a bar shows is named on the bar, as statusbar.py names it: each write sets a digest of what
// it told, of the session's own options and of its right end, which the listing reads back, so a
// look that would tell a bar the same sets no option, and a session made again, holding neither,
// is told whole.  The digest is Python's own, so neither program tells again what the other did
// (barShows where their Unicode tables differ).
const (
	barTold    = "@ak_told"
	barToldEnd = "@ak_told_end"
)

// barEnd is the command list that tells that seat's right end (barOthers), none where its digest
// says the bar shows it already (statusbar._ends).
func barEnd(found []barRow, row barRow) []string {
	needing, folded, hit := barOthers(found, row.name)
	digest := barDigest(barTuple(needing, folded, hit))
	if digest == row.toldEnd {
		return nil
	}
	target := "=" + row.name + ":"
	return barList([][3]string{{target, barToldEnd, ""}, {target, barHit, ""}, {target, barNeed, needing},
		{target, barFold, folded}, {target, barHit, hit}, {target, barToldEnd, digest}})
}

// barOwn is the command lists that tell each listed session its own of those options, none for one
// whose digest says it shows them already (statusbar._own), or that shows them under another's.
// The digest is emptied first and set last: tmux stops a list at the command that fails, and one
// stopped part way leaves no digest a later write could match.
func barOwn(own [][3]string, listed []barRow) (lists [][]string) {
	for _, row := range listed {
		target := "=" + row.name + ":"
		var options [][3]string
		var tuples []string
		for _, option := range own {
			if option[0] == target {
				options, tuples = append(options, option), append(tuples, barTuple(option[:]...))
			}
		}
		digest := barDigest("[" + strings.Join(tuples, ", ") + "]")
		if len(options) > 0 && digest != row.told && (row.told == "" || !barShows(target, row.told, options)) {
			lists = append(lists, barList(slices.Concat([][3]string{{target, barTold, ""}}, options, [][3]string{{target, barTold, digest}})))
		}
	}
	return lists
}

// barShows is whether that bar holds those options' texts already, read back, under a digest not
// Go's: Python's repr, which names a character its own Unicode tables do not know otherwise, gives
// the same texts another one.  The digest around them keeps tmux's trimmed answer whole.
func barShows(target, told string, options [][3]string) bool {
	asked, want := []string{"-u"}, told
	for _, option := range slices.Concat([][3]string{{target, barTold, ""}}, options, [][3]string{{target, barTold, ""}}) {
		asked = append(asked, "show-options", "-qv", "-t", target, option[1], ";")
	}
	for _, option := range options {
		want += "\n" + option[2]
	}
	shown, err := tmux.Ask(tmux.Own(), asked[:len(asked)-1]...)
	return err == nil && shown == want+"\n"+told
}

// barList is those options set as one command list, which tmux runs whole.
func barList(options [][3]string) []string {
	var list []string
	for _, option := range options {
		list = append(append(list, barSet(option)...), ";")
	}
	return list[:len(list)-1]
}

// barTuple is Python's repr of a tuple of texts.
func barTuple(texts ...string) string {
	quoted := make([]string, len(texts))
	for i, text := range texts {
		quoted[i] = commandhelp.Quote(text)
	}
	return "(" + strings.Join(quoted, ", ") + ")"
}

// barDigest is statusbar._digest of what a Python repr says.
func barDigest(repr string) string {
	sum := sha256.Sum256([]byte(repr))
	return hex.EncodeToString(sum[:])[:16]
}
