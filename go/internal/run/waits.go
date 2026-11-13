package run

// Waits is whether this ending waits for its seat's next quiet prompt and nothing has said it yet
// (handback.waits): deferred, not handed back, and its line not already in its composer.  The
// `handback_pending` mark outlives delivery, so it alone does not say an ending waits.
func Waits(record *Object) bool {
	return record.Truthy("handback_pending") && !record.Truthy("handback_typed") && !HandedBack(record)
}
