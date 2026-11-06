// Package boards is the public boards ak rates models on (quality), each asked at most once a day
// and kept in state/boards.json, Python's file and format: a board's rows, when it was asked,
// when it last answered and the error it last gave.  A board that cannot answer keeps what it
// last said and waits for the day like one that answered.  A board another build of ak read is
// asked again, once, by a build reading a column its rows carry none of: its reader changed, and
// a day of nothing is stale state.  Callers at once share one collection: each writer holds
// boards.lock from reading the file to replacing it.
package boards

import (
	"context"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// freshFor is the seconds a board is not asked again: none moves faster than a day.
const freshFor = 86400

const (
	artificialAnalysisBoard = "artificialanalysis.ai"
	arenaBoard              = "arena.ai"
)

// names are the boards in the order they are asked and held.
var names = []string{artificialAnalysisBoard, arenaBoard}

// prefix is what each board's columns start with.
var prefix = map[string]string{artificialAnalysisBoard: "aa", arenaBoard: "arena"}

// carries is what a board's rows hold beside what quality reads, a table counted where any of its
// fields is: Artificial Analysis's record's identity and its evaluations, and Arena's agent board
// with its interval.
var carries = map[string][]string{
	artificialAnalysisBoard: {"slug", "release", "maker", "deprecated", "aa.intelligenceIndexEvaluations"},
	arenaBoard:              {"arena.agent.lower95ci"},
}

var asks = map[string]func() ([]any, error){artificialAnalysisBoard: artificialAnalysis, arenaBoard: arena}

func path() string {
	return filepath.Join(config.Home(), "state", "boards.json")
}

// Cached is boards.json as it is, or while there is none yet the boards as state/matrix.json held
// them beside the matrix until 20 Oct 2026, so an install upgraded keeps its day's pace; empty
// where the file is unreadable.
func Cached() *run.Object {
	file := path()
	if _, err := os.Stat(file); err != nil {
		file = filepath.Join(config.Home(), "state", "matrix.json")
	}
	cache := run.NewObject()
	data, err := os.ReadFile(file)
	if err != nil {
		return cache
	}
	value, err := run.Decode(data)
	if err != nil {
		return cache
	}
	if held, ok := value.(*run.Object); ok {
		for _, board := range names {
			if held.Has(board) {
				cache.Set(board, held.Get(board))
			}
		}
	}
	return cache
}

// Collect is the boards' rows, each board asked once a day (refresh asks now), as the cache holds
// them: {board: {"asked_at", "fetched_at", "rows", "error", "build"}}.  The day counts from
// asked_at, answered or not; build is ak's build asking.  keep is asked of the boards as asked
// before the cache is written: its error writes nothing and is returned.
func Collect(refresh bool, now float64, build string, keep func(*run.Object) error) (*run.Object, error) {
	if err := os.MkdirAll(filepath.Dir(path()), 0o777); err != nil {
		return nil, err
	}
	held, err := lock.Wait(context.Background(), strings.TrimSuffix(path(), ".json")+".lock")
	if err != nil {
		return nil, err
	}
	defer held.Close()
	cache := Cached()
	for _, board := range names {
		last, _ := cache.Get(board).(*run.Object)
		if !refresh && fresh(board, last, now, build) {
			continue
		}
		answer := run.NewObject()
		rows, err := asks[board]()
		if err == nil {
			answer.Set("asked_at", now)
			answer.Set("fetched_at", now)
			answer.Set("rows", rows)
			answer.Set("error", nil)
			answer.Set("build", build)
		} else { // a board down is a note, not a crash
			if last != nil {
				answer = last.Copy()
			}
			answer.Set("asked_at", now)
			answer.Set("build", build)
			answer.Set("error", strings.Join(strings.FieldsFunc(err.Error(), config.Space), " "))
		}
		cache.Set(board, answer)
	}
	if err := keep(cache); err != nil {
		return nil, err
	}
	return cache, WriteJSON(path(), cache)
}

// fresh is whether a board's last answer stands: asked within the day, and by this build or one
// whose rows carry all this build reads.
func fresh(board string, last *run.Object, now float64, build string) bool {
	if last == nil || !last.Truthy("asked_at") {
		return false
	}
	asked, ok := last.Num("asked_at")
	if !ok || now-asked >= freshFor {
		return false
	}
	if held, ok := last.Get("build").(string); ok && held == build {
		return true
	}
	carried := map[string]bool{}
	for _, value := range last.List("rows") {
		row, _ := value.(*run.Object)
		if row == nil {
			continue
		}
		columns := row.Keys()
		if values := row.Dict("values"); values != nil {
			columns = append(columns, values.Keys()...)
		}
		for _, column := range columns {
			parts := strings.Split(column, ".")
			for n := 1; n <= len(parts); n++ {
				carried[strings.Join(parts[:n], ".")] = true
			}
		}
	}
	wanted := slices.Clone(carries[board])
	for _, column := range quality.Needed() {
		if strings.Split(column, ".")[0] == prefix[board] {
			wanted = append(wanted, column)
		}
	}
	return !slices.ContainsFunc(wanted, func(column string) bool { return !carried[column] })
}

// WriteJSON replaces a state file whole, as Python's json.dumps writes it, through its `.tmp`: a
// reader never sees half of it.  The caller holds its lock, so two writers never share the `.tmp`.
func WriteJSON(file string, value any) error {
	tmp := strings.TrimSuffix(file, ".json") + ".tmp"
	if err := os.WriteFile(tmp, []byte(run.Line(value)), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, file)
}
