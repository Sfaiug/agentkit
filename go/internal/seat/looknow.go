package seat

// LookNow has the seat this wrapper runs in looked at again now, without waiting for it, as
// watch.start_look does where its harness tells of a change its screen may not show.
func LookNow() {
	if seat, _, _, ok := paneOf(); ok {
		if look := startLook(seat, ""); look != nil {
			look.Process.Release()
		}
	}
}
