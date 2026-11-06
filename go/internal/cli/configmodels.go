package cli

import (
	"context"
	"strings"
	"time"

	"agentkit/internal/config"
	modelListing "agentkit/internal/listing"
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
	catalogs := map[string][]modelListing.Choice{}
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
				for _, model := range catalogs[harness] {
					rows = append(rows, menu.ModelRow{Name: model.Label, Choice: true, Marked: len(ticks.Names(harness, model.ID)) > 0})
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
			if opened {
				opened = false
				continue
			}
			providers, err := config.Section(harness, "providers")
			if err != nil {
				return false
			}
			if _, hosts := providers["label"].(string); hosts {
				return false // provider login choices still need Python before any model is saved
			}
			if _, read := catalogs[harness]; !read {
				choices, err := waitConfigCatalog(harness, "config · models", nil, keyboard, painter)
				if err == context.Canceled {
					continue
				}
				catalogs[harness] = choices
				if err != nil {
					note = err.Error()
				}
			}
			if len(catalogs[harness]) == 0 {
				if note == "" {
					note = "its catalog lists no model"
				}
				continue
			}
			opened, choice = true, 0
			for i, model := range catalogs[harness] {
				if len(ticks.Names(harness, model.ID)) > 0 {
					choice = i
					break
				}
			}
		}
		if key.Name == "space" && opened {
			model := catalogs[harness][choice]
			if err := ticks.Tick(harness, model.ID, model.Label, model.Efforts, seat.KeepConfigEfforts); err != nil {
				note = err.Error()
			} else {
				models, _ = config.Models()
			}
		}
	}
}
