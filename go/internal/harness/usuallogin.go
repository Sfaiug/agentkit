package harness

// UsualLoginOnly is whether Go opens that harness's seats on its usual login alone: a seat on a
// login its provider lists by name is then its Python adapter's to make, as a Codex account's own
// home is codex.sh's (codexInteractive declines it).
func UsualLoginOnly(name string) bool {
	return plugins[name].usual
}
