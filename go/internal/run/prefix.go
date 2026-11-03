package run

// DecodeAt reads the JSON value starting at the byte at, and leaves what follows it, as Python's
// raw_decode: a page's script data holds its records among much else.
func DecodeAt(data []byte, at int) (any, error) {
	return (&parser{data: data, at: at}).value(0)
}
