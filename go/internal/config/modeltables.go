package config

import (
	"fmt"
	"slices"
)

// A Listed provider is one a host harness can log in to (config.listed_providers): its id, its name,
// and how it is paid while logged in, `subscription`, `free` or `payg`, else "".
type Listed struct{ ID, Name, Mode string }

// keepTable keeps a copy of a provider's table for a model of it coming back on Models
// (menu.models_page's `tables`), unless the page keeps one already or the config has none: as the
// page opened, else as it first took a model of it in or out.  A copy, so no change made to the
// config since reaches it, nor a load dropping a bare free provider another page put in.
func (t *ModelTicks) keepTable(provider string, entry *table) {
	if _, kept := t.tables[provider]; !kept && entry != nil {
		t.tables[provider] = copied(entry).(*table)
	}
}

// tableBack puts a fresh copy of the provider's kept table where the config has none.
func (t *ModelTicks) tableBack(providers *table, provider string) error {
	if providers.get(provider) != nil {
		return nil
	}
	kept, ok := t.tables[provider]
	if !ok { // a model names it, but this page never saw its table: nothing here says what it was
		return fmt.Errorf("[providers.%s] is no longer in the config; open Models again", provider)
	}
	providers.put(provider, copied(kept))
	return nil
}

// copied is value with each table and list in it one of its own.
func copied(value any) any {
	switch value := value.(type) {
	case *table:
		fresh := newTable()
		for _, key := range present(value) {
			fresh.put(key, copied(value.values[key]))
		}
		return fresh
	case tableArray:
		rows := make(tableArray, len(value))
		for i, row := range value {
			rows[i] = copied(row).(*table)
		}
		return rows
	case []any:
		items := slices.Clone(value)
		for i, item := range items {
			items[i] = copied(item)
		}
		return items
	}
	return value
}
