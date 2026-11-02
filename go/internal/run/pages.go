package run

import (
	"errors"
	"unicode/utf8"
)

// Pages reads what `gh api --paginate` prints, consecutive JSON documents, as Python's
// config.json_pages does: a list of them. It is only read, so a lone surrogate is U+FFFD.
func Pages(data []byte) (any, error) {
	if !utf8.Valid(data) {
		return nil, errors.New("not UTF-8")
	}
	p := &parser{data: data, shown: true}
	var pages []any
	for p.space(); p.at < len(p.data); p.space() {
		page, err := p.value(0)
		if err != nil {
			return nil, err
		}
		pages = append(pages, page)
	}
	if pages == nil {
		return nil, errors.New("gh printed no JSON pages")
	}
	return pages, nil
}
