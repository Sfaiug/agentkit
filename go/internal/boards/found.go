package boards

import (
	"regexp"
	"strings"
)

var bracketed = regexp.MustCompile(`\([^()]*\)`)

// normal is a model's name as every board and config spells it alike: its letters and digits.
func normal(text string) string {
	text = text[strings.LastIndexByte(text, '/')+1:]
	return strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, strings.ToLower(text))
}

// A Hit is one name a release goes by on a board.
type Hit struct {
	Model   string
	Release *Release
}

// An Index is each release under every name it goes by, what Found reads.
type Index map[string][]Hit

func allDigits(text string) bool {
	return text != "" && strings.Trim(text, "0123456789") == ""
}

// Found is a board's hits for one model: under its exact name, else under a board's name naming no
// version of its own that model extends with one (`Acme Pro` for `acme-pro-1.0`, never `Acme 5`
// for `acme-5-5`), else under the one board name that is model with a qualifier in brackets
// (`Acme 5 (Default Fallback)`; two such names stand for nothing), else under each board name that
// adds a version or date to a model naming none (`Acme Flash 1017` for `acme-flash`, lineup taking
// only one release), else the same matches without a trailing `-free` pricing tier.
func (index Index) Found(model string) []Hit {
	wanted := normal(model)
	if hits, ok := index[wanted]; ok {
		return hits
	}
	longest, stemmed := "", false
	for stem := range index {
		if stem != "" && !allDigits(stem[len(stem)-1:]) && strings.HasPrefix(wanted, stem) && allDigits(wanted[len(stem):]) &&
			(!stemmed || len(stem) > len(longest)) {
			longest, stemmed = stem, true
		}
	}
	if stemmed {
		return index[longest]
	}
	var qualified []string
	for stem, hits := range index {
		if normal(bracketed.ReplaceAllString(hits[0].Model, "")) == wanted {
			qualified = append(qualified, stem)
		}
	}
	if len(qualified) == 1 {
		return index[qualified[0]]
	}
	var extended []Hit
	if wanted == "" || !allDigits(wanted[len(wanted)-1:]) {
		for stem, hits := range index {
			if strings.HasPrefix(stem, wanted) && allDigits(stem[len(wanted):]) {
				extended = append(extended, hits...)
			}
		}
	}
	if len(extended) > 0 {
		return extended
	}
	if bare, free := strings.CutSuffix(model, "-free"); free {
		// Free is a pricing tier, so use the underlying model's board rows.
		return index.Found(bare)
	}
	return nil
}

// IndexOf is the Index of releases.
func IndexOf(releases []*Release) Index {
	index := Index{}
	for _, release := range releases {
		// the name first: Found reads the first hit's for a bracketed qualifier; either may lack
		name, _ := release.Name.(string)
		for _, each := range []string{name, release.Slug} {
			if each != "" {
				index[normal(each)] = append(index[normal(each)], Hit{each, release})
			}
		}
	}
	return index
}
