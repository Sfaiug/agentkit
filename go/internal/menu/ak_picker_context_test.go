package menu

import (
    "fmt"
    "strings"
    "testing"

    "agentkit/internal/config"
    "agentkit/internal/terminal"
)

func TestAKReviewFocusedModelIsIdentifiable(t *testing.T) {
    home := t.TempDir()
    t.Setenv("HOME", home)
    t.Setenv("USERPROFILE", home)
    t.Setenv("COLUMNS", "30")
    t.Setenv("NO_COLOR", "1")
    t.Setenv("AGENTKIT_TERMFEATURES", "")
    for _, locale := range []string{"C.UTF-8", "C"} {
        t.Setenv("LC_ALL", locale)
        for _, scenario := range []struct{ height, column int }{{10, 2}, {10, 5}, {9, 1}, {9, 4}} {
            t.Run(fmt.Sprintf("%s/%dx%d/column%d", locale, 30, scenario.height, scenario.column), func(t *testing.T) {
                t.Setenv("LINES", fmt.Sprint(scenario.height))
                draft := &Draft{
                    Orchestrator: "amber", Workers: []string{"amber", "bolt", "cobalt"},
                    Reviewers: []string{"amber", "bolt", "cobalt"}, Names: []string{"amber", "bolt", "cobalt"},
                    At: 1, Column: scenario.column, Picker: true,
                    Models: map[string]config.Model{}, Levels: map[string][]string{},
                }
                for _, name := range draft.Names {
                    draft.Models[name] = config.Model{Harness: "acme", ID: name,
                        Efforts: map[string]string{"effort": "low", "exec_effort": "high", "review_effort": "medium"}}
                    draft.Levels[name] = []string{"low", "medium", "high"}
                }
                keyboard := &terminal.Keyboard{}
                keyboard.Sense()
                before := strings.Join(draft.PickerLines(keyboard.Screen(), "14:02"), "\n")
                draft.Key(terminal.Key{Name: "down"})
                after := strings.Join(draft.PickerLines(keyboard.Screen(), "14:02"), "\n")
                if draft.At != 2 || draft.Column != scenario.column {
                    t.Fatal("down did not retain the column on the next model")
                }
                draft.Key(terminal.Key{Name: "space"})
                switch scenario.column {
                case 1:
                    if strings.Join(draft.Workers, ",") != "amber,bolt" {
                        t.Fatal("space did not unmark the new builder")
                    }
                case 2:
                    if strings.Join(draft.Reviewers, ",") != "amber,bolt" {
                        t.Fatal("space did not unmark the new reviewer")
                    }
                case 4:
                    if draft.effort("cobalt", "exec_effort") != "low" {
                        t.Fatal("space did not step the new builder's effort")
                    }
                case 5:
                    if draft.effort("cobalt", "review_effort") != "high" {
                        t.Fatal("space did not step the new reviewer's effort")
                    }
                }
                if before == after {
                    t.Fatalf("down changed the model Space edits from bolt to cobalt, with identical displays:\n%s", after)
                }
            })
        }
    }
}
