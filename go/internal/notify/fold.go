package notify

import (
	"strings"
	"unicode"
)

// casefold is text as Python's str.casefold() writes it, Unicode's full case folding: a rune's
// simple fold is its upper case's lower case, but for those whose fold is longer (`ß` is `ss`)
// or not lower case at all (Cherokee folds to its capitals), each kept below as Python folds it.
func casefold(text string) string {
	var out strings.Builder
	for _, r := range text {
		switch folded, long := folds[r]; {
		case long:
			out.WriteString(folded)
		case r >= 0x13a0 && r <= 0x13f5:
			out.WriteRune(r)
		case r >= 0x13f8 && r <= 0x13fd:
			out.WriteRune(r - 8)
		case r >= 0xab70 && r <= 0xabbf:
			out.WriteRune(r - 0xab70 + 0x13a0)
		default:
			out.WriteRune(unicode.ToLower(unicode.ToUpper(r)))
		}
	}
	return out.String()
}

// folds are the runes whose fold their upper case's lower case misses, from Python's own
// casefold, Cherokee's aside.
var folds = map[rune]string{
	0xdf: "\u0073\u0073", 0x130: "\u0069\u0307", 0x131: "\u0131", 0x149: "\u02bc\u006e",
	0x1f0: "\u006a\u030c", 0x390: "\u03b9\u0308\u0301", 0x3b0: "\u03c5\u0308\u0301",
	0x587: "\u0565\u0582", 0x1e96: "\u0068\u0331", 0x1e97: "\u0074\u0308", 0x1e98: "\u0077\u030a",
	0x1e99: "\u0079\u030a", 0x1e9a: "\u0061\u02be", 0x1e9e: "\u0073\u0073", 0x1f50: "\u03c5\u0313",
	0x1f52: "\u03c5\u0313\u0300", 0x1f54: "\u03c5\u0313\u0301", 0x1f56: "\u03c5\u0313\u0342",
	0x1f80: "\u1f00\u03b9", 0x1f81: "\u1f01\u03b9", 0x1f82: "\u1f02\u03b9", 0x1f83: "\u1f03\u03b9",
	0x1f84: "\u1f04\u03b9", 0x1f85: "\u1f05\u03b9", 0x1f86: "\u1f06\u03b9", 0x1f87: "\u1f07\u03b9",
	0x1f88: "\u1f00\u03b9", 0x1f89: "\u1f01\u03b9", 0x1f8a: "\u1f02\u03b9", 0x1f8b: "\u1f03\u03b9",
	0x1f8c: "\u1f04\u03b9", 0x1f8d: "\u1f05\u03b9", 0x1f8e: "\u1f06\u03b9", 0x1f8f: "\u1f07\u03b9",
	0x1f90: "\u1f20\u03b9", 0x1f91: "\u1f21\u03b9", 0x1f92: "\u1f22\u03b9", 0x1f93: "\u1f23\u03b9",
	0x1f94: "\u1f24\u03b9", 0x1f95: "\u1f25\u03b9", 0x1f96: "\u1f26\u03b9", 0x1f97: "\u1f27\u03b9",
	0x1f98: "\u1f20\u03b9", 0x1f99: "\u1f21\u03b9", 0x1f9a: "\u1f22\u03b9", 0x1f9b: "\u1f23\u03b9",
	0x1f9c: "\u1f24\u03b9", 0x1f9d: "\u1f25\u03b9", 0x1f9e: "\u1f26\u03b9", 0x1f9f: "\u1f27\u03b9",
	0x1fa0: "\u1f60\u03b9", 0x1fa1: "\u1f61\u03b9", 0x1fa2: "\u1f62\u03b9", 0x1fa3: "\u1f63\u03b9",
	0x1fa4: "\u1f64\u03b9", 0x1fa5: "\u1f65\u03b9", 0x1fa6: "\u1f66\u03b9", 0x1fa7: "\u1f67\u03b9",
	0x1fa8: "\u1f60\u03b9", 0x1fa9: "\u1f61\u03b9", 0x1faa: "\u1f62\u03b9", 0x1fab: "\u1f63\u03b9",
	0x1fac: "\u1f64\u03b9", 0x1fad: "\u1f65\u03b9", 0x1fae: "\u1f66\u03b9", 0x1faf: "\u1f67\u03b9",
	0x1fb2: "\u1f70\u03b9", 0x1fb3: "\u03b1\u03b9", 0x1fb4: "\u03ac\u03b9", 0x1fb6: "\u03b1\u0342",
	0x1fb7: "\u03b1\u0342\u03b9", 0x1fbc: "\u03b1\u03b9", 0x1fc2: "\u1f74\u03b9",
	0x1fc3: "\u03b7\u03b9", 0x1fc4: "\u03ae\u03b9", 0x1fc6: "\u03b7\u0342",
	0x1fc7: "\u03b7\u0342\u03b9", 0x1fcc: "\u03b7\u03b9", 0x1fd2: "\u03b9\u0308\u0300",
	0x1fd3: "\u03b9\u0308\u0301", 0x1fd6: "\u03b9\u0342", 0x1fd7: "\u03b9\u0308\u0342",
	0x1fe2: "\u03c5\u0308\u0300", 0x1fe3: "\u03c5\u0308\u0301", 0x1fe4: "\u03c1\u0313",
	0x1fe6: "\u03c5\u0342", 0x1fe7: "\u03c5\u0308\u0342", 0x1ff2: "\u1f7c\u03b9",
	0x1ff3: "\u03c9\u03b9", 0x1ff4: "\u03ce\u03b9", 0x1ff6: "\u03c9\u0342",
	0x1ff7: "\u03c9\u0342\u03b9", 0x1ffc: "\u03c9\u03b9", 0xfb00: "\u0066\u0066",
	0xfb01: "\u0066\u0069", 0xfb02: "\u0066\u006c", 0xfb03: "\u0066\u0066\u0069",
	0xfb04: "\u0066\u0066\u006c", 0xfb05: "\u0073\u0074", 0xfb06: "\u0073\u0074",
	0xfb13: "\u0574\u0576", 0xfb14: "\u0574\u0565", 0xfb15: "\u0574\u056b", 0xfb16: "\u057e\u0576",
	0xfb17: "\u0574\u056d",
}
