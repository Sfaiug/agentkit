package cli

import (
	"fmt"
	"io"
	"math/rand/v2"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// characters are what a seat nobody named is called until its orchestrator names it for its job
// (orch.CHARACTERS): one word each, so the menu reads names rather than `new-35`.
var characters = strings.Fields(`
	ahsoka anakin skywalker kenobi yoda windu plo fisto luminara barriss aayla shaak quinlan
	mundi koth gallia piell ropal sinube nahdar vebb jocasta huyang katooni petro zatt ganodi
	byph gungi kalifa jinx tiplar tiplee krell
	rex cody wolffe gregor fives echo hevy cutup droidbait jesse kix hardcase tup dogma appo
	waxer boil bly gree ponds thire fox denal sinker boost comet colt slick keeli hunter
	wrecker crosshair tech nala lama taun
	dooku sidious palpatine ventress asajj maul savage opress talzin feral viscus daka karis
	grievous gunray nute tambor poggle durd lok kalani trench tuuk whorm loathsom sobeck
	tamson riff karina
	padme amidala bail organa mothma chuchi riyo onaconda farr clovis rush deechi burtoni
	amedda lott dod tarkin yularen argyus ackbar nossor tandin
	satine korkie almec vizsla kryze bokatan rook kast saxon gar
	steela gerrera saw lux bonteri mina dendup rash cham syndulla numa gobi binks tarpals
	lyonie tarfful chewbacca garnac dar smug
	bane embo aurra bossk latts dengar highsinger robonino sugi seripas rumi moralo derrown castas
	shahan twazzi todo boba hondo gwarm pilf mukmuk falso
	jabba ziro rotta arok oruba marlo snootles miraj scintel agruss atai
	lawquane suu jek shaeeah zillo sionver boll gascon meebur wac artoo threepio letta jackar
	cassie cryar trace rafa martez`)

var workerSeparators = regexp.MustCompile(`[\s,]+`)

// askName is Python's ask_name for a seat `ak orch` was given no name for: the name typed, "" for
// one left to ak.  False with the code to exit on where Esc goes back or only Python's listing can
// say whether a name is free.
func askName(out, errOut io.Writer) (name string, ok bool, code int) {
	names := seat.ReadNames()
	for {
		raw := terminal.Answer(out, "Name (Enter: auto): ")
		switch {
		case raw == terminal.Esc:
			return "", false, 0
		case terminal.Sequence(raw):
			continue
		case raw == "":
			return "", true, 0
		}
		name = config.SessionName(raw)
		if name == "" {
			fmt.Fprintln(out, "a session needs a name")
			continue
		}
		taken, known := names.Taken(name)
		if !known {
			return "", false, notImplemented(errOut, "orch")
		}
		if !taken {
			return name, true, 0
		}
		fmt.Fprintf(out, "a session named %s is already there; pick another name\n", name)
	}
}

// characterName is a name for a seat nobody named, read as its name is chosen, for the question
// may have waited: a character no seat or rename has, at random; with none free `unnamed`, numbered
// as a name a seat holds is.  A name only Python's listing could call free is passed over.
func characterName(taken func(string) (bool, bool)) string {
	free := func(name string) bool {
		held, known := taken(name)
		return known && !held
	}
	if open := slices.DeleteFunc(slices.Clone(characters), func(name string) bool { return !free(name) }); len(open) > 0 {
		return open[rand.IntN(len(open))]
	}
	name := "unnamed"
	for number := 2; !free(name); number++ {
		name = fmt.Sprintf("unnamed-%d", number)
	}
	return name
}

// askWorkers is Python's prompt_workers: the models named or numbered, Enter and the end of input
// taking [defaults]' workers.  False where Esc goes back.
func askWorkers(out io.Writer) ([]string, bool, error) {
	names, err := config.Offered()
	if err != nil {
		return nil, false, err
	}
	workers, _, err := config.Groups()
	if err != nil {
		return nil, false, err
	}
	room := terminal.For(out).Width()
	choices := terminal.ChoiceLines(names, room)
	shown := terminal.PromptLines("Workers ["+strings.Join(workers, " ")+"]: ", room)
	fmt.Fprintln(out)
	for {
		for _, line := range choices {
			fmt.Fprintln(out, "  "+terminal.Dim(out, line))
		}
		for _, line := range shown[:len(shown)-1] {
			fmt.Fprintln(out, line)
		}
		answer := terminal.Answer(out, shown[len(shown)-1])
		switch {
		case answer == terminal.Esc:
			return nil, false, nil
		case answer == "":
			return workers, true, nil
		case terminal.Sequence(answer):
			continue
		}
		if crew := workersNamed(answer, names); crew != nil {
			return crew, true, nil
		}
		fmt.Fprintln(out, terminal.Dim(out, "not a choice: "+commandhelp.Quote(answer)))
	}
}

// workersNamed is an answer to the workers question as the models it names, nil for one it cannot
// read: `all`, or numbers and names apart by spaces or commas, none twice.
func workersNamed(answer string, names []string) []string {
	if strings.EqualFold(answer, "all") {
		return slices.Clone(names)
	}
	var crew []string
	for _, part := range workerSeparators.Split(answer, -1) {
		if part == "" {
			continue
		}
		name := ""
		if number, err := strconv.Atoi(part); err == nil && part[0] != '+' && part[0] != '-' && 1 <= number && number <= len(names) {
			name = names[number-1]
		} else {
			matches := slices.DeleteFunc(slices.Clone(names), func(each string) bool { return !strings.EqualFold(each, part) })
			if len(matches) != 1 {
				return nil
			}
			name = matches[0]
		}
		if slices.Contains(crew, name) {
			return nil
		}
		crew = append(crew, name)
	}
	return crew
}
