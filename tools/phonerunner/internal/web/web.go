// Package web serves the phone page. Every route sits behind the gate, so only the
// paired phone can load anything. Watch-only: there are no routes that change state.
package web

import (
	"context"
	_ "embed"
	"encoding/json"
	"net/http"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/service"
)

//go:embed page.html
var pageHTML []byte

//go:embed app.js
var appJS []byte

// Source is what the handlers read (service.Service satisfies it).
type Source interface {
	Refresh(ctx context.Context) service.Status
	LatestShot() []byte
}

// Setting is one row of the read-only Settings view, with its (i) box text.
type Setting struct {
	Name  string `json:"name"`
	Value any    `json:"value"`
	Info  string `json:"info"`
}

// Settings lists the current settings with plain-language info boxes. Changing a
// setting needs the desk for now (the phone-side switch arrives with the passkey).
func Settings(c config.Config) []Setting {
	return []Setting{
		{"Screen text every (seconds)", c.CaptureTextSeconds, "How often the tool notes which window is in front of the PC and whether it is locked."},
		{"Screenshot every (seconds)", c.CaptureShotSeconds, "How often the tool takes a picture of the PC screen. A picture is only kept when the screen changed."},
		{"Pictures copied to the share", false, "Off until the picture filter is built (Decision 266 = A: copied only after key and patient blackout; built last). Until then pictures stay in an admin-only folder on the PC and on your phone."},
		{"Pause pictures on", len(c.DenyRules), "Number of window rules (key pages, Windows security screens, password managers, patient-mode windows, titles with a birth date or record number) that stop pictures and hide the window title while that window is in front. Only the FRONT window is checked: a key page or patient file in a side window or on a second monitor is still in the picture."},
		{"Window titles copied to the share", false, "Off: until a patient filter exists, window titles show on this page only. The status copy the PC lane takes says 'kept on the PC and phone'."},
		{"Heartbeat every (seconds)", c.HeartbeatSeconds, "How often the PC writes an 'I am alive' note, so you get an alert if the PC goes offline."},
		{"Copy-off allowed delay (seconds)", c.CopyAckMaxAgeSeconds, "If results have not been copied off the PC for longer than this, the page shows a warning and you get one alert."},
		{"Page link in phone alerts", c.NtfyClickLink, "Off: alerts carry no link, so the alert service (ntfy.sh) never learns this page's address. Turn on at the desk if you want to tap an alert to open the page."},
		{"Phone alerts", c.NtfyTopic != "", "Short alerts to your phone. The text never contains details, only 'needs you', 'done', 'locked' or 'not copying'."},
		{"Watched logs", len(c.WatchedLogs), "Text files whose last lines show on this page, with anything that looks like a key removed."},
	}
}

// Handler builds the gated router. wrap is the gate middleware.
func Handler(src Source, cfg config.Config, wrap func(http.Handler) http.Handler) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		secure(w)
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write(pageHTML)
	})
	mux.HandleFunc("GET /app.js", func(w http.ResponseWriter, r *http.Request) {
		secure(w)
		w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
		w.Write(appJS)
	})
	mux.HandleFunc("GET /api/status", func(w http.ResponseWriter, r *http.Request) {
		secure(w)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(src.Refresh(r.Context()))
	})
	mux.HandleFunc("GET /api/settings", func(w http.ResponseWriter, r *http.Request) {
		secure(w)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(Settings(cfg))
	})
	mux.HandleFunc("GET /api/shot", func(w http.ResponseWriter, r *http.Request) {
		secure(w)
		png := src.LatestShot()
		if len(png) == 0 {
			http.Error(w, "no screenshot yet", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "image/png")
		w.Write(png)
	})
	return wrap(mux)
}

func secure(w http.ResponseWriter) {
	h := w.Header()
	h.Set("Cache-Control", "no-store")
	h.Set("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("Referrer-Policy", "no-referrer")
}
