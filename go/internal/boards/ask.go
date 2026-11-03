package boards

import (
	"crypto/tls"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// Artificial Analysis, a page of its site, no key: per model and effort, every benchmark's score,
// index, price and cost the page hands its scripts, which its free endpoint leaves out, and the
// record's identity for catalog.  Arena, its leaderboard's Hugging Face dataset, no key: each
// board quality rates on at its category, with its 95% interval, no row of a model run inside
// another harness.  A row is one model at one effort, with every number the board gives as
// `<board>.<field>`, a table's fields under the table's name, a list's tables under each one's
// slug.  Attribution: Source: Artificial Analysis (artificialanalysis.ai); Arena (lmarena-ai),
// leaderboard-dataset, CC-BY-4.0.
const (
	timeout = 30 * time.Second // one request
	pace    = time.Second      // between two asks of one host: a day's asks are a few dozen
	// a retired model's page carries every model's record whole
	aaPage   = "https://artificialanalysis.ai/models/gpt-35-turbo"
	arenaURL = "https://datasets-server.huggingface.co/%s?dataset=lmarena-ai/leaderboard-dataset&config=%s&split=latest"
)

// retries are the waits before asking again after a server error: Hugging Face's dataset server
// answers about one ask in seven with one while it is up, and refuses every ask for minutes once
// asked faster.
var retries = []time.Duration{2 * time.Second, 4 * time.Second}

var (
	aaRecord = regexp.MustCompile(`\{"id":"[0-9a-f-]{36}","slug":"[^"]+","name":"`)
	aaChunk  = regexp.MustCompile(`self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)`)
	bracket  = regexp.MustCompile(`\s*\(([^()]*)\)`)
	lastAsk  = map[string]time.Time{}
)

// arenaFields are an Arena row's number and the ends of its 95% interval: a rate on the agent
// boards, a rating on the others.
var arenaFields = [][3]string{{"score", "score_ci_lower", "score_ci_upper"}, {"rating", "rating_lower", "rating_upper"}}

// effortWords are the words a board writes an effort as, each to ak's own.
var effortWords = map[string]string{"x-high": "xhigh", "extra high": "xhigh", "non-reasoning": "none"}

// fetch is one GET and its body: the one place the network is touched, so tests hand bodies in.
var fetch = get

// client asks over HTTP/1.1, as Python does: HTTP/2 carries no reason phrase, and a board's failure
// is recorded in the server's words.
var client = http.Client{Timeout: timeout, Transport: &http.Transport{
	Proxy:        http.ProxyFromEnvironment,
	TLSNextProto: map[string]func(string, *tls.Conn) http.RoundTripper{},
}}

func get(address string) ([]byte, error) {
	parsed, err := url.Parse(address)
	if err != nil {
		return nil, err
	}
	for attempt := 0; ; attempt++ {
		time.Sleep(time.Until(lastAsk[parsed.Host].Add(pace)))
		lastAsk[parsed.Host] = time.Now()
		response, err := client.Get(address)
		if err != nil {
			return nil, err
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if response.StatusCode < 400 {
			return body, err
		}
		if response.StatusCode < 500 || attempt == len(retries) {
			return nil, fmt.Errorf("HTTP Error %s", strings.Replace(response.Status, " ", ": ", 1))
		}
		time.Sleep(retries[attempt])
	}
}

// splitEffort is the model's name without its effort, and the effort or "", off a board's model
// name: `Acme 5 (max)` is Acme 5 at max, `Acme 5 (max) (0813)` is Acme 5 (0813) at max, and a
// bracket of several words keeps the others (`Acme 5 (Max, Default Fallback)` is Acme 5 (Default
// Fallback) at max); a bracket naming no effort stays on the name.  `thinking` and `reasoning`
// name no effort, and are cut too.
func splitEffort(name string) (string, string) {
	for _, found := range bracket.FindAllStringSubmatchIndex(name, -1) {
		parts := strings.Split(name[found[2]:found[3]], ",")
		for i := range parts {
			parts[i] = strings.TrimFunc(parts[i], config.Space)
		}
		for _, part := range parts {
			word := strings.ToLower(part)
			if own, ok := effortWords[word]; ok {
				word = own
			}
			if quality.EffortRank(word) < 0 && word != "thinking" && word != "reasoning" {
				continue
			}
			var others []string
			for _, other := range parts {
				if other != part {
					others = append(others, other)
				}
			}
			kept := ""
			if len(others) > 0 {
				kept = " (" + strings.Join(others, ", ") + ")"
			}
			rest := strings.TrimFunc(name[:found[0]]+kept+name[found[1]:], config.Space)
			if quality.EffortRank(word) < 0 {
				word = ""
			}
			return rest, word
		}
	}
	return name, ""
}

// effortValue is an effort as a board's row holds it: null where it names none.
func effortValue(effort string) any {
	if effort == "" {
		return nil
	}
	return effort
}

// numbers is every number of entry as `prefix.field`, a table's fields under the table's name and
// a list's tables under each one's slug.
func numbers(entry *run.Object, prefix string, into *run.Object) {
	for _, field := range entry.Keys() {
		switch value := entry.Get(field).(type) {
		case run.Number:
			into.Set(prefix+"."+field, value)
		case *run.Object:
			numbers(value, prefix+"."+field, into)
		case []any:
			for _, item := range value {
				if table, ok := item.(*run.Object); ok {
					if slug, ok := table.Get("slug").(string); ok {
						numbers(table, prefix+"."+field+"."+slug, into)
					}
				}
			}
		}
	}
}

// artificialAnalysis is its rows, one per model and effort: each model's record in the data
// aaPage hands its scripts, one per slug.  A page with no model's record is an error: the site
// changed, and the board keeps what it last said.
func artificialAnalysis() ([]any, error) {
	page, err := fetch(aaPage)
	if err != nil {
		return nil, err
	}
	var data strings.Builder
	for _, chunk := range aaChunk.FindAllSubmatch([]byte(strings.ToValidUTF8(string(page), "�")), -1) {
		value, err := run.Decode(chunk[1])
		if err != nil {
			return nil, err
		}
		text, _ := value.(string)
		data.WriteString(text)
	}
	return aaRows([]byte(data.String()))
}

func aaRows(data []byte) ([]any, error) {
	records := run.NewObject()
	for _, found := range aaRecord.FindAllIndex(data, -1) {
		value, err := run.DecodeAt(data, found[0])
		record, ok := value.(*run.Object)
		if err != nil || !ok || !record.Has("release") { // a maker's, not a model's
			continue
		}
		slug := record.Str("slug")
		merged := records.Dict(slug)
		if merged == nil {
			merged = run.NewObject()
			records.Set(slug, merged)
		}
		for _, field := range record.Keys() {
			if record.Get(field) != nil {
				merged.Set(field, record.Get(field))
			}
		}
	}
	if len(records.Keys()) == 0 {
		return nil, fmt.Errorf("no model's record on %s", aaPage)
	}
	rows := []any{}
	for _, slug := range records.Keys() {
		record := records.Dict(slug)
		release := record.Dict("release")
		if release == nil {
			return nil, fmt.Errorf("%s has no release", slug)
		}
		name, effort := splitEffort(run.Text(record.Get("name")))
		// the newest records give Briefcase's overall rating flat, the others under `overall`
		if briefcase := record.Dict("briefcaseBreakdown"); briefcase != nil && !briefcase.Has("overall") {
			overall := run.NewObject()
			for _, field := range []string{"elo", "lower95ci", "upper95ci"} {
				if briefcase.Has(field) {
					overall.Set(field, briefcase.Get(field))
					briefcase.Delete(field)
				}
			}
			briefcase.Set("overall", overall)
		}
		values := run.NewObject()
		numbers(record, "aa", values)
		identity := run.NewObject()
		for _, field := range []string{"slug", "name", "deprecatedTo"} {
			identity.Set(field, release.Get(field))
		}
		var maker any
		if creator := record.Dict("creator"); creator != nil {
			maker = creator.Get("name")
		}
		row := run.NewObject()
		row.Set("model", name)
		row.Set("effort", effortValue(effort))
		row.Set("values", values)
		row.Set("slug", slug)
		row.Set("release", identity)
		row.Set("maker", maker)
		row.Set("deprecated", record.Get("deprecated") == true)
		rows = append(rows, row)
	}
	return rows, nil
}

// harnessed is whether a name is a model run inside another program than Arena's own, which
// measures that program too: the word `harness` between any separators, `_` among them, but not
// as the word after `arena`.
func harnessed(name string) bool {
	alnum := func(r rune) bool { return r >= 'a' && r <= 'z' || r >= '0' && r <= '9' }
	lower := strings.Map(func(r rune) rune {
		if r >= 'A' && r <= 'Z' {
			return r + 'a' - 'A'
		}
		return r
	}, name)
	for at := 0; ; at += len("harness") {
		next := strings.Index(lower[at:], "harness")
		if next < 0 {
			return false
		}
		at += next
		before := lower[:at]
		last, size := utf8.DecodeLastRuneInString(before)
		follows, _ := utf8.DecodeRuneInString(lower[at+len("harness"):])
		if alnum(last) || alnum(follows) {
			continue
		}
		stem, afterArena := strings.CutSuffix(before[:len(before)-size], "arena")
		if size > 0 && afterArena {
			if prior, _ := utf8.DecodeLastRuneInString(stem); !alnum(prior) {
				continue
			}
		}
		return true
	}
}

// arenaBoards are the boards quality rates on, each [board, category], sorted.
func arenaBoards() [][2]string {
	var found [][2]string
	for _, column := range quality.Columns() {
		parts := strings.Split(column, ".")
		if parts[0] != "arena" {
			continue
		}
		pair := [2]string{parts[1], "overall"}
		if len(parts) > 2 {
			pair[1] = parts[2]
		}
		if !slices.Contains(found, pair) {
			found = append(found, pair)
		}
	}
	slices.SortFunc(found, func(a, b [2]string) int { return strings.Compare(a[0]+"\x00"+a[1], b[0]+"\x00"+b[1]) })
	return found
}

// arena is its rows: each of arenaBoards a column with its interval, for every model its latest
// leaderboard lists at that category.  A board's rows come grouped by category, overall first and
// the others in their alphabetical order, so the dataset's counts per category say where the
// wanted ones start, and every row read is checked to be one of them, all of them read.
func arena() ([]any, error) {
	rows := []any{}
	held := map[[2]string]*run.Object{}
	for _, wanted := range arenaBoards() {
		board, category := wanted[0], wanted[1]
		value, err := askJSON(fmt.Sprintf(arenaURL, "statistics", board))
		if err != nil {
			return nil, err
		}
		counts := categoryCounts(value)
		count, ok := counts[category]
		if !ok {
			return nil, fmt.Errorf("arena.ai: %s has no %s rows", board, category)
		}
		offset := 0
		for name, each := range counts {
			if name != category && category != "overall" && (name == "overall" || name < category) {
				offset += each
			}
		}
		column := "arena." + board
		if category != "overall" {
			column += "." + category
		}
		var found []*run.Object
		for len(found) < count {
			value, err := askJSON(fmt.Sprintf(arenaURL, "rows", board) + "&offset=" + strconv.Itoa(offset+len(found)) +
				"&length=" + strconv.Itoa(min(100, count-len(found))))
			if err != nil {
				return nil, err
			}
			page, _ := value.(*run.Object)
			var items []any
			if page != nil {
				items = page.List("rows")
			}
			if len(items) == 0 {
				break
			}
			for _, item := range items {
				row := run.NewObject()
				if each, ok := item.(*run.Object); ok && each.Dict("row") != nil {
					row = each.Dict("row")
				}
				found = append(found, row)
			}
		}
		if len(found) != count || slices.ContainsFunc(found, func(row *run.Object) bool { return row.Str("category") != category }) {
			return nil, fmt.Errorf("arena.ai: %s's %s rows are not where its counts put them", board, category)
		}
		for _, row := range found {
			at := slices.IndexFunc(arenaFields, func(fields [3]string) bool {
				_, ok := row.Num(fields[0])
				return ok
			})
			if at < 0 || !row.Truthy("model_name") || harnessed(run.Text(row.Get("model_name"))) ||
				row.Truthy("model_key") && harnessed(run.Text(row.Get("model_key"))) {
				continue
			}
			model, effort := splitEffort(run.Text(row.Get("model_name")))
			entry, ok := held[[2]string{model, effort}]
			if !ok {
				entry = run.NewObject()
				entry.Set("model", model)
				entry.Set("effort", effortValue(effort))
				entry.Set("values", run.NewObject())
				held[[2]string{model, effort}] = entry
				rows = append(rows, entry)
			}
			for i, name := range []string{column, column + ".lower95ci", column + ".upper95ci"} {
				if _, ok := row.Num(arenaFields[at][i]); ok {
					entry.Dict("values").Set(name, row.Get(arenaFields[at][i]))
				}
			}
		}
	}
	return rows, nil
}

func askJSON(address string) (any, error) {
	body, err := fetch(address)
	if err != nil {
		return nil, err
	}
	return run.Decode(body)
}

// categoryCounts is the rows a dataset's statistics say each category has.
func categoryCounts(statistics any) map[string]int {
	counts := map[string]int{}
	whole, _ := statistics.(*run.Object)
	if whole == nil {
		return counts
	}
	for _, each := range whole.List("statistics") {
		column, _ := each.(*run.Object)
		if column == nil || column.Str("column_name") != "category" {
			continue
		}
		if stats := column.Dict("column_statistics"); stats != nil && stats.Dict("frequencies") != nil {
			frequencies := stats.Dict("frequencies")
			for _, name := range frequencies.Keys() {
				counts[name], _ = frequencies.Int(name)
			}
		}
		break
	}
	return counts
}
