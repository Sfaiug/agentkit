package boards

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/quality"
	"agentkit/internal/run"
)

func decoded(t *testing.T, text string) any {
	t.Helper()
	value, err := run.Decode([]byte(text))
	if err != nil {
		t.Fatal(err)
	}
	return value
}

func TestSplitEffort(t *testing.T) {
	for name, want := range map[string][2]string{
		"Acme 5":                         {"Acme 5", ""},
		"Acme 5 (max)":                   {"Acme 5", "max"},
		"Acme 5 (x-high)":                {"Acme 5", "xhigh"},
		"Acme 5 (max) (0813)":            {"Acme 5 (0813)", "max"},
		"Acme 5 (Max, Default Fallback)": {"Acme 5 (Default Fallback)", "max"},
		"Acme 5 (Non-reasoning)":         {"Acme 5", "none"},
		"Acme 5 (Thinking)":              {"Acme 5", ""},
		"Acme 5 (Preview)":               {"Acme 5 (Preview)", ""},
	} {
		if model, effort := splitEffort(name); model != want[0] || effort != want[1] {
			t.Errorf("%q: %q %q", name, model, effort)
		}
	}
}

func TestHarnessedIsTheWordBetweenSeparators(t *testing.T) {
	for name, want := range map[string]bool{
		"acme-5": false, "acme_harness_5": true, "acme (Harness)": true, "harness": true, "harnesses": false,
		"unharness": false, "arena-harness": false, "arena_harness x": false, "myarena-harness": true,
		"arena-harness harness": true, "ARENA HARNESS": false, "Acme harness": true,
	} {
		if got := harnessed(name); got != want {
			t.Errorf("%q: %v", name, got)
		}
	}
}

func TestAPagesRecordsBecomeRows(t *testing.T) {
	id := strings.Repeat("a", 36)
	record := func(slug, name string, more string) string {
		return `{"id":"` + id + `","slug":"` + slug + `","name":"` + name + `",` + more + `}`
	}
	data, _ := json.Marshal("junk " + record("acme-5-max", "Acme 5 (max)",
		`"release":{"slug":"acme-5","name":"Acme 5","deprecatedTo":null,"extra":1},"creator":{"name":"Acme"},`+
			`"intelligenceIndex":70,"on":true,"deprecated":true,"briefcaseBreakdown":{"elo":1400,"lower95ci":1390},`+
			`"intelligenceIndexEvaluations":[{"slug":"frontiercode-2-0","costPerTask":3.5},{"nameless":1}],"cost":{"total":2.5}`) +
		" and " + record("acme-5-max", "Acme 5 (max)", `"release":{"slug":"acme-5","name":"Acme 5"},"late":1,"intelligenceIndex":null`) +
		" maker " + record("acme", "Acme", `"website":"x"`))
	fetch = func(string) ([]byte, error) {
		return []byte(`<script>self.__next_f.push([1,` + string(data) + `])</script>`), nil
	}
	defer func() { fetch = get }()
	rows, err := artificialAnalysis()
	if err != nil {
		t.Fatal(err)
	}
	want := `[{"model": "Acme 5", "effort": "max", "values": {"aa.intelligenceIndex": 70, ` +
		`"aa.briefcaseBreakdown.overall.elo": 1400, "aa.briefcaseBreakdown.overall.lower95ci": 1390, ` +
		`"aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask": 3.5, "aa.cost.total": 2.5, "aa.late": 1}, ` +
		`"slug": "acme-5-max", "release": {"slug": "acme-5", "name": "Acme 5", "deprecatedTo": null}, "maker": "Acme", "deprecated": true}]`
	if got := run.Line(rows); got != want {
		t.Fatalf("rows:\n%s\nwant\n%s", got, want)
	}
	fetch = func(string) ([]byte, error) { return []byte("no records here"), nil }
	if _, err := artificialAnalysis(); err == nil {
		t.Fatal("a page with no model's record is an error: the site changed")
	}
}

// arenaBodies answers for one agent board whose overall rows come first and a harness row among them.
func arenaBodies(address string) ([]byte, error) {
	if strings.Contains(address, "/statistics") {
		return []byte(`{"statistics":[{"column_name":"other"},{"column_name":"category","column_statistics":{"frequencies":{"coding":9,"overall":3}}}]}`), nil
	}
	if !strings.Contains(address, "config=agent") || !strings.Contains(address, "offset=0") || !strings.Contains(address, "length=3") {
		return nil, fmt.Errorf("asked %s", address)
	}
	return []byte(`{"rows":[{"row":{"category":"overall","model_name":"Acme 5 (max)","score":0.8,"score_ci_lower":0.7,"score_ci_upper":0.9}},
		{"row":{"category":"overall","model_name":"Bolt 3","model_key":"bolt_harness","score":0.5}},
		{"row":{"category":"overall","model_name":"Crux 2","rating":1400,"rating_lower":1390}}]}`), nil
}

func TestArenaReadsEachBoardsCategoryFromItsCounts(t *testing.T) {
	fetch = arenaBodies
	defer func() { fetch = get }()
	rows, err := arena()
	if err != nil {
		t.Fatal(err)
	}
	want := `[{"model": "Acme 5", "effort": "max", "values": {"arena.agent": 0.8, "arena.agent.lower95ci": 0.7, "arena.agent.upper95ci": 0.9}}, ` +
		`{"model": "Crux 2", "effort": null, "values": {"arena.agent": 1400, "arena.agent.lower95ci": 1390}}]`
	if got := run.Line(rows); got != want {
		t.Fatalf("rows:\n%s\nwant\n%s", got, want)
	}
	fetch = func(address string) ([]byte, error) {
		if strings.Contains(address, "/statistics") {
			return arenaBodies(address)
		}
		return []byte(`{"rows":[{"row":{"category":"coding"}},{"row":{"category":"coding"}},{"row":{"category":"coding"}}]}`), nil
	}
	if _, err := arena(); err == nil || !strings.Contains(err.Error(), "not where its counts put them") {
		t.Fatalf("rows of another category: %v", err)
	}
}

func sandbox(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "state"), 0o777); err != nil {
		t.Fatal(err)
	}
	return filepath.Join(home, ".agentkit", "state", "boards.json")
}

func TestABoardIsAskedDailyAndAFailureKeepsItsRows(t *testing.T) {
	file := sandbox(t)
	keepAll := func(*run.Object) error { return nil }
	asked := map[string]int{}
	real := asks
	defer func() { asks = real }()
	asks = map[string]func() ([]any, error){
		artificialAnalysisBoard: func() ([]any, error) { asked["aa"]++; return nil, errors.New("site\n  down") },
		arenaBoard:              func() ([]any, error) { asked["arena"]++; return []any{}, nil },
	}
	if err := os.WriteFile(file, []byte(`{"artificialanalysis.ai": {"asked_at": 1000, "fetched_at": 1000, "rows": [{"model": "Kept", "values": {}}], "error": null, "build": "b"}, "retired.example": {}}`), 0o666); err != nil {
		t.Fatal(err)
	}
	cache, err := Collect(false, 1000+freshFor, "b", keepAll)
	if err != nil {
		t.Fatal(err)
	}
	if asked["aa"] != 1 || asked["arena"] != 1 {
		t.Fatalf("asked %v", asked)
	}
	board := cache.Dict(artificialAnalysisBoard)
	if len(board.List("rows")) != 1 || board.Str("error") != "site down" {
		t.Fatalf("board %s", run.Line(board))
	}
	if fetched, _ := board.Num("fetched_at"); fetched != 1000 {
		t.Fatalf("a failure moved fetched_at to %v", fetched)
	}
	data, _ := os.ReadFile(file)
	if held := decoded(t, string(data)).(*run.Object); held.Has("retired.example") || held.Dict(arenaBoard) == nil {
		t.Fatalf("file %s", data)
	}
	// the day counts from asked_at, answered or not
	if _, err := Collect(false, 1000+freshFor+5, "b", keepAll); err != nil {
		t.Fatal(err)
	}
	if asked["aa"] != 1 || asked["arena"] != 1 {
		t.Fatalf("asked within the day: %v", asked)
	}
	if _, err := Collect(true, 1000+freshFor+5, "b", keepAll); err != nil {
		t.Fatal(err)
	}
	if asked["aa"] != 2 || asked["arena"] != 2 {
		t.Fatalf("--refresh: %v", asked)
	}
	// a refused answer leaves the file as it was
	kept, _ := os.ReadFile(file)
	refused := errors.New("refused")
	if _, err := Collect(true, 1000+freshFor+10, "b", func(*run.Object) error { return refused }); err != refused {
		t.Fatalf("refused: %v", err)
	}
	if data, _ := os.ReadFile(file); string(data) != string(kept) {
		t.Fatalf("a refused answer was written: %s", data)
	}
}

func TestAnotherBuildAsksAgainOnlyForAColumnItsRowsLack(t *testing.T) {
	sandbox(t)
	last := func(values string) *run.Object {
		return decoded(t, `{"asked_at": 1000, "build": "old", "rows": [{"model": "x", "slug": "s", "release": {}, "maker": "m", "deprecated": false, "values": {`+values+`}}]}`).(*run.Object)
	}
	var all []string
	for _, column := range append(quality.Needed(), "aa.intelligenceIndexEvaluations.x") {
		if strings.HasPrefix(column, "aa.") {
			all = append(all, `"`+column+`": 1`)
		}
	}
	whole := strings.Join(all, ", ")
	if !fresh(artificialAnalysisBoard, last(whole), 1001, "new") {
		t.Fatal("a board carrying all this build reads was asked again")
	}
	if fresh(artificialAnalysisBoard, last(`"aa.intelligenceIndex": 1`), 1001, "new") {
		t.Fatal("a board lacking a column this build reads stood")
	}
	if !fresh(artificialAnalysisBoard, last(`"aa.intelligenceIndex": 1`), 1001, "old") {
		t.Fatal("this build's own board was asked again")
	}
	if fresh(artificialAnalysisBoard, last(whole), 1000+freshFor, "new") {
		t.Fatal("a day old board stood")
	}
}

func TestCachedFallsBackToTheMatrixFileUntilThereIsABoardsFile(t *testing.T) {
	file := sandbox(t)
	legacy := filepath.Join(filepath.Dir(file), "matrix.json")
	if err := os.WriteFile(legacy, []byte(`{"arena.ai": {"asked_at": 5}, "matrix": {}}`), 0o666); err != nil {
		t.Fatal(err)
	}
	if got := run.Line(Cached()); got != `{"arena.ai": {"asked_at": 5}}` {
		t.Fatalf("legacy: %s", got)
	}
	if err := os.WriteFile(file, []byte(`not json`), 0o666); err != nil {
		t.Fatal(err)
	}
	if got := run.Line(Cached()); got != `{}` {
		t.Fatalf("unreadable: %s", got)
	}
}

func board(rows ...string) *run.Object {
	whole, _ := run.Decode([]byte(`{"artificialanalysis.ai": {"rows": [` + strings.Join(rows, ",") + `]}, "arena.ai": {"rows": []}}`))
	return whole.(*run.Object)
}

func aaRow(slug, release, name, effort string, deprecated bool, to string, index float64) string {
	next := "null"
	if to != "" {
		next = `"` + to + `"`
	}
	word := "null"
	if effort != "" {
		word = `"` + effort + `"`
	}
	return fmt.Sprintf(`{"model": %q, "effort": %s, "slug": %q, "maker": "Acme", "deprecated": %v, "values": {"aa.intelligenceIndex": %v}, "release": {"slug": %q, "name": %q, "deprecatedTo": %s}}`,
		name, word, slug, deprecated, index, release, name, next)
}

func slugs(releases []*Release) []string {
	var found []string
	for _, each := range releases {
		found = append(found, each.Slug)
	}
	return found
}

func TestCurrentKeepsWhatItsSeriesKeeps(t *testing.T) {
	boards := board(
		aaRow("old", "old", "Old", "", true, "new", 90),
		aaRow("new", "new", "New", "", false, "", 80),
		aaRow("new-max", "new", "New", "max", false, "", 85),
		aaRow("strong", "strong", "Strong", "", false, "", 99),
		aaRow("alone", "alone", "Alone", "", true, "", 99),
		aaRow("noindex", "noindex", "Noindex", "", false, "", 0),
		// a series: a retired one of it names a release outside, so its current variant goes too
		aaRow("fade", "fade", "Fade", "", true, "new", 50),
		aaRow("fade-v", "fade-v", "Fade", "", false, "", 50),
	)
	if got := slugs(Current(boards)); !reflect.DeepEqual(got, []string{"strong", "new", "noindex"}) {
		t.Fatalf("current %v", got)
	}
	efforts := Current(boards)[1].Efforts
	if efforts[0].Word != "" || !efforts[0].Default || efforts[1].Word != "max" || efforts[1].Default {
		t.Fatalf("efforts %+v %+v", efforts[0], efforts[1])
	}
	for slug, want := range map[string]string{"old": "new", "fade": "new", "fade-v": "new", "strong": "strong"} {
		if found := Successor(boards, slug); found == nil || found.Slug != want {
			t.Errorf("successor of %s: %+v", slug, found)
		}
	}
	if found := Successor(boards, "alone"); found != nil {
		t.Errorf("alone names no successor: %+v", found)
	}
}

func TestAnotherBoardsRowJoinsTheReleaseItNames(t *testing.T) {
	boards := board(
		aaRow("acme-7", "acme-7", "Acme 7", "", false, "", 80),
		aaRow("acme-7-0902", "acme-7-0902", "Acme 7 0902", "", false, "", 70),
		aaRow("bolt-3-max", "bolt-3", "Bolt 3", "max", false, "", 60),
		aaRow("bolt-3-low", "bolt-3", "Bolt 3", "low", false, "", 55),
	)
	other := func(model, effort string, values string) any {
		word := "null"
		if effort != "" {
			word = `"` + effort + `"`
		}
		return decoded(t, fmt.Sprintf(`{"model": %q, "effort": %s, "values": {%s}}`, model, word, values))
	}
	boards.Dict(arenaBoard).Set("rows", []any{
		other("Acme 7", "", `"arena.agent": 0.5, "arena.agent.lower95ci": 0.4`),
		other("Acme 7", "", `"arena.agent": 0.6, "arena.agent.upper95ci": 0.7`), // the lowest stands, with its interval
		other("Acme 7 (0902)", "", `"arena.agent": 0.3`),                        // the dated release, not Acme 7
		other("Acme 7 (Instant)", "", `"arena.agent": 0.1`),                     // a variant: no release
		other("Bolt 3", "max", `"arena.agent": 0.8`),
		other("Bolt 3", "high", `"arena.agent": 0.2`), // an effort the release lacks
		other("Bolt 3", "", `"arena.agent": 0.2`),     // no default, and two efforts
	})
	values := map[string]string{}
	for _, release := range Current(boards) {
		for _, effort := range release.Efforts {
			values[release.Slug+"/"+effort.Word] = run.Line(effort.Values)
		}
	}
	for at, want := range map[string]string{
		"acme-7/":      `{"aa.intelligenceIndex": 80, "arena.agent": 0.5, "arena.agent.lower95ci": 0.4}`,
		"acme-7-0902/": `{"aa.intelligenceIndex": 70, "arena.agent": 0.3}`,
		"bolt-3/max":   `{"aa.intelligenceIndex": 60, "arena.agent": 0.8}`,
		"bolt-3/low":   `{"aa.intelligenceIndex": 55}`,
	} {
		if values[at] != want {
			t.Errorf("%s: %s, want %s", at, values[at], want)
		}
	}
}

func TestAFailureIsRecordedInTheServersOwnWords(t *testing.T) {
	var protocol string
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		protocol = r.Proto
		connection, buffer, err := w.(http.Hijacker).Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		defer connection.Close()
		buffer.WriteString("HTTP/1.1 404 Gone Fishing\r\nContent-Length: 0\r\n\r\n")
		buffer.Flush()
	}))
	server.EnableHTTP2 = true // were it spoken, there would be no words to record
	server.StartTLS()
	defer server.Close()
	transport := client.Transport.(*http.Transport)
	trusted := x509.NewCertPool()
	trusted.AddCert(server.Certificate())
	transport.TLSClientConfig = &tls.Config{RootCAs: trusted}
	defer func() { transport.TLSClientConfig = nil }()
	_, err := get(server.URL)
	if err == nil || err.Error() != "HTTP Error 404: Gone Fishing" || protocol != "HTTP/1.1" {
		t.Fatalf("%v over %s", err, protocol)
	}
}
