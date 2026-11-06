package config

import (
	"bytes"
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"
)

func TestMultipleModelTicksKeepPreExistingReferencesThroughEveryRemoval(t *testing.T) {
	for _, order := range [][]int{{0, 1, 0, 1}, {0, 1, 1, 0}, {0, 1, 0, 0, 1, 0}} {
		t.Run(fmt.Sprint(order), func(t *testing.T) {
			before := "# original bytes\n[defaults]\nworkers=['one','two']\nreviewers=['one','three']\n" +
				strings.Replace(tickModels, "mode = 'subscription'", "mode = 'subscription'\nusage_model = 'two'", 1)
			path := rememberIn(t, before)
			ticks, err := OpenModelTicks()
			if err != nil {
				t.Fatal(err)
			}
			original, _ := parseDocument(before)
			for _, index := range order {
				if err := ticks.Tick("acme", []string{"m1", "m2"}[index], []string{"Two", "Three"}[index], []string{"low", "high"}, nil, noKeep); err != nil {
					t.Fatal(err)
				}
				data, _ := os.ReadFile(path)
				root, _ := parseDocument(string(data))
				for _, key := range []string{"defaults", "providers"} {
					if !reflect.DeepEqual(plain(root.get(key)), plain(original.get(key))) {
						t.Fatalf("%s changed while toggling models: %s", key, data)
					}
				}
			}
			if data, _ := os.ReadFile(path); !bytes.Equal(data, []byte(before)) {
				t.Fatalf("multiple toggles lost original bytes: %s", data)
			}
		})
	}
}
