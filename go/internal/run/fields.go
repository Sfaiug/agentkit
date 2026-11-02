package run

// SetAll sets each key and value of pairs on the record in turn, and is the record.
func SetAll(record *Object, pairs ...any) *Object {
	for i := 0; i < len(pairs); i += 2 {
		record.Set(pairs[i].(string), pairs[i+1])
	}
	return record
}

// Fields is a new object of those keys and values, in that order.
func Fields(pairs ...any) *Object {
	return SetAll(NewObject(), pairs...)
}
