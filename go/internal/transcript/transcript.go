// Package transcript reads a seat's conversation, the JSON lines file its harness keeps, through
// that harness's manifest: its `[transcript]` table names each entry Go needs by its shape, so no
// harness is named here, and another harness is one more table.  The file is read from its end,
// newest entry first, as hooks/orchestrator-stop.sh reads it, so a long conversation costs what
// its last turn costs.
package transcript

import (
	"bytes"
	"io"
	"iter"
	"os"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// An End is what a conversation's end says: what the model said last (`last_message`), whether a
// question card it asked since the owner's last prompt is unanswered (`questioned`), and when
// that prompt was written, in Unix seconds, 0 where none is dated (`notify.owner_said`).
type End struct {
	Said     string
	Asking   bool
	Prompted float64
}

// A kind is one entry the table names: an entry of its shape, or, with parts, each part of
// that shape among those at that path; its words, or its id, at those paths.
type kind struct {
	shape         map[string]any
	parts, id     string
	words, frames []string
}

// Read is the end of the conversation at path, a harness's that its manifest reads; nothing
// where it has no `[transcript]` table or the file cannot be opened.
func Read(harness, path string) (end End) {
	table, _ := config.Section(harness, "transcript")
	file, err := os.Open(path)
	if table == nil || err != nil {
		return end
	}
	defer file.Close()
	skip, _ := table["skip"].(map[string]any)
	stamp, _ := table["at"].(string)
	said, card, answer := named(table["said"]), named(table["card"]), named(table["answer"])
	var prompts []kind
	for _, each := range listed(table["prompt"]) {
		prompts = append(prompts, named(each))
	}
	answered, prompted := map[string]bool{}, false
	for entry := range newest(file) {
		if skip != nil && fits(skip, entry) {
			continue
		}
		for _, item := range said.items(entry) {
			if end.Said == "" {
				end.Said = words(item, said.words)
			}
		}
		// what was asked before the owner's prompt is answered or set aside
		if !prompted && !end.Asking {
			answers := answer.items(entry)
			for _, item := range answers {
				if id, ok := first(at(item, answer.id)).(string); ok {
					answered[id] = true
				}
			}
			if len(answers) == 0 && prompt(prompts, entry) {
				prompted, end.Prompted = true, moment(first(at(entry, stamp)))
			} else {
				for _, item := range card.items(entry) {
					id, _ := first(at(item, card.id)).(string)
					end.Asking = end.Asking || !answered[id]
				}
			}
		}
		if end.Said != "" && (prompted || end.Asking) {
			break
		}
	}
	return end
}

// named is the kind a table of the manifest's `[transcript]` names.
func named(value any) (found kind) {
	table, _ := value.(map[string]any)
	found.shape, _ = table["shape"].(map[string]any)
	found.parts, _ = table["parts"].(string)
	found.id, _ = table["id"].(string)
	for _, each := range listed(table["words"]) {
		text, _ := each.(string)
		found.words = append(found.words, text)
	}
	for _, each := range listed(table["frames"]) {
		text, _ := each.(string)
		found.frames = append(found.frames, text)
	}
	return found
}

func listed(value any) []any {
	items, _ := value.([]any)
	return items
}

// items is each of the entry the kind is: the entry where it has the kind's shape, or each of
// its parts that has it; none for a kind with no shape.
func (k kind) items(entry *run.Object) (found []*run.Object) {
	candidates := []any{entry}
	if k.parts != "" {
		candidates = at(entry, k.parts)
	}
	for _, each := range candidates {
		if item, ok := each.(*run.Object); ok && k.shape != nil && fits(k.shape, item) {
			found = append(found, item)
		}
	}
	return found
}

// prompt is whether the entry is the owner's prompt: of one of their shapes, with words that
// no frame of its own opens.
func prompt(kinds []kind, entry *run.Object) bool {
	for _, k := range kinds {
		for _, item := range k.items(entry) {
			said := words(item, k.words)
			if said != "" && !slices.ContainsFunc(k.frames, func(frame string) bool { return strings.HasPrefix(said, frame) }) {
				return true
			}
		}
	}
	return false
}

// fits is whether the object has the shape: each of its keys holds what the shape says there.
func fits(shape map[string]any, object *run.Object) bool {
	for key, want := range shape {
		if !holds(want, object, key) {
			return false
		}
	}
	return true
}

// holds is whether the object's key holds what want says: that string, an object of that shape
// for a table, what any one of a list's says, and for a bool whether Python reads it as that.
func holds(want any, object *run.Object, key string) bool {
	switch want := want.(type) {
	case string:
		text, ok := object.Get(key).(string)
		return ok && text == want
	case bool:
		return object.Truthy(key) == want
	case map[string]any:
		inner := object.Dict(key)
		return inner != nil && fits(want, inner)
	case []any:
		return slices.ContainsFunc(want, func(each any) bool { return holds(each, object, key) })
	}
	return false
}

// at is each value the path reaches from the object: keys a dot apart, `[]` after one each item
// of the list it holds.
func at(object *run.Object, path string) []any {
	found := []any{object}
	for _, step := range strings.Split(path, ".") {
		key, each := strings.CutSuffix(step, "[]")
		var next []any
		for _, value := range found {
			if inner, ok := value.(*run.Object); !ok {
				continue
			} else if !each {
				next = append(next, inner.Get(key))
			} else if items, ok := inner.Get(key).([]any); ok {
				next = append(next, items...)
			}
		}
		found = next
	}
	return found
}

func first(values []any) any {
	if len(values) == 0 {
		return nil
	}
	return values[0]
}

// words is the strings at the paths from the item, a line apart.
func words(item *run.Object, paths []string) string {
	var said []string
	for _, path := range paths {
		for _, value := range at(item, path) {
			if text, ok := value.(string); ok {
				said = append(said, text)
			}
		}
	}
	return strings.Join(said, "\n")
}

// moment is a time in Unix seconds, a number or an RFC 3339 time with its zone (harness.moment);
// 0 for anything else.
func moment(value any) float64 {
	if text, ok := value.(string); ok {
		stamp, err := time.Parse(time.RFC3339Nano, text)
		if err != nil {
			return 0
		}
		return float64(stamp.UnixNano()) / 1e9
	}
	seconds, _ := run.Num(value)
	return seconds
}

// newest is each JSON object the file holds a line, its last line first, read back in growing
// chunks as far as the caller goes: an entry stays found however much followed it, in at most
// one chunk of memory beside the line it is in.
func newest(file *os.File) iter.Seq[*run.Object] {
	return func(yield func(*run.Object) bool) {
		end, err := file.Seek(0, io.SeekEnd)
		chunk, rest := int64(1<<18), []byte(nil)
		for err == nil && end > 0 {
			start := max(0, end-chunk)
			data := make([]byte, end-start, end-start+int64(len(rest)))
			if _, err = file.ReadAt(data, start); err != nil {
				return
			}
			lines := bytes.Split(append(data, rest...), []byte("\n"))
			rest = nil
			if start > 0 { // the head of a line the next read ends
				rest, lines = bytes.Clone(lines[0]), lines[1:]
			}
			for at := len(lines) - 1; at >= 0; at-- {
				value, _ := run.Decode(lines[at])
				if entry, ok := value.(*run.Object); ok && !yield(entry) {
					return
				}
			}
			end, chunk = start, min(chunk*4, 1<<26)
		}
	}
}
