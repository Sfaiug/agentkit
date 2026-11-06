package boards

import (
	"cmp"
	"regexp"
	"slices"
	"strings"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// Which models exist now, and what replaced what, read off Artificial Analysis's records as
// Collect holds them.  A release is one model, its efforts each a row of the board; it is current
// while none of its rows is deprecated, and a deprecated one names the release that replaced it
// (`deprecatedTo`), which may itself be replaced.  A series, one maker's releases of one release
// name, whose deprecated releases name a successor takes its current variants along (gone).  The
// record's shape stays here, and so does which release another board's model is: boards name
// models their own way and know nothing of releases.

// A Release is a model as callers see it, its efforts weakest first.
type Release struct {
	Slug        string
	Name, Maker any
	Efforts     []*Effort
}

// An Effort is one row of a release: Word "" where it names none.
type Effort struct {
	Word    string
	Default bool
	Values  *run.Object
}

var (
	digits      = regexp.MustCompile(`\p{Nd}+`)
	bracketDate = regexp.MustCompile(`^(?:20\d\d-?\d\d-?\d\d|\d{4})$`)
	size        = regexp.MustCompile(`(?i)^\d+(\.\d+)?[kmb]$`)
)

type held struct {
	slug string
	rows []*run.Object
}

func rowsOf(board any) []any {
	if object, ok := board.(*run.Object); ok {
		return object.List("rows")
	}
	return nil
}

// releases is each release's rows in the order the board first names it, off rows that carry
// their record's identity: those an older build read carry none, and stand for nothing until a
// new build has asked again.
func releases(boards *run.Object) []*held {
	var found []*held
	bySlug := map[string]*held{}
	for _, value := range rowsOf(boards.Get(artificialAnalysisBoard)) {
		row, _ := value.(*run.Object)
		if row == nil || row.Dict("release") == nil {
			continue
		}
		slug := row.Dict("release").Str("slug")
		if bySlug[slug] == nil {
			bySlug[slug] = &held{slug: slug}
			found = append(found, bySlug[slug])
		}
		bySlug[slug].rows = append(bySlug[slug].rows, row)
	}
	return found
}

func release(from *held) *Release {
	rows := slices.Clone(from.rows)
	slices.SortStableFunc(rows, func(a, b *run.Object) int {
		return cmp.Compare(quality.EffortRank(a.Str("effort")), quality.EffortRank(b.Str("effort")))
	})
	made := &Release{Slug: from.slug, Name: rows[0].Dict("release").Get("name"), Maker: rows[0].Get("maker")}
	for _, row := range rows {
		values := row.Dict("values")
		if values == nil {
			values = run.NewObject()
		}
		made.Efforts = append(made.Efforts, &Effort{row.Str("effort"), row.Str("slug") == from.slug, values.Copy()})
	}
	return made
}

// forms is what a name matches as: its letters and digits alone, ignoring case, and so again with
// each eight-digit date cut to its last four digits.
func forms(name string) []string {
	clean := func(form string) string {
		return strings.Map(func(r rune) rune {
			if unicode.IsLetter(r) || unicode.IsNumber(r) {
				return r
			}
			return -1
		}, strings.ToLower(form))
	}
	cut := digits.ReplaceAllStringFunc(name, func(found string) string {
		if number := []rune(found); len(number) == 8 && strings.HasPrefix(found, "20") {
			return string(number[4:])
		}
		return found
	})
	return []string{clean(name), clean(cut)}
}

// boardNames is forms of another board's model name to try in turn: its brackets of dates and
// sizes cut to their dates, so `Acme 7 (0902)` names the release dated so, then dropped; none
// where another bracket is left, which names a variant of the model (`Acme 7 (Instant)`).
func boardNames(name string) [][]string {
	form := func(dates bool) string {
		return bracket.ReplaceAllStringFunc(name, func(found string) string {
			inner := bracket.FindStringSubmatch(found)[1]
			parts := strings.FieldsFunc(strings.ReplaceAll(inner, ",", " "), config.Space)
			kept := ""
			for _, part := range parts {
				date := bracketDate.MatchString(part)
				if !date && !size.MatchString(part) {
					return found
				}
				if date && dates {
					kept += " " + strings.ReplaceAll(part, "-", "")
				}
			}
			return kept
		})
	}
	if strings.Contains(form(false), "(") {
		return nil
	}
	return [][]string{forms(form(true)), forms(form(false))}
}

// effortOf is the release's effort a board's row at effort measures: the one it names, the
// default where it names none, else the release's only effort; nil where none is.
func effortOf(of *Release, effort string) *Effort {
	for _, each := range of.Efforts {
		if effort != "" && each.Word == effort || effort == "" && each.Default {
			return each
		}
	}
	if len(of.Efforts) == 1 {
		return of.Efforts[0]
	}
	return nil
}

// join puts a board's row's numbers into an effort's values, the lowest of a column kept, since a
// doubt never counts in a model's favour, with its interval from the same row.
func join(values, row *run.Object) {
	for _, column := range row.Keys() {
		if strings.HasSuffix(column, ".lower95ci") || strings.HasSuffix(column, ".upper95ci") {
			if row.Has(column[:strings.LastIndexByte(column, '.')]) {
				continue
			}
		}
		number, _ := row.Num(column)
		have, ok := values.Num(column)
		if ok && number >= have {
			continue
		}
		for _, name := range []string{column, column + ".lower95ci", column + ".upper95ci"} {
			if row.Has(name) {
				values.Set(name, row.Get(name))
			} else {
				values.Delete(name)
			}
		}
	}
}

func current(from *held) bool {
	return !slices.ContainsFunc(from.rows, func(row *run.Object) bool { return row.Truthy("deprecated") })
}

// end is the current release the release slug's deprecatedTo chain reaches, itself when it is
// current, a release stepping to the one successor its rows name, whichever row names it; "" when
// the chain reaches a slug the board does not list, a release naming no successor or several, or
// a loop.
func end(all map[string]*held, slug string) string {
	seen := map[string]bool{}
	for all[slug] != nil && !seen[slug] {
		if current(all[slug]) {
			return slug
		}
		seen[slug] = true
		named := map[string]bool{}
		for _, row := range all[slug].rows {
			if next := row.Dict("release").Str("deprecatedTo"); next != "" {
				named[next] = true
			}
		}
		slug = ""
		if len(named) == 1 {
			for next := range named {
				slug = next
			}
		}
	}
	return ""
}

// gone is where each current release its series gives up went, "" for nowhere.  A series none of
// whose deprecated releases names a successor keeps all: on the board a retired model beside its
// variant looks like a retired preview beside its model, and only display names, which follow no
// pattern, tell the two apart.  Otherwise, once one of their ends lies outside the series every
// current release goes, to that end when it is the only one outside; else the ends stay and the
// others go, to the end when there is exactly one.
func gone(found []*held) map[string]string {
	all := map[string]*held{}
	series := map[string][]*held{}
	var order []string
	for _, each := range found {
		all[each.slug] = each
		first := each.rows[0]
		key := run.Line([]any{first.Get("maker"), first.Dict("release").Get("name")})
		if series[key] == nil {
			order = append(order, key)
		}
		series[key] = append(series[key], each)
	}
	out := map[string]string{}
	for _, key := range order {
		members := series[key]
		named := false
		inside, ends := map[string]bool{}, map[string]bool{}
		for _, each := range members {
			inside[each.slug] = true
			if current(each) {
				continue
			}
			for _, row := range each.rows {
				named = named || row.Dict("release").Str("deprecatedTo") != ""
			}
			if reached := end(all, each.slug); reached != "" {
				ends[reached] = true
			}
		}
		if !named {
			continue
		}
		outside := map[string]bool{}
		for reached := range ends {
			if !inside[reached] {
				outside[reached] = true
			}
		}
		to, stay := ends, ends
		if len(outside) > 0 {
			to, stay = outside, map[string]bool{}
		}
		for _, each := range members {
			if stay[each.slug] || !current(each) {
				continue
			}
			out[each.slug] = ""
			if len(to) == 1 {
				for target := range to {
					out[each.slug] = target
				}
			}
		}
	}
	return out
}

// Current is Artificial Analysis's current releases their series keep (gone), strongest first by
// their best index; those without one last, by name.  Each effort's Values carry, beside its own
// row's, those of every other board's rows naming the release (the first of boardNames meeting
// forms of any current release's name, of its alone) at that effort.
func Current(boards *run.Object) []*Release {
	all := releases(boards)
	given := gone(all)
	type ranked struct {
		from    *held
		best    float64
		indexed bool
		name    string
	}
	var order []ranked
	for _, each := range all {
		rank := ranked{from: each, name: run.Text(each.rows[0].Dict("release").Get("name"))}
		for _, row := range each.rows {
			if values := row.Dict("values"); values != nil {
				if index, ok := values.Num("aa.intelligenceIndex"); ok && (!rank.indexed || index > rank.best) {
					rank.best, rank.indexed = index, true
				}
			}
		}
		order = append(order, rank)
	}
	slices.SortStableFunc(order, func(a, b ranked) int {
		if a.indexed != b.indexed {
			if a.indexed {
				return -1
			}
			return 1
		}
		return cmp.Or(cmp.Compare(b.best, a.best), strings.Compare(a.name, b.name))
	})
	var out []*Release
	named := map[string][]*Release{}
	for _, each := range order {
		if _, left := given[each.from.slug]; left || !current(each.from) {
			continue
		}
		made := release(each.from)
		out = append(out, made)
		for _, form := range forms(run.Text(made.Name)) {
			named[form] = append(named[form], made)
		}
	}
	for _, board := range names {
		if board == artificialAnalysisBoard {
			continue
		}
		for _, value := range rowsOf(boards.Get(board)) {
			row, _ := value.(*run.Object)
			if row == nil {
				continue
			}
			for _, tried := range boardNames(row.Str("model")) {
				matched := map[string]*Release{}
				for _, form := range tried {
					for _, each := range named[form] {
						matched[each.Slug] = each
					}
				}
				if len(matched) == 0 {
					continue
				}
				if len(matched) == 1 {
					for _, each := range matched {
						if effort := effortOf(each, row.Str("effort")); effort != nil && row.Dict("values") != nil {
							join(effort.Values, row.Dict("values"))
						}
					}
				}
				break
			}
		}
	}
	return out
}
