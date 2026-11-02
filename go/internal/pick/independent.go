package pick

// Independent is the first reviewer with room who is not the writer's own model, by the place in
// the owner's order beside that writer, then pick order; "" where there is none.
func (r *Rules) Independent(room Room, writer string) string {
	best, found := 2, "" // 2: the writer's own model, which takes nothing over
	for _, name := range r.Order(room, true, nil) {
		if tier := r.tier(writer, name); tier < best {
			best, found = tier, name
		}
	}
	return found
}
