// Package matrix is every current model on the boards, a row per release and effort with the
// installed harnesses' models that are it (lineup), computed from the boards and the config and
// kept in state/matrix.json, Python's file and format, so a program that picks reads one computed
// truth.  Attribution: Source: Artificial Analysis (artificialanalysis.ai); arena.ai.
package matrix

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/boards"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/listing"
	"agentkit/internal/lock"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/update"
)

func path() string {
	return filepath.Join(config.Home(), "state", "matrix.json")
}

// stored is the matrix as last computed, empty where it is not or unreadable.
func stored() *run.Object {
	data, err := os.ReadFile(path())
	if err != nil {
		return run.NewObject()
	}
	value, err := run.Decode(data)
	if err != nil {
		return run.NewObject()
	}
	if held, ok := value.(*run.Object); ok && held.Dict("matrix") != nil {
		return held.Dict("matrix")
	}
	return run.NewObject()
}

// present is every harness present to run a turn, sorted: its adapter here and its program found.
// A home naming no adapter directory has the shipped ones.
func present() ([]any, error) {
	names, err := config.HarnessNames()
	if err != nil {
		return nil, err
	}
	found := []any{}
	for _, name := range names {
		if _, err := config.Adapter(name); err != nil && !errors.Is(err, config.ErrNoAdapterDir) {
			continue
		}
		program := name
		if version, err := config.Words(name, "update", "version"); err == nil && len(version) > 0 && version[0] != "" {
			program = version[0]
		}
		if harness.Binary(program) != "" {
			found = append(found, name)
		}
	}
	return found, nil
}

// configKey is what of the config the matrix is computed from: a change here recomputes it.
func configKey() ([]any, error) {
	rows, err := config.ModelsKey()
	if err != nil {
		return nil, err
	}
	key := []any{}
	for _, row := range rows {
		var fields []any
		for _, field := range row {
			fields = append(fields, field)
		}
		key = append(key, fields)
	}
	return key, nil
}

var bracketed = regexp.MustCompile(`\([^()]*\)`)

// normal is a model's name as every board and config spells it alike: its letters and digits.
func normal(text string) string {
	text = text[strings.LastIndexByte(text, '/')+1:]
	return strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, strings.ToLower(text))
}

// A hit is one name a release goes by on a board.
type hit struct {
	model   string
	release *boards.Release
}

func allDigits(text string) bool {
	return text != "" && strings.Trim(text, "0123456789") == ""
}

// found is a board's hits for one model: under its exact name, else under a board's name naming no
// version of its own that model extends with one (`Acme Pro` for `acme-pro-1.0`, never `Acme 5`
// for `acme-5-5`), else under the one board name that is model with a qualifier in brackets
// (`Acme 5 (Default Fallback)`; two such names stand for nothing), else under each board name that
// adds a version or date to a model naming none (`Acme Flash 1017` for `acme-flash`, lineup taking
// only one release), else the same matches without a trailing `-free` pricing tier.
func found(index map[string][]hit, model string) []hit {
	wanted := normal(model)
	if hits, ok := index[wanted]; ok {
		return hits
	}
	longest, stemmed := "", false
	for stem := range index {
		if stem != "" && !allDigits(stem[len(stem)-1:]) && strings.HasPrefix(wanted, stem) && allDigits(wanted[len(stem):]) &&
			(!stemmed || len(stem) > len(longest)) {
			longest, stemmed = stem, true
		}
	}
	if stemmed {
		return index[longest]
	}
	var qualified []string
	for stem, hits := range index {
		if normal(bracketed.ReplaceAllString(hits[0].model, "")) == wanted {
			qualified = append(qualified, stem)
		}
	}
	if len(qualified) == 1 {
		return index[qualified[0]]
	}
	var extended []hit
	if wanted == "" || !allDigits(wanted[len(wanted)-1:]) {
		for stem, hits := range index {
			if strings.HasPrefix(stem, wanted) && allDigits(stem[len(wanted):]) {
				extended = append(extended, hits...)
			}
		}
	}
	if len(extended) > 0 {
		return extended
	}
	if bare, free := strings.CutSuffix(model, "-free"); free {
		// Free is a pricing tier, so use the underlying model's board rows.
		return found(index, bare)
	}
	return nil
}

// indexOf is the hits found reads, each release under every name it goes by.
func indexOf(releases []*boards.Release) map[string][]hit {
	index := map[string][]hit{}
	for _, release := range releases {
		// the name first: found reads the first hit's for a bracketed qualifier; either may lack
		name, _ := release.Name.(string)
		for _, each := range []string{name, release.Slug} {
			if each != "" {
				index[normal(each)] = append(index[normal(each)], hit{each, release})
			}
		}
	}
	return index
}

// lineup is a row per current release and effort, with its values as the catalog joins them and
// `yours`: each model of offers that found matches to this release alone, as {"harness", "model"},
// at each effort it lists and at a row naming no effort, which is the model however it is run, or
// at the release's default where it lists none but `none`.
func lineup(held *run.Object, harnesses []any, offers map[string][]listing.Model) []any {
	releases := boards.Current(held)
	index := indexOf(releases)
	type place struct{ slug, effort string }
	yours := map[place][]any{}
	for _, each := range harnesses {
		name := each.(string)
		for _, model := range offers[name] {
			hits := map[string]*boards.Release{}
			for _, one := range found(index, model.ID) {
				hits[one.release.Slug] = one.release
			}
			if len(hits) != 1 {
				continue
			}
			worded := slices.ContainsFunc(model.Efforts, func(word string) bool { return word != "none" })
			for _, release := range hits {
				for _, effort := range release.Efforts {
					if worded && (effort.Word == "" || slices.Contains(model.Efforts, effort.Word)) || !worded && effort.Default {
						mine := run.NewObject()
						mine.Set("harness", name)
						mine.Set("model", model.ID)
						at := place{release.Slug, effort.Word}
						yours[at] = append(yours[at], mine)
					}
				}
			}
		}
	}
	rows := []any{}
	for _, release := range releases {
		for _, effort := range release.Efforts {
			row := run.NewObject()
			row.Set("release", release.Slug)
			row.Set("name", release.Name)
			row.Set("maker", release.Maker)
			if effort.Word == "" {
				row.Set("effort", nil)
			} else {
				row.Set("effort", effort.Word)
			}
			row.Set("values", effort.Values)
			mine := yours[place{release.Slug, effort.Word}]
			if mine == nil {
				mine = []any{}
			}
			row.Set("yours", mine)
			rows = append(rows, row)
		}
	}
	return rows
}

// A Matrix is what the boards and the config come to: the rows of the lineup, and when the newest
// board last answered (0 where none has).
type Matrix struct {
	Rows    []quality.Row
	Fetched float64
}

// Refresh is the boards (boards.Collect) and the matrix computed from them and the config, written
// to state/matrix.json; computed again only once a board answered anew, the config's models
// changed, the harnesses installed are not the ones it rowed or ak's own build is not the one that
// computed it, since the harness catalogs it asks take time.  Asked by `ak models`, never the
// tick: the owner wants the assessment as a feature opened, not a process running all day.
// ErrPriced, with nothing written, where the boards as asked give a lineup Go's answer does not
// carry (Priced).
func Refresh(refresh bool) (*Matrix, error) {
	now := float64(time.Now().UnixNano()) / 1e9
	harnesses, err := present()
	if err != nil {
		return nil, err
	}
	build := update.Build()
	held, err := boards.Collect(refresh, now, build, unpriced)
	if err != nil {
		return nil, err
	}
	key, err := configKey()
	if err != nil {
		return nil, err
	}
	matrix := stored()
	// the newest board's, as it reads: an int stays one in the file
	var fetched any = run.Number("0")
	newest := 0.0
	for _, name := range held.Keys() {
		board, _ := held.Get(name).(*run.Object)
		if board == nil {
			continue
		}
		if at, ok := board.Num("fetched_at"); ok && at > newest {
			fetched, newest = board.Get("fetched_at"), at
		}
	}
	computed, hasComputed := matrix.Num("computed_at")
	if !hasComputed {
		computed = -1
	}
	if matrix.Get("lineup") != nil && computed >= newest && run.Equal(matrix.Get("config"), key) &&
		run.Equal(matrix.Get("harnesses"), harnesses) && run.Equal(matrix.Get("build"), build) {
		seen, _ := matrix.Num("fetched_at")
		return &Matrix{rowsOf(matrix.List("lineup")), seen}, nil
	}
	offers := map[string][]listing.Model{}
	for _, name := range harnesses {
		if offers[name.(string)], err = listing.Catalog(name.(string)); err != nil {
			return nil, err
		}
	}
	rows := lineup(held, harnesses, offers)
	written := run.NewObject()
	written.Set("computed_at", now)
	written.Set("config", key)
	written.Set("harnesses", harnesses)
	written.Set("build", build)
	written.Set("lineup", rows)
	written.Set("fetched_at", fetched)
	whole := run.NewObject()
	whole.Set("matrix", written)
	if err := write(whole); err != nil {
		return nil, err
	}
	return &Matrix{rowsOf(rows), newest}, nil
}

// write replaces the file with matrix.lock held, so two writers never share its `.tmp`.
func write(whole *run.Object) error {
	if err := os.MkdirAll(filepath.Dir(path()), 0o777); err != nil {
		return err
	}
	held, err := lock.Wait(context.Background(), strings.TrimSuffix(path(), ".json")+".lock")
	if err != nil {
		return err
	}
	defer held.Close()
	return boards.WriteJSON(path(), whole)
}

// rowsOf is a lineup as quality reads it.
func rowsOf(lineup []any) []quality.Row {
	var rows []quality.Row
	for _, value := range lineup {
		row, _ := value.(*run.Object)
		if row == nil {
			continue
		}
		values := row.Dict("values")
		if values == nil {
			values = run.NewObject()
		}
		rows = append(rows, quality.Row{Release: row.Str("release"), Name: row.Str("name"),
			Effort: row.Str("effort"), Maker: row.Str("maker"), Values: values, Yours: row.Truthy("yours"), Runners: runners(row)})
	}
	return rows
}

// Compared is the releases of rows that `compare` in the config marks, one replaced since as its
// successor, so a mark never holds a replaced model, and one that is neither as nothing; nil,
// every one, where nothing is marked.
func Compared(rows []quality.Row) (map[string]bool, error) {
	marked, err := config.Compare()
	if err != nil {
		return nil, err
	}
	current := map[string]bool{}
	for _, row := range rows {
		current[row.Release] = true
	}
	var held *run.Object // the boards only for a replaced one
	found := map[string]bool{}
	for _, slug := range marked {
		if current[slug] {
			found[slug] = true
			continue
		}
		if held == nil {
			held = boards.Cached()
		}
		if next := boards.Successor(held, slug); next != nil && current[next.Slug] {
			found[next.Slug] = true
		}
	}
	if len(found) == 0 {
		return nil, nil
	}
	return found, nil
}
