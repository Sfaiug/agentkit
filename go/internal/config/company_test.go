package config

import "testing"

func TestCompanyUsesTheHomeMappingBeforeTheShippedMapping(t *testing.T) {
	for _, each := range []struct{ own, maker, want string }{
		{"", "Acme", "acme"},
		{"", "Xiaomi", "mimo"},
		{"maker = \"Bolt Labs\"", "Bolt Labs", "acme"},
		{"maker = \"Xiaomi\"", "Xiaomi", "acme"},
		{"maker = 1", "Bolt Labs", "bolt labs"},
	} {
		t.Run(each.own+each.maker, func(t *testing.T) {
			modelsHome(t, `[models.mid]
harness = "claude"
model = "acme-mid-5"
provider = "acme"
[providers.acme]
mode = "subscription"
`+each.own+"\n")
			if got, err := Company(each.maker); err != nil || got != each.want {
				t.Fatalf("Company(%q) = %q, %v; want %q", each.maker, got, err, each.want)
			}
		})
	}
}
