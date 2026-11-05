package listing

import (
	"reflect"
	"testing"
)

func TestChoicesKeepAdapterLabelsAndEffortsAndManifestFallbacks(t *testing.T) {
	adapter(t, `printf 'acme-1\tAcme One\tlow high\nacme-2\tAcme Two\t\nacme-1\tAgain\tmax\n'`, "[effort]\nlevels=['medium','high','max']\n")
	choices, err := Choices("acme")
	want := []Choice{{"acme-1", "Acme One", []string{"low", "high"}}, {"acme-2", "Acme Two", []string{"medium", "high", "max"}}}
	if err != nil || !reflect.DeepEqual(choices, want) {
		t.Fatalf("%+v, %v", choices, err)
	}
	adapter(t, "exit 1", "[catalog]\nacme-3={label='Acme Three',efforts=['low','high']}\n")
	choices, err = Choices("acme")
	want = []Choice{{"acme-3", "Acme Three", []string{"low", "high"}}}
	if err != nil || !reflect.DeepEqual(choices, want) {
		t.Fatalf("manifest fallback: %+v, %v", choices, err)
	}
}
