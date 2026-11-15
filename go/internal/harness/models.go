package harness

import (
	"cmp"
	"fmt"
	"io"
	"os"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// catalogued writes tools/catalog.py's line for each of a listing's rows, [id, label, efforts]:
// the [catalog] table's label where it has that id, else the row's own, else the id; the row's
// efforts where it says them, else the table's, else unsaid.  So a harness that lists only its
// ids gets their efforts, while one that lists its own keeps them.
func catalogued(out io.Writer, harness string, rows [][]string) {
	table, _ := config.CatalogTable(harness)
	for _, row := range rows {
		label, efforts := cmp.Or(row[1], row[0]), strings.Join(strings.Fields(row[2]), " ")
		if at := slices.IndexFunc(table, func(known []string) bool { return known[0] == row[0] }); at >= 0 {
			label, efforts = table[at][2], cmp.Or(efforts, table[at][1])
		}
		fmt.Fprintf(out, "%s\t%s\t%s\n", row[0], label, efforts)
	}
}

// texts is those values as jq's @tsv and join write them, a string itself and null nothing; false
// where one is anything else, which no listing of a harness's holds.
func texts(values []any) ([]string, bool) {
	said := make([]string, len(values))
	for i, value := range values {
		text, isText := value.(string)
		if !isText && value != nil {
			return nil, false
		}
		said[i] = text
	}
	return said, true
}

// unsetting is this process's environment as a script's `unset` of those names and `export` of
// those pairs leave it for what it runs.
func unsetting(names []string, set ...string) []string {
	return append(slices.DeleteFunc(os.Environ(), func(pair string) bool {
		name, _, _ := strings.Cut(pair, "=")
		return slices.Contains(names, name)
	}), set...)
}
