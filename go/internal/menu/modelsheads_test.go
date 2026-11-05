package menu

import (
	"slices"
	"strings"
	"testing"
)

func TestModelsRoleHeadsStandApartFromTheColumnHeads(t *testing.T) {
	rows := []Line{{Name: "Acme 1", Word: "high", Quality: "100.0", Cost: "$1.00", Near: 1}}
	said := []Role{{Head: "orch", Lines: rows}, {Head: "builds", Lines: rows}, {Head: "reviews", Lines: rows}}
	for _, width := range []string{"40", "80", "100"} {
		t.Run(width, func(t *testing.T) {
			lines := ModelsBody(screenAt(t, width), said, nil, 1, 0)
			for _, role := range said {
				if !slices.Contains(lines, "  "+role.Head) {
					t.Errorf("role %q has no heading of its own: %q", role.Head, lines)
				}
			}
			heads := 0
			for _, line := range lines {
				if strings.Contains(line, "quality") {
					heads++
					if !strings.HasPrefix(strings.TrimSpace(line), "quality") {
						t.Errorf("column heads include a role: %q", line)
					}
				}
			}
			if heads != 1 {
				t.Errorf("column heads appear %d times", heads)
			}
		})
	}
}
