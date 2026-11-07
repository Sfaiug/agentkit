package gc

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"unicode/utf8"

	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// How the collector takes what nothing outside runs and jobs comes back for.

// takeEphemeral takes an artifact under its writer's lease while its receipt and tree are as
// planned, its writer gone and nobody in it (retention.remove_ephemeral).
func takeEphemeral(path, receipt string, smoke bool, snapshot []entry) func(*collection) (bool, error) {
	identity, _ := fingerprint(receipt)
	return func(*collection) (bool, error) {
		paths := processPaths()
		lease, err := reading(receipt, false)
		if err != nil {
			return false, err
		}
		defer lease.Close()
		if !unlocked(lease) {
			return false, errors.New("its writer holds the lease")
		}
		var live []string
		if smoke {
			live = unixSockets()
		}
		again, whole := tree(path, live, nil)
		if now, _ := fingerprint(receipt); now != identity || !whole || !slices.Equal(again, snapshot) ||
			writerActive(orEmpty((&reads{}).json(receipt))) || busy(path, paths) {
			return false, nil
		}
		if isDir(path) {
			return true, os.RemoveAll(path)
		}
		return true, errors.Join(os.Remove(path), os.Remove(receipt))
	}
}

// takeSeatFile takes a gone seat's file while its seat is still gone and the file a day old.
func takeSeatFile(path string) func(*collection) (bool, error) {
	return func(*collection) (bool, error) {
		if _, gone := (&reads{now: epoch()}).seatGone(path); !gone {
			return false, nil
		}
		return true, os.Remove(path)
	}
}

// takeTmp takes a top-level temporary entry while still untouched and held by nobody, by one
// reading of what every process holds for the pass.
func takeTmp(path string) func(*collection) (bool, error) {
	return func(c *collection) (bool, error) {
		name := filepath.Base(path)
		if protected(name) || harness.OwnsTmp(name) || (&reads{now: epoch()}).untouched(path, c.every(), tmpAge) == "" {
			return false, nil
		}
		return removeEntry(path)
	}
}

// takeHomeEntry takes an entry of ak's home while still untouched for its age, held by nobody
// and no task file a job names.
func takeHomeEntry(path string, age float64) func(*collection) (bool, error) {
	return func(c *collection) (bool, error) {
		paths := c.every()
		if paths == nil {
			return false, nil
		}
		r := &reads{now: epoch()}
		if r.untouched(path, append(slices.Clone(paths), r.taskFiles()...), age) == "" {
			return false, nil
		}
		return removeEntry(path)
	}
}

// removeEntry takes an entry no link reaches: a folder whole, a file alone.
func removeEntry(path string) (bool, error) {
	if isLink(path) {
		return false, nil
	}
	var err error
	if isDir(path) {
		err = os.RemoveAll(path)
	} else {
		err = os.Remove(path)
	}
	return !present(path), err
}

// takeConversation ends a conversation its harness's own way, nil where that way is Python's.
func takeConversation(name, path, conversation string) func(*collection) (bool, error) {
	if _, ours, err := harness.ConversationParts(name, path); !ours || err != nil {
		return nil
	}
	return balking(name, func() (bool, error) { return endConversation(name, path, conversation) })
}

// takeIdle ends a conversation kept as rows of its harness's database its harness's own way, only
// while that database is ours, reached through no link, names it idle still and no seat holds it,
// the seats read again now (gc.cmd_gc).
func takeIdle(idle harness.Idle) func(*collection) (bool, error) {
	return balking(idle.Harness, func() (bool, error) {
		return harness.EndIdle(idle, func(database string) bool {
			now, known := harness.IdleConversations(epoch() - runAge)
			return safe(database) && known && slices.Contains(now, idle) && (&reads{}).free(idle.Harness, idle.ID)
		})
	})
}

// balking is that end of a conversation of that harness, skipped once its harness's own way
// failed this pass.
func balking(name string, end func() (bool, error)) func(*collection) (bool, error) {
	return func(c *collection) (bool, error) {
		if c.balked[name] {
			return false, nil
		}
		done, err := end()
		if err != nil {
			c.balked[name] = true // one failure a pass, not one a conversation
		}
		return done, err
	}
}

// endConversation takes what the harness keeps of a conversation, then the conversation, only
// while it is still stale, no seat holds it, the seats read again now, and each part is ours,
// reached through no link and held by nobody (harness.end_conversation, gc.conversation_ends).
func endConversation(name, path, conversation string) (bool, error) {
	parts, ours, err := harness.ConversationParts(name, path)
	if !ours || err != nil {
		return false, err
	}
	r := &reads{now: epoch()}
	paths := r.every()
	if r.conversationStale(path, paths) == "" || !r.free(name, conversation) || slices.ContainsFunc(parts, func(part string) bool {
		return !safe(part) || busy(part, paths)
	}) {
		return false, nil
	}
	for _, part := range parts {
		if _, err := removeEntry(part); err != nil {
			return false, err
		}
	}
	err = os.Remove(path)
	return !present(path), err
}

// takeHarness rewrites a harness's JSON file without the entries naming a gone sandbox or
// checkout: atomically, with its own mode, and never over a write the harness made since it was
// read (retention.prune_harness).  A TOML file's is Python's.
func takeHarness(file, trust, mcp string) func(*collection) (bool, error) {
	if filepath.Ext(file) != ".json" {
		return nil
	}
	return func(*collection) (bool, error) {
		identity, text, ok := harnessPruned(file, trust, mcp)
		if !ok {
			return false, nil
		}
		part := filepath.Join(filepath.Dir(file), "."+filepath.Base(file)+".agentkit-gc")
		if err := os.Remove(part); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return false, err
		}
		output, err := os.OpenFile(part, os.O_WRONLY|os.O_CREATE|os.O_EXCL, fs.FileMode(identity.mode&0o777))
		if err != nil {
			return false, err
		}
		_, err = output.WriteString(text)
		if err = errors.Join(err, output.Sync(), output.Close()); err == nil {
			if now, _ := fingerprint(file); now != identity {
				return false, os.Remove(part)
			}
			err = os.Rename(part, file)
		}
		if err != nil {
			os.Remove(part)
		}
		return err == nil, err
	}
}

// harnessPruned is that harness file's text less every entry naming a gone sandbox or checkout,
// and what the file was when read; false where there is none, or the file is a link, not ours,
// or does not read as the document less those entries (retention.harness_pruned).
func harnessPruned(file, trust, mcp string) (stat, string, bool) {
	if !safe(file) || !isFile(file) {
		return stat{}, "", false
	}
	identity, ok := fingerprint(file)
	data, err := readBytes(file)
	if !ok || err != nil || !utf8.Valid(data) {
		return stat{}, "", false
	}
	text, pruned := jsonPruned(string(data), trust, mcp)
	return identity, text, pruned
}

// jsonPruned is the JSON text less its stale trust entries and MCP servers, cut from the text
// itself, commas and all, so every other byte stays as the harness wrote it; false where there
// are none, or the result does not decode to exactly the old document less them
// (retention.json_pruned).
func jsonPruned(raw, trust, mcp string) (string, bool) {
	value, err := run.DecodeLimited([]byte(raw))
	data, ok := value.(*run.Object)
	if err != nil || !ok {
		return "", false
	}
	top, _, err := jsonMembers(raw, jsonSpace(raw, 0))
	if err != nil {
		return "", false
	}
	var spans [][2]int
	taken := 0
	for _, section := range []string{trust, mcp} {
		entries, _ := data.Get(section).(*run.Object)
		stale := map[string]bool{}
		if entries != nil {
			for _, key := range entries.Keys() {
				if section == trust && gonePath(key) || section == mcp && slices.ContainsFunc(texts(entries.Get(key)), gonePath) {
					stale[key] = true
				}
			}
		}
		for _, each := range top {
			if each.key == section && raw[each.value] == '{' {
				members, closing, err := jsonMembers(raw, each.value)
				if err != nil {
					return "", false
				}
				doomed := map[int]bool{}
				for n, member := range members {
					if stale[member.key] {
						doomed[n] = true
					}
				}
				spans = append(spans, cut(members, doomed, each.value, closing)...)
			}
		}
		for key := range stale {
			entries.Delete(key)
		}
		taken += len(stale)
	}
	text := splice(raw, spans)
	again, err := run.DecodeLimited([]byte(text))
	return text, taken > 0 && err == nil && run.Equal(again, data)
}

// member is one member of a JSON object's text: from its key's quote to its value's end, and
// where its value starts.
type member struct {
	key               string
	start, end, value int
}

// jsonMembers is each member of the object whose `{` is at raw[i], and where its `}` is.
func jsonMembers(raw string, i int) ([]member, int, error) {
	var found []member
	for i = jsonSpace(raw, i+1); i < len(raw) && raw[i] != '}'; {
		var key string
		colon, err := jsonValue(raw, i, &key)
		if err != nil {
			return nil, 0, err
		}
		value := jsonSpace(raw, jsonSpace(raw, colon)+1)
		var skipped json.RawMessage
		end, err := jsonValue(raw, value, &skipped)
		if err != nil {
			return nil, 0, err
		}
		found = append(found, member{key, i, end, value})
		if i = jsonSpace(raw, end); i < len(raw) && raw[i] == ',' {
			i = jsonSpace(raw, i+1)
		}
	}
	if i >= len(raw) {
		return nil, 0, errors.New("no object end")
	}
	return found, i, nil
}

// jsonValue decodes the JSON value at raw[at] into into: where it ends.
func jsonValue(raw string, at int, into any) (int, error) {
	if at >= len(raw) {
		return 0, errors.New("no value")
	}
	decoder := json.NewDecoder(strings.NewReader(raw[at:]))
	if err := decoder.Decode(into); err != nil {
		return 0, err
	}
	return at + int(decoder.InputOffset()), nil
}

func jsonSpace(raw string, i int) int {
	for i < len(raw) && strings.IndexByte(" \t\n\r", raw[i]) >= 0 {
		i++
	}
	return i
}

// cut is the spans that take the doomed members out of the object between opening and closing,
// commas and all: a member with what follows it up to the next, the last with what precedes it
// from the one kept before.  Taking every member leaves `{}` (retention.cut).
func cut(members []member, doomed map[int]bool, opening, closing int) [][2]int {
	if len(doomed) == 0 {
		return nil
	}
	if len(doomed) == len(members) {
		return [][2]int{{opening + 1, closing}}
	}
	var spans [][2]int
	for n, each := range members {
		switch {
		case !doomed[n]:
		case n+1 < len(members):
			spans = append(spans, [2]int{each.start, members[n+1].start})
		default:
			kept := n - 1
			for doomed[kept] {
				kept--
			}
			spans = append(spans, [2]int{members[kept].end, each.end})
		}
	}
	return spans
}

// splice is raw less those spans, overlapping ones taken once.
func splice(raw string, spans [][2]int) string {
	sort.Slice(spans, func(a, b int) bool {
		return spans[a][0] < spans[b][0] || spans[a][0] == spans[b][0] && spans[a][1] < spans[b][1]
	})
	var kept strings.Builder
	at := 0
	for _, span := range spans {
		kept.WriteString(raw[at:max(at, span[0])])
		at = max(at, span[1])
	}
	return kept.String() + raw[at:]
}
