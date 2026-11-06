package cli

import (
	"context"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
	"agentkit/internal/update"
)

func menuConfigModels(keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	ticks, err := config.OpenModelTicks()
	if err != nil || len(ticks.Harnesses) == 0 {
		return false
	}
	models, err := config.Models()
	if err != nil {
		return false
	}
	catalogs := map[string][]throughChoice{}
	at, choice, top, opened, note := 0, 0, 0, false, ""
	version := update.Build()
	if version == "" {
		version = "?"
	}
	defer painter.Forget()
	for {
		rows := []menu.ModelRow{}
		cursor := at
		for i, harness := range ticks.Harnesses {
			name, colour := config.HarnessLook(harness)
			labels := []string{}
			for _, name := range ticks.Names(harness, "") {
				labels = append(labels, config.ModelName(name, models))
			}
			value := strings.Join(labels, ", ")
			if value == "" {
				value = "none"
			}
			rows = append(rows, menu.ModelRow{Name: name, Value: value, Colour: colour})
			if opened && i == at {
				cursor = len(rows) + choice
				for _, each := range catalogs[harness] {
					rows = append(rows, each.modelRow(harness, ticks))
				}
			}
		}
		frame := menu.ConfigModelsFrame(keyboard.Screen(), rows, cursor, top, time.Now().Format("15:04"), version, note)
		top = frame.Top
		painter.Write(frame.Lines, keyboard.Screen())
		key := keyboard.ReadKey()
		note = ""
		harness := ticks.Harnesses[at]
		step := 0
		switch {
		case key.Name == "again":
			painter.Forget()
		case key.Name == "eof":
			return true
		case key.Name == "esc":
			if !opened {
				return true
			}
			opened = false
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			step = -1
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			step = 1
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				step = mouse.Notches
			} else if row, _, hit := frame.Hit(mouse); hit {
				if opened && row > at && row <= at+len(catalogs[harness]) {
					choice = row - at - 1
					if mouse.Released && mouse.Button&3 == 0 {
						key.Name = "space"
						if catalogs[harness][choice].model == nil {
							key.Name = "enter" // a provider's click logs in to it
						}
					}
				} else {
					if opened && row > at {
						row -= len(catalogs[harness])
					}
					at, opened = row, false
					if mouse.Released && mouse.Button&3 == 0 {
						key.Name = "enter"
					}
				}
			}
		}
		harness = ticks.Harnesses[at]
		if step != 0 {
			if opened {
				choice = max(0, min(len(catalogs[harness])-1, choice+step))
			} else {
				at = max(0, min(len(ticks.Harnesses)-1, at+step))
			}
		}
		if key.Name == "enter" {
			if opened && catalogs[harness][choice].model != nil {
				opened = false
				continue
			}
			if opened { // a provider to log in to: its models are listed once it is
				provider := catalogs[harness][choice].provider
				verb := adapterVerbs(keyboard, painter, harness, []string{"login"}, "", provider.ID, false)
				painter.Forget()
				if verb != "" {
					note = notAdded(harness, verb, provider.Name)
					continue
				}
				delete(catalogs, harness)
			}
			if _, read := catalogs[harness]; !read {
				choices, err := modelsList(harness, keyboard, painter)
				if err == context.Canceled {
					opened = false
					continue
				}
				catalogs[harness] = choices
				if err != nil {
					note = err.Error()
				}
			}
			if len(catalogs[harness]) == 0 {
				opened = false
				if note == "" {
					note = "its catalog lists no model"
				}
				continue
			}
			if opened { // asked again after a login: the highlight stays on a choice
				choice = min(choice, len(catalogs[harness])-1)
				continue
			}
			opened, choice = true, 0
			for i, chosen := range catalogs[harness] {
				if chosen.modelRow(harness, ticks).Marked {
					choice = i
					break
				}
			}
		}
		if key.Name == "space" && opened && catalogs[harness][choice].model != nil {
			chosen := catalogs[harness][choice]
			if err := ticks.Tick(harness, chosen.model.ID, chosen.model.Label, chosen.model.Efforts, chosen.under(), seat.KeepConfigEfforts); err != nil {
				note = err.Error()
			} else {
				models, _ = config.Models()
			}
		}
	}
}
