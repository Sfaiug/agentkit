package harness

import "agentkit/internal/hookfact"

// HookFact is what this listing heard at reconciliation; an unreconciled reader reads it now.
func (reader Reader) HookFact(name string) hookfact.Fact {
	if heard := reader.own.heard; heard != nil {
		return heard(name)
	}
	return hookfact.Standing(name)
}

// hearing keeps hooks beside the harness's other evidence, before any seat is published.
func (reader Reader) hearing(name string) Reader {
	fact := reader.HookFact(name)
	reader.own.heard = func(string) hookfact.Fact { return fact }
	return reader
}
