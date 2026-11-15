package adapters

// Refused is matrix.Refused, which matrix supplies: it reads the harness catalogs through packages
// that import this one.  Until then the model list turns nothing off.
var Refused = func(name string) error { return nil }
