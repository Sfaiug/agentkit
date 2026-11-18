package boards

import (
	"reflect"
	"testing"
)

func index(names ...string) Index {
	found := Index{}
	for _, name := range names {
		found[normal(name)] = append(found[normal(name)], Hit{name, &Release{Slug: name}})
	}
	return found
}

func TestAModelIsFoundUnderTheNamesABoardGivesIt(t *testing.T) {
	for _, each := range []struct {
		names []string
		model string
		want  []string
	}{
		{[]string{"Acme 5"}, "provider/acme-5", []string{"Acme 5"}},
		{[]string{"Acme Pro"}, "acme-pro-1.0", []string{"Acme Pro"}},
		{[]string{"Acme 5"}, "acme-5-5", nil}, // a board's name with its own version: another model
		{[]string{"Acme 5 (Default Fallback)"}, "acme-5", []string{"Acme 5 (Default Fallback)"}},
		{[]string{"Acme 5 (One)", "Acme 5 (Two)"}, "acme-5", nil},
		{[]string{"Acme Flash 1017", "Acme Flash 1102"}, "acme-flash", []string{"Acme Flash 1017", "Acme Flash 1102"}},
		{[]string{"Acme 5"}, "acme-5-free", []string{"Acme 5"}},
		{[]string{"Acme 5"}, "bolt-3", nil},
	} {
		var got []string
		for _, one := range index(each.names...).Found(each.model) {
			got = append(got, one.Model)
		}
		if len(got) > 1 {
			// a map's order; lineup keeps only that all are one release
			if got[0] > got[1] {
				got[0], got[1] = got[1], got[0]
			}
		}
		if !reflect.DeepEqual(got, each.want) {
			t.Errorf("%s in %v: %v", each.model, each.names, got)
		}
	}
}
