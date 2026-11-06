package config

// TOMLSet is a key a TOML document sets in its own table, with the bytes from its key to the
// end of its value.
type TOMLSet struct {
	Key        []string
	Start, End int
}

// TOMLTop is each key text sets above its first [table] header, read by the rules ReadTOML
// reads by, so a multi-line string's lines are the string's and never a key or a header.  text
// is TOML ReadTOML takes, its newlines "\n".
func TOMLTop(text string) ([]TOMLSet, error) {
	p := parser{text: text}
	var sets []TOMLSet
	for {
		// between two statements, as between two values of an array, only space and comments
		if err := p.arraySpace(); err != nil {
			return nil, err
		}
		if p.pos == len(p.text) || p.at("[") {
			return sets, nil
		}
		start := p.pos
		key, _, err := p.pair()
		if err != nil {
			return nil, err
		}
		sets = append(sets, TOMLSet{key, start, p.pos})
	}
}
