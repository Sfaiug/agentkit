package cli

import "testing"

func TestAnEmptyHistoryNamesTheFirstGrowingSizeOtherwiseTheFirstKnown(t *testing.T) {
	value := func(n int) *int { return &n }
	for name, each := range map[string]struct {
		current, before []measure
		want            string
	}{
		"none": {nil, nil, "no loss to name, since no run ended in two weeks"},
		"new history": {[]measure{{"code lines", value(12000)}}, nil,
			"the largest loss is ak's code lines, 12,000 against not recorded the week before"},
		"first known": {[]measure{{"code lines", value(12)}}, []measure{{"code lines", value(13)}},
			"the largest loss is ak's code lines, 12 against 13 the week before"},
		"first growing": {[]measure{{"code lines", value(12)}, {"README words", value(20)}},
			[]measure{{"code lines", value(13)}, {"README words", value(10)}},
			"the largest loss is ak's README words, 20 against 10 the week before"},
	} {
		t.Run(name, func(t *testing.T) {
			b := board{sizes: [2][]measure{each.current, each.before}}
			if got := b.loss(); got != each.want {
				t.Fatal(got)
			}
		})
	}
}
