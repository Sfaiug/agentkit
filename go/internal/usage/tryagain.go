package usage

import (
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
)

var (
	tryAgainISO   = regexp.MustCompile(`(?i)try again (?:at|on)\s+(\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:?\d\d)?)`)
	tryAgainNamed = regexp.MustCompile(`(?i)try again (?:at|on)\s+([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?:\s+at)?,?\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp])?\.?[Mm]?\.?`)
	months        = []string{"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
)

// TryAgainAt is the moment a refusal named to come back at, 0 for none, Python's try_again_at: a
// clock time with no date could be minutes ago or a week off, and the meters answer that better.
func TryAgainAt(said string) float64 {
	if found := tryAgainISO.FindStringSubmatch(said); found != nil {
		spelled := strings.ToUpper(strings.Replace(found[1], " ", "T", 1))
		for _, seconds := range []string{":05", ""} {
			for _, zone := range []string{"Z07:00", "Z0700", ""} {
				if at, err := time.ParseInLocation("2006-01-02T15:04"+seconds+zone, spelled, time.Local); err == nil {
					return float64(at.UnixNano()) / 1e9
				}
			}
		}
		return 0
	}
	found := tryAgainNamed.FindStringSubmatch(said)
	if found == nil {
		return 0
	}
	month := slices.Index(months, strings.ToLower(found[1][:3])) + 1
	day, _ := strconv.Atoi(found[2])
	year, _ := strconv.Atoi(found[3])
	hour, _ := strconv.Atoi(found[4])
	minute, _ := strconv.Atoi(found[5])
	switch strings.ToLower(found[6]) {
	case "p":
		hour = hour%12 + 12
	case "a":
		hour %= 12
	}
	at := time.Date(year, time.Month(month), day, hour, minute, 0, 0, time.Local)
	if month == 0 || at.Day() != day || at.Hour() != hour || at.Minute() != minute {
		return 0 // no such moment: time.Date would have carried it over to another
	}
	return float64(at.Unix())
}
