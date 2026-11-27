package seat

import (
	"slices"
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

// Each want is what agentkit/statusbar.py and menu.last_column write for the same seat, so a bar
// reads the same whichever program wrote it last.

func TestTheBarsFormatsAreStatusbarsOwn(t *testing.T) {
	need := "#{?#{@ak_news},#{@ak_need_lit},#{@ak_need}}"
	fold := "#{?#{@ak_news},#{@ak_fold_lit},#{@ak_fold}}"
	one := "#{?#{e|<=:#{e|+:#{w:@ak_top},#{e|+:#{w:@ak_need},2}},#{client_width}},#[align=left]#{@ak_top} #[align=right]" + need + ",#{?#{e|<=:#{e|+:#{w:@ak_top1},#{e|+:#{w:@ak_need},2}},#{client_width}},#[align=left]#{@ak_top1} #[align=right]" + need + ",#{?#{e|<=:#{e|+:#{w:@ak_top2},#{e|+:#{w:@ak_need},2}},#{client_width}},#[align=left]#{@ak_top2} #[align=right]" + need + ",#{?#{e|<=:#{e|+:#{w:@ak_top},#{e|+:#{w:@ak_fold},2}},#{client_width}},#[align=left]#{@ak_top} #[align=right]" + fold + ",#{?#{e|<=:#{e|+:#{w:@ak_top1},#{e|+:#{w:@ak_fold},2}},#{client_width}},#[align=left]#{@ak_top1} #[align=right]" + fold + ",#{?#{e|<=:#{e|+:#{w:@ak_top2},#{e|+:#{w:@ak_fold},2}},#{client_width}},#[align=left]#{@ak_top2} #[align=right]" + fold + ",#[align=left]#{?#{e|>:#{e|-:#{client_width},#{e|+:#{w:@ak_fold},2}},0},#{=/#{e|-:#{client_width},#{e|+:#{w:@ak_fold},2}}/…:@ak_top2}#[default],} #[align=right]" + fold + "}}}}}}"
	two := "#[align=left]#{?#{e|<=:#{w:@ak_why},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why},#{?#{e|<:#{e|+:#{w:@ak_why1},3},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{?#{e|>:#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}},0},#{=/#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}/…:@ak_why}#[default],},#{?#{e|<=:#{w:@ak_why1},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why1},#{?#{e|<=:#{w:@ak_why2},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why2},#{?#{e|<:#{e|+:#{w:@ak_why3},3},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{?#{e|>:#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}},0},#{=/#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}/…:@ak_why2}#[default],},#{?#{e|<=:#{w:@ak_why3},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why3},#{?#{e|<=:#{w:@ak_why4},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why4},#{?#{e|<:#{e|+:#{w:@ak_why5},3},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{?#{e|>:#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}},0},#{=/#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}/…:@ak_why4}#[default],},#{?#{e|<=:#{w:@ak_why5},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why5},#{?#{e|>:#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}},0},#{=/#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}/…:@ak_why5}#[default],}}}}}}}}}} #[align=right]#{@ak_key}"
	if got := barLineOne(); got != one {
		t.Fatalf("line one:\n%s", got)
	}
	if got := barLineTwo(); got != two {
		t.Fatalf("line two:\n%s", got)
	}
}

func TestTheBarSaysWhatStatusbarSays(t *testing.T) {
	t.Setenv("LC_ALL", "C.UTF-8")
	sandbox(t) // the shades kept are the home's: none, black's
	screen := terminal.For(nil)
	needs := " #[fg=#000000,bg=#d79200,bold] ! needs you #[default]   #[bold]acme#[nobold]   #[fg=#acb4bd]Opus 5.5#[default]   "
	done := " #[fg=#000000,bg=#33b65f] ✓ done #[default]   #[bold]acme#[nobold]   #[fg=#acb4bd]Opus 5.5#[default]   "
	idle := " #[fg=#000000,bg=#868d97] ○ idle #[default]   #[bold]acme#[nobold]   #[fg=#acb4bd]Opus 5.5#[default]"
	crew := "  #[fg=#acb4bd]build: Opus 5.5, Astra   review: Opus 5.5, Spark#[default]"
	// line two with no task in flight: the crew, and those squares alone, nothing
	for _, each := range []struct {
		word, reason string
		why          [2]string
		done, total  int
		tops         [3]string
	}{
		{"needs you", "session #1 closed", [2]string{"  session ##1 closed", "  session ##1 closed"}, 1, 3, [3]string{
			needs + "#[fg=#d79200]━━━━━━━━━╸#[fg=#3a3f46]───────────────────#[default] #[fg=#acb4bd]1 of 3#[default]",
			needs + "#[fg=#d79200]━━━━━╸#[fg=#3a3f46]───────────#[default] #[fg=#acb4bd]1 of 3#[default]",
			needs + "#[fg=#d79200]━╸#[fg=#3a3f46]───#[default] #[fg=#acb4bd]1 of 3#[default]"}},
		{"done", "it shipped", [2]string{crew, ""}, 3, 3, [3]string{
			done + "#[fg=#33b65f]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━#[default] #[fg=#acb4bd]3 of 3#[default]",
			done + "#[fg=#33b65f]━━━━━━━━━━━━━━━━━#[default] #[fg=#acb4bd]3 of 3#[default]",
			done + "#[fg=#33b65f]━━━━━#[default] #[fg=#acb4bd]3 of 3#[default]"}},
		{"idle", "session closed: press 1 to reopen", [2]string{crew, ""}, 1, 3, [3]string{idle, idle, idle}},
	} {
		seat := Seat{Name: "acme", Word: each.word, reason: each.reason}
		told := map[string]string{}
		for _, option := range seat.barOptions(screen, "Opus 5.5", []string{"Opus 5.5", "Astra"}, []string{"Opus 5.5", "Spark"}, each.done, each.total) {
			if option[0] != "=acme:" {
				t.Fatalf("%s told %s", each.word, option[0])
			}
			told[option[1]] = option[2]
		}
		for i, option := range barTops {
			if told[option] != each.tops[i] {
				t.Errorf("%s %s:\n%s\nwant\n%s", each.word, option, told[option], each.tops[i])
			}
		}
		for i, option := range barWhys {
			if told[option] != each.why[i%2] {
				t.Errorf("%s %s: %q", each.word, option, told[option])
			}
		}
		if told[barKey] != "#[fg=#868d97]Ctrl-b m#[fg=#acb4bd]  menu #[default]" || told["set-titles-string"] != "acme · "+each.word {
			t.Errorf("%s: key %q, title %q", each.word, told[barKey], told["set-titles-string"])
		}
		// on the terminal's own colours, and tmux's own selection in the shades
		for option, want := range map[string]string{"status-style": "default", "mode-style": "fg=#e2e8ef,bg=#08305d",
			"message-style": "default", "message-command-style": "default"} {
			if told[option] != want {
				t.Errorf("%s %s: %q", each.word, option, told[option])
			}
		}
	}
	seat := Seat{Name: "a#b%", Word: "idle"}
	options := seat.barOptions(screen, "", nil, nil, 0, 0)
	if last := options[len(options)-1]; last != [3]string{"=a#b%:", "set-titles-string", "a##b%% · idle"} {
		t.Errorf("the title is told last, as tmux reads it: %q", last)
	}
}

// Line two opens with each task in flight as menu.squares draws it, then the crew, then those
// squares alone; again with them cut to six, then to one and the count of the rest.
func TestLineTwoDrawsTheTasksFirst(t *testing.T) {
	t.Setenv("LC_ALL", "C.UTF-8")
	sandbox(t) // the shades kept are the home's: none, black's
	var mine []ran
	for _, task := range append([]Task{{Stage: 0, Moving: true}, {Stage: 1}}, slices.Repeat([]Task{{Stage: 2}}, 6)...) {
		mine = append(mine, ran{view: &runView{task: &task}})
	}
	building, reviewing := "#[fg=#4da3ff]■#[default]#[fg=#868d97]□□#[default]", "#[fg=#868d97]■■#[default]#[fg=#868d97]□#[default]"
	landing, crew := "  #[fg=#868d97]■■■#[default]", "   #[fg=#acb4bd]build: Opus 5.5, Astra   review: Opus 5.5, Spark#[default]"
	every := building + "  " + reviewing + strings.Repeat(landing, 6)
	six := building + "  " + reviewing + strings.Repeat(landing, 4) + "  #[fg=#868d97]+2#[default]"
	one := building + "  #[fg=#868d97]+7#[default]"
	told := map[string]string{}
	seat := Seat{Name: "acme", Word: "working", mine: mine}
	for _, option := range seat.barOptions(terminal.For(nil), "", []string{"Opus 5.5", "Astra"}, []string{"Opus 5.5", "Spark"}, 0, 0) {
		told[option[1]] = option[2]
	}
	for i, want := range []string{every + crew, every, six + crew, six, one + crew, one} {
		if told[barWhys[i]] != "  "+want {
			t.Errorf("%s:\n%s\nwant\n  %s", barWhys[i], told[barWhys[i]], want)
		}
	}
}

func TestTheRightEndCountsTheOtherSeatsThatNeedYou(t *testing.T) {
	sandbox(t) // the shades kept are the home's: none, black's
	hit := "#{?#{&&:#{e|>:#{e|-:#{client_width},#{mouse_x}},1},#{e|<=:#{e|-:#{client_width},#{mouse_x}},25}},$1,}"
	one := []barRow{{id: "$1", name: "a", word: "needs you"}, {id: "$2", name: "b", word: "idle"}}
	said, short, saidLit, shortLit, found := barOthers(one, "b")
	if said != "#[range=right]#[fg=#d79200,bold]! 1 other seat needs you#[default]#[norange] " ||
		short != "#[range=right]#[fg=#d79200,bold]! 1 needs you#[default]#[norange] " ||
		saidLit != "#[range=right]#[fg=#dcbd78,bold]! 1 other seat needs you#[default]#[norange] " ||
		shortLit != "#[range=right]#[fg=#dcbd78,bold]! 1 needs you#[default]#[norange] " || found != hit {
		t.Errorf("%q %q %q %q %q", said, short, saidLit, shortLit, found)
	}
	said, short, saidLit, shortLit, found = barOthers(append(one, barRow{id: "$3", name: "c", word: "needs you"}), "b")
	if said != "#[range=right]#[fg=#d79200,bold]! 2 other seats need you#[default]#[norange] " ||
		short != "#[range=right]#[fg=#d79200,bold]! 2 need you#[default]#[norange] " ||
		saidLit != "#[range=right]#[fg=#dcbd78,bold]! 2 other seats need you#[default]#[norange] " ||
		shortLit != "#[range=right]#[fg=#dcbd78,bold]! 2 need you#[default]#[norange] " || found != hit {
		t.Errorf("%q %q %q %q %q", said, short, saidLit, shortLit, found)
	}
	if said, short, saidLit, shortLit, found := barOthers(one, "a"); said != "" || short != "" || saidLit != "" || shortLit != "" || found != "" {
		t.Errorf("a seat counts itself: %q %q %q %q %q", said, short, saidLit, shortLit, found)
	}
}
