package launch

// unreviewed is what the preflight of a review with review off says it delivers, Python's
// preflight: the pull request at that head lands on its checks, as a seat's own would after its
// review, and its ending is told as a task run's is.
func unreviewed(url, head, seated string) (merge, delivery, notification string) {
	return "squash", url + " at " + head + "; no review; land on its checks", notified(seated)
}
