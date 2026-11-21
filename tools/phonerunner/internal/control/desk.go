package control

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Adding a passkey is a desk step. The elevated desk command and the running
// service talk through small files in a folder only SYSTEM and Administrators
// can write (private\desk), so under "Always notify" each desk step starts with
// Jake's own click on the Windows prompt:
//
//	open.json      desk -> service: open a 5-minute registration window
//	confirm.json   desk -> service: the code Jake read on his phone
//	state.json     service -> desk: the waiting code and the last result
//
// The phone's device is the paired phone from the settings; it is never typed.

// Registrar is the registration side of the approver.
type Registrar interface {
	OpenRegistration(phoneID string)
	Waiting() (string, bool)
	Confirm(code string) error
}

// DeskState is state.json.
type DeskState struct {
	At      time.Time `json:"at"`
	Open    bool      `json:"window_open"`
	Waiting string    `json:"waiting_code,omitempty"`
	Result  string    `json:"result,omitempty"`
}

// ResultStored is the success result.
const ResultStored = "PASS passkey stored"

var removeFile = os.Remove

// Desk is the service side.
type Desk struct {
	Dir   string
	Reg   Registrar
	Phone func() string // the paired phone's Tailscale device ID ("" if none)
	Log   func(string, map[string]any)
	Now   func() time.Time

	until  time.Time
	result string
}

// Poll handles any desk request and writes state.json. The service calls it
// every second.
func (d *Desk) Poll() error {
	if _, err := os.Stat(filepath.Join(d.Dir, "open.json")); err == nil {
		if err := removeFile(filepath.Join(d.Dir, "open.json")); err != nil {
			return fmt.Errorf("desk: %w", err)
		}
		if phone := d.Phone(); phone == "" {
			d.result = "FAIL no phone is paired yet; pair it first"
		} else {
			d.Reg.OpenRegistration(phone)
			d.until = d.Now().Add(5 * time.Minute)
			d.result = ""
			d.Log("passkey.window_opened", nil)
		}
	}
	if b, err := os.ReadFile(filepath.Join(d.Dir, "confirm.json")); err == nil {
		if err := removeFile(filepath.Join(d.Dir, "confirm.json")); err != nil {
			return fmt.Errorf("desk: %w", err)
		}
		var c struct {
			Code string `json:"code"`
		}
		_ = json.Unmarshal(b, &c)
		if err := d.Reg.Confirm(strings.TrimSpace(c.Code)); err != nil {
			d.result = "FAIL " + err.Error()
			d.Log("passkey.refused", map[string]any{"error": err.Error()})
		} else {
			d.result = ResultStored
			d.until = time.Time{}
			d.Log("passkey.stored", nil)
		}
	}
	st := DeskState{At: d.Now().UTC(), Open: d.Now().Before(d.until), Result: d.result}
	st.Waiting, _ = d.Reg.Waiting()
	b, _ := json.Marshal(st)
	tmp := filepath.Join(d.Dir, "state.json.tmp")
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return fmt.Errorf("desk: %w", err)
	}
	return os.Rename(tmp, filepath.Join(d.Dir, "state.json"))
}

// ErrDeskTimeout means nothing arrived in time.
var ErrDeskTimeout = errors.New("nothing arrived in time: either the phone's step failed (the page says why; run this step again to reopen the window) or the service is not running")

// AddPasskey is the desk command's side. It opens the window, waits for the
// phone's new passkey, asks Jake to type the code his phone shows, and prints
// PASS or FAIL. sleep and limit are seams for tests.
func AddPasskey(dir string, in io.Reader, out io.Writer, sleep func(time.Duration), limit int) error {
	_ = removeFile(filepath.Join(dir, "state.json"))
	if err := os.WriteFile(filepath.Join(dir, "open.json"), []byte("{}"), 0o600); err != nil {
		return fmt.Errorf("desk: %w", err)
	}
	fmt.Fprintln(out, "Registration is open for 5 minutes.")
	fmt.Fprintln(out, "On your phone: open the PhoneRunner page, tap 'Add this phone's passkey', and unlock the phone when it asks.")
	st, err := waitFor(dir, sleep, limit, func(s DeskState) bool { return s.Waiting != "" || strings.HasPrefix(s.Result, "FAIL") })
	if err != nil {
		return err
	}
	if st.Waiting == "" {
		return errors.New(strings.TrimPrefix(st.Result, "FAIL "))
	}
	fmt.Fprint(out, "Type the 8-character code your phone shows, then press Enter: ")
	code, _ := bufio.NewReader(in).ReadString('\n')
	b, _ := json.Marshal(map[string]string{"code": strings.TrimSpace(code)})
	if err := os.WriteFile(filepath.Join(dir, "confirm.json"), b, 0o600); err != nil {
		return fmt.Errorf("desk: %w", err)
	}
	st, err = waitFor(dir, sleep, limit, func(s DeskState) bool { return s.Result != "" })
	if err != nil {
		return err
	}
	if st.Result != ResultStored {
		return errors.New(strings.TrimPrefix(st.Result, "FAIL "))
	}
	fmt.Fprintln(out, ResultStored)
	return nil
}

func waitFor(dir string, sleep func(time.Duration), limit int, done func(DeskState) bool) (DeskState, error) {
	for i := 0; i < limit; i++ {
		sleep(time.Second)
		b, err := os.ReadFile(filepath.Join(dir, "state.json"))
		if err != nil {
			continue
		}
		var s DeskState
		if json.Unmarshal(b, &s) == nil && done(s) {
			return s, nil
		}
	}
	return DeskState{}, ErrDeskTimeout
}
