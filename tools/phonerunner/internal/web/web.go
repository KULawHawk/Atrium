// Package web serves the phone page. Every route sits behind the gate, so only the
// paired phone can load anything.
//
// The only routes that change anything are the Run button's: a tap begins a
// passkey challenge and the phone's signed answer finishes it (package control
// does the checks), and adding a passkey while a desk-opened window is open.
// Those POST routes also require a same-origin JSON request, and the device is
// always the one the tailnet reports, never a value from the page.
package web

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/go-webauthn/webauthn/protocol"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/control"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/gate"
	"github.com/kulawhawk/atrium/tools/phonerunner/internal/service"
)

// Controls is the Run button (control.Control satisfies it).
type Controls interface {
	Items() ([]control.Card, error)
	File(itemID, rel string) (control.FileView, error)
	Run() control.RunView
	BeginTap(deviceID, itemID, action string) (*protocol.CredentialAssertion, error)
	FinishTap(deviceID string, resp *protocol.ParsedCredentialAssertionData) (control.Result, error)
}

// Passkeys is the registration side (approve.Approver satisfies it).
type Passkeys interface {
	Count() int
	BeginRegistration(deviceID string) (*protocol.CredentialCreation, error)
	FinishRegistration(deviceID string, resp *protocol.ParsedCredentialCreationData) (string, error)
}

// RiskNote is shown on the page beside the Run button and in the README.
const RiskNote = "Your PC uses \"Always notify\". It closes the known quiet routes to admin rights. Microsoft still does not treat the Windows prompt as a security wall, so a program running as you might one day find a way to admin without a prompt. If that happened, it could read the phone tool's private files and fake a tap. The tool shows every run on your phone and logs it, and it never stores your PIN. The stronger fix, agents in a separate Windows account (plan B), is parked until the suite is fully working."

// RegFailHelp follows any failed passkey registration (WIRING item 6).
const RegFailHelp = "This registration window is now used up. Run the passkey step at the desk again to reopen it, then try once more."

// MaxBody caps a POST body.
const MaxBody = 64 << 10

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
		{"Front-window check every (seconds)", c.CaptureTextSeconds, "How often the tool notes which window is in front of the PC and whether it is locked."},
		{"Screen text every (seconds)", c.ScreenTextSeconds, "How often the tool reads the words in the front window (Windows accessibility). 0 means off: it stays off until the PC test (T-10) shows it works on your PC. Paused on key, security, password and patient windows; shown on this page only, never copied to the share."},
		{"Screenshot every (seconds)", c.CaptureShotSeconds, "How often the tool takes a picture of the PC screen. A picture is only kept when the screen changed."},
		{"Pictures copied to the share", false, "Off until the picture filter is built (Decision 266 = A: copied only after key and patient blackout; built last). Until then pictures stay in an admin-only folder on the PC and on your phone."},
		{"Pause pictures on", len(c.DenyRules), "Number of window rules (key pages, Windows security screens, password managers, patient-mode windows, titles with a birth date or record number) that stop pictures and hide the window title while that window is in front. Only the FRONT window is checked: a key page or patient file in a side window or on a second monitor is still in the picture."},
		{"Window titles copied to the share", false, "Off: until a patient filter exists, window titles show on this page only. The status copy the PC lane takes says 'kept on the PC and phone'."},
		{"Heartbeat every (seconds)", c.HeartbeatSeconds, "How often the PC writes an 'I am alive' note, so you get an alert if the PC goes offline."},
		{"Copy-off allowed delay (seconds)", c.CopyAckMaxAgeSeconds, "If results have not been copied off the PC for longer than this, the page shows a warning and you get one alert."},
		{"Page link in phone alerts", c.NtfyClickLink, "Off: alerts carry no link, so the alert service (ntfy.sh) never learns this page's address. Turn on at the desk if you want to tap an alert to open the page."},
		{"Phone alerts", c.NtfyTopic != "", "Short alerts to your phone. The text never contains details, only 'needs you', 'done', 'locked' or 'not copying'."},
		{"Run button (as the running service uses it)", c.RunButton, "A change at the desk takes effect after the service restarts. Off until turned on at the desk, which first re-checks that Windows uses \"Always notify\" (T-01C). When on, each Run or Stop needs your tap and your phone unlock (a passkey), and runs only while the PC is already unlocked. " + RiskNote},
		{"Watched logs", len(c.WatchedLogs), "Text files whose last lines show on this page, with anything that looks like a key removed. Their lines are NOT copied off the PC unless that log is marked may_copy at the desk (off by default, because a log can hold patient data the key filter cannot see)."},
	}
}

// Handler builds the gated router. wrap is the gate middleware.
func Handler(src Source, cfg config.Config, ctl Controls, keys Passkeys, wrap func(http.Handler) http.Handler) http.Handler {
	mux := http.NewServeMux()
	getJSON := func(path string, f func(r *http.Request) (any, error)) {
		mux.HandleFunc("GET "+path, func(w http.ResponseWriter, r *http.Request) {
			v, err := f(r)
			reply(w, v, err)
		})
	}
	postJSON := func(path string, f func(dev string, body io.Reader) (any, error)) {
		mux.HandleFunc("POST "+path, func(w http.ResponseWriter, r *http.Request) {
			id, ok := gate.FromContext(r.Context())
			switch {
			case !ok || id.NodeID == "":
				reply(w, nil, errNoDevice)
			case r.Header.Get("Sec-Fetch-Site") != "same-origin" || r.Header.Get("Content-Type") != "application/json":
				reply(w, nil, errCrossSite)
			default:
				v, err := f(id.NodeID, http.MaxBytesReader(w, r.Body, MaxBody))
				reply(w, v, err)
			}
		})
	}
	getJSON("/api/items", func(r *http.Request) (any, error) { return ctl.Items() })
	getJSON("/api/items/{id}/file", func(r *http.Request) (any, error) {
		return ctl.File(r.PathValue("id"), r.URL.Query().Get("path"))
	})
	getJSON("/api/run", func(r *http.Request) (any, error) { return ctl.Run(), nil })
	getJSON("/api/passkey", func(r *http.Request) (any, error) {
		return map[string]any{"count": keys.Count(), "risk_note": RiskNote}, nil
	})
	postJSON("/api/tap/begin", func(dev string, body io.Reader) (any, error) {
		var q struct {
			Item   string `json:"item"`
			Action string `json:"action"`
		}
		if err := json.NewDecoder(body).Decode(&q); err != nil {
			return nil, err
		}
		return ctl.BeginTap(dev, q.Item, q.Action)
	})
	postJSON("/api/tap/finish", func(dev string, body io.Reader) (any, error) {
		resp, err := protocol.ParseCredentialRequestResponseBody(body)
		if err != nil {
			return nil, err
		}
		return ctl.FinishTap(dev, resp)
	})
	postJSON("/api/passkey/begin", func(dev string, body io.Reader) (any, error) { return keys.BeginRegistration(dev) })
	postJSON("/api/passkey/finish", func(dev string, body io.Reader) (any, error) {
		resp, err := protocol.ParseCredentialCreationResponseBody(body)
		if err != nil {
			return nil, regFail{err}
		}
		code, err := keys.FinishRegistration(dev, resp)
		if err != nil {
			return nil, regFail{err}
		}
		return map[string]string{"code": code, "next": "At the desk, type this code where the passkey step asks for it."}, nil
	})
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

var (
	errNoDevice  = errors.New("the tailnet did not name this device")
	errCrossSite = errors.New("refused: not a request from this page")
)

// regFail adds the reopen-the-window help to a failed registration.
type regFail struct{ err error }

func (r regFail) Error() string { return r.err.Error() + ". " + RegFailHelp }

// reply writes v as JSON, or {"error": ...} with status 400. Errors are the
// refusal reasons from the checks; they name no secret.
func reply(w http.ResponseWriter, v any, err error) {
	secure(w)
	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	json.NewEncoder(w).Encode(v)
}

func secure(w http.ResponseWriter) {
	h := w.Header()
	h.Set("Cache-Control", "no-store")
	h.Set("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("Referrer-Policy", "no-referrer")
}
