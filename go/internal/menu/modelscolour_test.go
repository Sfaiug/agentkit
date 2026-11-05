package menu

import (
	"reflect"
	"regexp"
	"strings"
	"testing"
	"unsafe"
)

func TestLitFoldedModelWithoutEffortHasNoTrailingSpaces(t *testing.T) {
	screen := screenAt(t, "40")
	// Exercise colour without taking the developer's terminal.
	depth := reflect.ValueOf(&screen).Elem().FieldByName("depth")
	reflect.NewAt(depth.Type(), unsafe.Pointer(depth.UnsafeAddr())).Elem().SetInt(24)
	said := []Role{{Head: "orch", Lines: []Line{
		{Name: "Bolt 3", Maker: "Bolt Labs", Quality: "100.0", Cost: "$1.00", Near: 1},
		{Name: "Acme Long Context 9", Word: "high", Quality: "99.0", Cost: "$0.50", Near: .9},
	}}}
	light := ModelLight{Maker: "Bolt Labs", Colour: "#40A0E0"}
	ansi := regexp.MustCompile(`\x1b\[[0-?]*[ -/]*[@-~]`)
	for _, row := range modelsBody(screen, said, nil, 2, 0, light) {
		text := ansi.ReplaceAllString(row.line, "")
		if strings.Contains(text, "Bolt 3") {
			if text != "    Bolt 3" {
				t.Fatalf("folded name retains padding: %q", text)
			}
			if !strings.Contains(row.line, screen.Tinted("Bolt 3", light.Colour, -0.25)) {
				t.Fatalf("folded name lost its tint: %q", row.line)
			}
			return
		}
	}
	t.Fatal("model row not shown")
}
