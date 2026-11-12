package machines

// Serves is whether m may take new work: a rental only while the tick last found it ready and ak
// may rent; one that keeps its route for the work it holds takes none (google_cloud.not_serving).
func (m Machine) Serves() bool { return m.until != 0 || !m.Rented() }
