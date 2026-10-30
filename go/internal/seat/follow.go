package seat

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"unicode/utf16"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// projectCut is where Claude Code ends a project folder's name with a hash of the path.
const projectCut = 200

// audit is the weekly audit's seat (audit.NAME), whose models run at their entries' efforts.
const audit = "audit"

// A move is what a Claude seat's last answer moves in its record (watch.follow_model): the
// configured model the answer ran on, the seat's own first, and that model's orchestrator effort
// where the answer ran at another it takes; "" for none.
type move struct{ chosen, effort string }

// follows is the move of a record's last answer: `/model` or `/effort` typed in the seat moves
// it as a move on `c` would. False where Python's answer hangs on a configured model or a
// manifest this reading cannot read.
func follows(record *run.Object, models map[string]config.Model, offered []string) (move, bool) {
	kept := record.Str("orchestrator")
	own := models[kept]
	model, effort, answered := lastAnswer(record)
	if own.ID == "" || own.ID == "default" || !answered {
		return move{}, true
	}
	var runs []string
	for _, each := range append([]string{kept}, offered...) {
		entry, resolved := models[each]
		if !resolved {
			return move{}, false
		}
		if entry.Harness == own.Harness && model == any(entry.ID) {
			runs = append(runs, each)
		}
	}
	if len(runs) == 0 {
		return move{}, true
	}
	chosen := runs[0]
	if at := slices.IndexFunc(runs, func(each string) bool { return effort == any(models[each].Efforts["effort"]) }); at >= 0 {
		chosen = runs[at]
	}
	if effort == any(models[chosen].Efforts["effort"]) {
		return move{chosen, ""}, true
	}
	takes, err := config.Efforts(own.Harness, model.(string))
	if err != nil {
		return move{}, false
	}
	if word, named := effort.(string); named && slices.Contains(takes, word) {
		return move{chosen, word}, true
	}
	return move{chosen, ""}, true
}

// lastAnswer is the model and effort of the last answer a Claude seat's conversation records
// (claude.py `running`), read back from its end: its own, never a subagent's or one Claude Code
// made up itself. Read anywhere else Claude Code would keep it, or not read, there is none.
func lastAnswer(record *run.Object) (model, effort any, found bool) {
	conversation, cwd := record.Str("conversation"), record.Str("cwd")
	if conversation == "" || cwd == "" {
		return nil, nil, false
	}
	home, _ := os.UserHomeDir()
	file, err := os.Open(filepath.Join(home, ".claude", "projects", projectFolder(cwd), conversation+".jsonl"))
	if err != nil {
		return nil, nil, false
	}
	defer file.Close()
	end, err := file.Seek(0, io.SeekEnd)
	var rest []byte
	for err == nil && end > 0 {
		start := max(0, end-65536)
		chunk := make([]byte, end-start, end-start+int64(len(rest)))
		if _, err = file.ReadAt(chunk, start); err != nil {
			break
		}
		lines := bytes.Split(append(chunk, rest...), []byte("\n"))
		rest = nil
		if start > 0 { // the head of a line the next read ends
			rest, lines = lines[0], lines[1:]
		}
		for at := len(lines) - 1; at >= 0; at-- {
			value, _ := run.Decode(lines[at])
			entry, _ := value.(*run.Object)
			if entry == nil || entry.Str("type") != "assistant" || entry.Truthy("isSidechain") || entry.Dict("message") == nil {
				continue
			}
			if model = entry.Dict("message").Get("model"); model != nil && model != "<synthetic>" {
				return model, entry.Get("effort"), true
			}
		}
		end = start
	}
	return nil, nil, false
}

// moved writes into the record what its last answer moved: its orchestrator, through
// config.update_session, which gives each model the seat then runs its entry's efforts, then
// that model's orchestrator effort, through config.change_efforts.
func (seat Seat) moved(state string, models map[string]config.Model) error {
	path, held := filepath.Join(state, "session-"+seat.Name+".json"), filepath.Join(state, ".session-"+seat.Name+".lock")
	to := seat.follow
	if to.chosen != "" && to.chosen != seat.Orchestrator {
		orchestrate := set([]field{{"orchestrator", to.chosen}})
		if err := put(path, held, run.Encode, func(data *run.Object) bool {
			if !orchestrate(data) {
				return false
			}
			ownEfforts(data, seat.Name, models)
			return true
		}); err != nil {
			return err
		}
	}
	if to.effort == "" {
		return nil
	}
	return put(path, held, run.Encode, func(data *run.Object) bool {
		efforts := orchestratingAt(data, to.chosen, to.effort, models)
		if run.Equal(efforts, data.Get("efforts")) {
			return false
		}
		data.Set("efforts", efforts)
		return true
	})
}

// ownEfforts is config.own_efforts: each model the record runs that it holds no efforts for
// takes its entry's, once, so an entry changed since moves no seat; the audit seat's go on with
// the entries'.
func ownEfforts(data *run.Object, name string, models map[string]config.Model) {
	held := data.Dict("efforts")
	if held == nil {
		held = run.NewObject()
	}
	efforts := held.Copy()
	runs := append(append([]any{data.Get("orchestrator")}, data.List("workers")...), data.List("reviewers")...)
	for _, each := range runs {
		model, named := each.(string)
		if entry, known := models[model]; named && known && !held.Has(model) {
			efforts.Set(model, entryEfforts(entry))
		}
	}
	if name != audit && len(efforts.Keys()) > len(held.Keys()) {
		data.Set("efforts", efforts)
	}
}

// orchestratingAt is config.orchestrating_at: the record's efforts with that model's orchestrator
// effort at `word`, every key it holds kept, one that followed it set where it stood, and a
// model it holds none for starting from its entry's.
func orchestratingAt(data *run.Object, model, word string, models map[string]config.Model) *run.Object {
	efforts := run.NewObject()
	if held := data.Dict("efforts"); held != nil {
		efforts = held.Copy()
	}
	own := efforts.Dict(model)
	if !efforts.Truthy(model) || own == nil {
		own = entryEfforts(models[model])
	}
	next := run.NewObject()
	for _, key := range config.RoleEfforts {
		next.Set(key, own.Get("effort"))
	}
	for _, key := range own.Keys() {
		next.Set(key, own.Get(key))
	}
	next.Set("effort", word)
	efforts.Set(model, next)
	return efforts
}

// entryEfforts is config.efforts_of: the efforts an entry sets, by their keys.
func entryEfforts(entry config.Model) *run.Object {
	efforts := run.NewObject()
	for _, key := range config.RoleEfforts {
		if word, set := entry.Efforts[key]; set {
			efforts.Set(key, word)
		}
	}
	return efforts
}

// projectFolder is the folder Claude Code files a working directory's conversations under
// (claude.py `project`): each UTF-16 unit not an ASCII letter or digit a hyphen, and a long
// name its start and the magnitude of the path's 31-times hash as a signed 32-bit number.
func projectFolder(cwd string) string {
	var name strings.Builder
	for _, char := range cwd {
		switch {
		case char < 0x80 && (char >= '0' && char <= '9' || char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z'):
			name.WriteRune(char)
		case char > 0xFFFF:
			name.WriteString("--")
		default:
			name.WriteByte('-')
		}
	}
	if name.Len() <= projectCut {
		return name.String()
	}
	var hash uint32
	for _, unit := range utf16.Encode([]rune(cwd)) {
		hash = hash*31 + uint32(unit)
	}
	magnitude := int64(int32(hash))
	if magnitude < 0 {
		magnitude = -magnitude
	}
	return name.String()[:projectCut] + "-" + strconv.FormatInt(magnitude, 36)
}
