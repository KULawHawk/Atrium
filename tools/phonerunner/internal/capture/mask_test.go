package capture

import (
	"bytes"
	"context"
	"errors"
	"image"
	"image/color"
	"image/png"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
)

var patient = Window{Title: "Conclave Workbench (patient run)", Exe: `C:\Apps\workbench.exe`, PID: 42}

// maskFake is a capturer that also lists windows and returns a raw screen image.
type maskFake struct {
	fake
	mu2     sync.Mutex
	lists   [][]VisibleWindow // returned in turn; the last one repeats
	listErr error
	calls   int
	origin  image.Point
	size    image.Point
	shots   int
	// layouts, when set, are returned in turn by Layout (the last one repeats);
	// otherwise the layout matches the screen image.
	layouts   []Layout
	layCalls  int
	afterShot *Window // front window once the picture is taken
}

func (m *maskFake) Layout() (Layout, error) {
	m.mu2.Lock()
	defer m.mu2.Unlock()
	if len(m.layouts) == 0 {
		return Layout{Rect: image.Rectangle{Min: m.origin, Max: m.origin.Add(m.size)}, Monitors: 1}, nil
	}
	i := m.layCalls
	if i >= len(m.layouts) {
		i = len(m.layouts) - 1
	}
	m.layCalls++
	return m.layouts[i], nil
}

func (m *maskFake) VisibleWindows() ([]VisibleWindow, error) {
	m.mu2.Lock()
	defer m.mu2.Unlock()
	if m.listErr != nil {
		return nil, m.listErr
	}
	i := m.calls
	if i >= len(m.lists) {
		i = len(m.lists) - 1
	}
	m.calls++
	return m.lists[i], nil
}

func (m *maskFake) ScreenImage() (*image.RGBA, image.Point, error) {
	m.mu2.Lock()
	m.shots++
	after := m.afterShot
	m.mu2.Unlock()
	if after != nil {
		m.fake.mu.Lock()
		m.fake.w = *after
		m.fake.mu.Unlock()
	}
	img := image.NewRGBA(image.Rectangle{Max: m.size})
	for i := range img.Pix {
		img.Pix[i] = 0xc8 // light grey everywhere: "content"
	}
	return img, m.origin, nil
}

func vw(w Window, h uintptr, r image.Rectangle, sure bool) VisibleWindow {
	return VisibleWindow{Window: w, Handle: h, Rect: r, Sure: sure}
}

func TestMaskPlan(t *testing.T) {
	rules := config.DefaultDenyRules()
	shell := Window{Title: "Windows PowerShell", Exe: "powershell.exe", PID: 7}
	dialog := Window{Title: "Open", Exe: `C:\Apps\workbench.exe`, PID: 42} // the Workbench's own file dialog
	ws := []VisibleWindow{
		vw(shell, 1, image.Rect(0, 0, 800, 600), true),
		vw(dialog, 2, image.Rect(900, 100, 1300, 400), true),
		vw(patient, 3, image.Rect(-1920, 0, 0, 1080), true), // on a monitor left of the main one
	}
	rects, n, pause := MaskPlan(ws, rules)
	if pause != "" || n != 2 || len(rects) != 2 {
		t.Fatalf("plan: %v %d %q", rects, n, pause)
	}
	if rects[0] != image.Rect(900-MaskMargin, 100-MaskMargin, 1300+MaskMargin, 400+MaskMargin) {
		t.Errorf("dialog of the patient program not blacked out with margin: %v", rects[0])
	}
	if rects[1] != image.Rect(-1920-MaskMargin, -MaskMargin, MaskMargin, 1080+MaskMargin) {
		t.Errorf("patient window rect: %v", rects[1])
	}
	// Uncertain position of a window to black out: pause the whole picture.
	ws[2].Sure = false
	if _, _, pause := MaskPlan(ws, rules); !strings.HasPrefix(pause, "paused: patient-mode window") {
		t.Errorf("uncertain patient window did not pause: %q", pause)
	}
	// Uncertain position of a harmless window does not matter.
	ws[2].Sure, ws[0].Sure = true, false
	if _, _, pause := MaskPlan(ws, rules); pause != "" {
		t.Errorf("uncertain harmless window paused: %q", pause)
	}
	// An empty rectangle for a window to black out is not trusted either.
	if _, _, pause := MaskPlan([]VisibleWindow{vw(patient, 3, image.Rectangle{}, true)}, rules); pause == "" {
		t.Error("empty patient rect did not pause")
	}
	if rects, n, pause := MaskPlan([]VisibleWindow{vw(shell, 1, image.Rect(0, 0, 10, 10), true)}, rules); len(rects) != 0 || n != 0 || pause != "" {
		t.Error("nothing to black out expected")
	}
}

// Layouts: one monitor; a second monitor to the LEFT (negative origin); one ABOVE;
// a window spanning two monitors; a window partly off every screen.
func TestBlackOutLayouts(t *testing.T) {
	cases := []struct {
		name   string
		origin image.Point
		size   image.Point
		win    image.Rectangle
	}{
		{"single monitor", image.Pt(0, 0), image.Pt(1920, 1080), image.Rect(100, 100, 700, 500)},
		{"monitor on the left", image.Pt(-2560, 0), image.Pt(2560+1920, 1440), image.Rect(-2000, 200, -1000, 900)},
		{"monitor above", image.Pt(0, -1200), image.Pt(1920, 1200+1080), image.Rect(300, -900, 1500, -100)},
		{"spanning two monitors", image.Pt(-1920, 0), image.Pt(3840, 1080), image.Rect(-400, 50, 600, 900)},
		{"partly off screen", image.Pt(0, 0), image.Pt(1920, 1080), image.Rect(1700, 900, 2500, 1500)},
	}
	for _, c := range cases {
		img := image.NewRGBA(image.Rectangle{Max: c.size})
		for i := range img.Pix {
			img.Pix[i] = 0xc8
		}
		if err := BlackOut(img, c.origin, []image.Rectangle{c.win}); err != nil {
			t.Fatalf("%s: %v", c.name, err)
		}
		want := c.win.Sub(c.origin).Intersect(img.Rect)
		for y := 0; y < c.size.Y; y += 7 {
			for x := 0; x < c.size.X; x += 7 {
				black := img.RGBAAt(x, y) == color.RGBA{0, 0, 0, 0xff}
				if in := image.Pt(x, y).In(want); in != black {
					t.Fatalf("%s: pixel %d,%d black=%v, inside window=%v", c.name, x, y, black, in)
				}
			}
		}
	}
}

func runMask(t *testing.T, m *maskFake) []Frame {
	t.Helper()
	var buf syncBuf
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Millisecond)
	defer cancel()
	if err := Loop(ctx, m, LoopConfig{Rules: config.DefaultDenyRules(), TextEvery: time.Hour, ShotEvery: 5 * time.Millisecond}, &buf, time.Now); err != nil {
		t.Fatal(err)
	}
	var frames []Frame
	if err := Read(strings.NewReader(buf.String()), func(fr Frame) { frames = append(frames, fr) }); err != nil {
		t.Fatal(err)
	}
	return frames
}

func TestLoopBlacksOutPatientWindow(t *testing.T) {
	front := Window{Title: "Windows PowerShell", Exe: "powershell.exe", PID: 7}
	pw := image.Rect(-1500, 100, -500, 700) // patient Workbench on the left monitor
	m := &maskFake{fake: fake{w: front}, origin: image.Pt(-1920, 0), size: image.Pt(3840, 1080),
		lists: [][]VisibleWindow{{vw(front, 1, image.Rect(0, 0, 900, 700), true), vw(patient, 2, pw, true)}}}
	frames := runMask(t, m)
	var shot *Frame
	for i := range frames {
		if frames[i].Type == "shot" && len(frames[i].PNG) > 0 {
			shot = &frames[i]
			break
		}
	}
	if shot == nil {
		t.Fatalf("no masked picture: %+v", frames)
	}
	if shot.Masked != 1 {
		t.Errorf("masked = %d", shot.Masked)
	}
	img, err := png.Decode(bytes.NewReader(shot.PNG))
	if err != nil {
		t.Fatal(err)
	}
	inside := pw.Sub(m.origin)
	for _, p := range []image.Point{inside.Min, inside.Max.Sub(image.Pt(1, 1)), inside.Min.Add(inside.Size().Div(2)), inside.Min.Sub(image.Pt(MaskMargin-1, MaskMargin-1))} {
		if r, g, b, _ := img.At(p.X, p.Y).RGBA(); r|g|b != 0 {
			t.Errorf("patient pixel %v not black", p)
		}
	}
	if r, _, _, _ := img.At(1920+100, 100).RGBA(); r == 0 {
		t.Error("the PowerShell area was blacked out too")
	}
}

func TestLoopMaskFailsClosed(t *testing.T) {
	front := Window{Title: "Windows PowerShell", Exe: "powershell.exe", PID: 7}
	a := []VisibleWindow{vw(front, 1, image.Rect(0, 0, 900, 700), true), vw(patient, 2, image.Rect(1000, 0, 1900, 700), true)}
	moved := []VisibleWindow{a[0], vw(patient, 2, image.Rect(1100, 0, 2000, 700), true)}
	// The patient window moved between the two listings: discard.
	m := &maskFake{fake: fake{w: front}, size: image.Pt(1920, 1080), lists: [][]VisibleWindow{a, moved}}
	frames := runMask(t, m)
	if count(frames, func(fr Frame) bool { return fr.Paused == "screen changed during capture; picture discarded" }) == 0 {
		t.Errorf("moved window not discarded: %+v", frames)
	}
	// Window list unreadable: whole picture paused, no picture taken.
	m = &maskFake{fake: fake{w: front}, size: image.Pt(1920, 1080), listErr: errors.New("enum")}
	frames = runMask(t, m)
	if count(frames, func(fr Frame) bool { return strings.HasPrefix(fr.Paused, "paused: cannot list the windows") }) == 0 || m.shots != 0 || count(frames, func(fr Frame) bool { return len(fr.PNG) > 0 }) != 0 {
		t.Errorf("list error did not pause: shots=%d %+v", m.shots, frames)
	}
	// Patient window position uncertain (scaling): whole picture paused, none taken.
	m = &maskFake{fake: fake{w: front}, size: image.Pt(1920, 1080), lists: [][]VisibleWindow{{a[0], vw(patient, 2, image.Rect(1000, 0, 1900, 700), false)}}}
	frames = runMask(t, m)
	if m.shots != 0 || count(frames, func(fr Frame) bool { return strings.Contains(fr.Paused, "position is not certain") }) == 0 {
		t.Errorf("uncertain window did not pause: shots=%d", m.shots)
	}
	// Patient window in FRONT: whole picture paused as before, none taken.
	m = &maskFake{fake: fake{w: patient}, size: image.Pt(1920, 1080), lists: [][]VisibleWindow{{vw(patient, 2, image.Rect(0, 0, 900, 700), true)}}}
	frames = runMask(t, m)
	if m.shots != 0 || count(frames, func(fr Frame) bool { return fr.Paused == "paused: patient-mode window" }) == 0 {
		t.Errorf("front patient window did not pause: shots=%d", m.shots)
	}
}

// firstShot is the first "shot" frame: the one taken while the change happened
// (later shots see the settled screen and may legitimately keep a picture).
func firstShot(t *testing.T, frames []Frame) Frame {
	t.Helper()
	for _, fr := range frames {
		if fr.Type == "shot" {
			return fr
		}
	}
	t.Fatal("no shot frame")
	return Frame{}
}

// The front window changing during the picture discards it even when the window
// list is identical (the front-window re-check is load-bearing on its own).
func TestMaskFrontChangeDiscards(t *testing.T) {
	front := Window{Title: "Windows PowerShell", Exe: "powershell.exe", PID: 7}
	list := []VisibleWindow{vw(front, 1, image.Rect(0, 0, 900, 700), true), vw(patient, 2, image.Rect(1000, 0, 1900, 700), true)}
	for _, after := range []Window{{Title: "Notepad", Exe: "notepad.exe", PID: 8}, patient} {
		a := after
		m := &maskFake{fake: fake{w: front}, size: image.Pt(1920, 1080), lists: [][]VisibleWindow{list}, afterShot: &a}
		if fr := firstShot(t, runMask(t, m)); len(fr.PNG) > 0 || fr.Paused != "screen changed during capture; picture discarded" {
			t.Errorf("front window became %q: picture not discarded (%q)", after.Title, fr.Paused)
		}
	}
}

// A monitor added, removed or moved during the picture discards it, and a picture
// that does not match the layout is discarded too.
func TestMaskLayoutChangeDiscards(t *testing.T) {
	front := Window{Title: "Windows PowerShell", Exe: "powershell.exe", PID: 7}
	list := []VisibleWindow{vw(front, 1, image.Rect(0, 0, 900, 700), true), vw(patient, 2, image.Rect(1000, 0, 1900, 700), true)}
	one := Layout{Rect: image.Rect(0, 0, 1920, 1080), Monitors: 1}
	for name, lays := range map[string][]Layout{
		"monitor added":          {one, {Rect: image.Rect(-1920, 0, 1920, 1080), Monitors: 2}},
		"same size, other count": {one, {Rect: one.Rect, Monitors: 2}},
		"picture does not match": {{Rect: image.Rect(0, 0, 2560, 1440), Monitors: 1}},
	} {
		m := &maskFake{fake: fake{w: front}, size: image.Pt(1920, 1080), lists: [][]VisibleWindow{list}, layouts: lays}
		if fr := firstShot(t, runMask(t, m)); len(fr.PNG) > 0 || fr.Paused != "screen changed during capture; picture discarded" {
			t.Errorf("%s: picture not discarded (%q)", name, fr.Paused)
		}
	}
}

// While a patient window exists, minimized included, a task switcher or taskbar
// preview on screen pauses the whole picture: it can show the patient window's
// live content inside a shell window that no deny rule matches.
func TestPreviewWithPatientWindowPauses(t *testing.T) {
	rules := config.DefaultDenyRules()
	front := Window{Title: "Windows PowerShell", Exe: "powershell.exe", PID: 7}
	shell := Window{Title: "Task Switching", Exe: `C:\Windows\explorer.exe`, PID: 3}
	sw := VisibleWindow{Window: shell, Handle: 9, Rect: image.Rect(0, 300, 1920, 800), Class: "XamlExplorerHostIslandWindow", Sure: true}
	thumb := VisibleWindow{Window: Window{Exe: `C:\Windows\explorer.exe`, PID: 3}, Handle: 10, Rect: image.Rect(800, 800, 1100, 1040), Class: "TaskListThumbnailWnd", Sure: true}
	minimized := VisibleWindow{Window: patient, Handle: 2, Hidden: true}
	for name, ws := range map[string][]VisibleWindow{
		"Alt-Tab, patient window on screen": {sw, vw(front, 1, image.Rect(0, 0, 900, 700), true), vw(patient, 2, image.Rect(1000, 0, 1900, 700), true)},
		"taskbar hover, patient minimized":  {thumb, vw(front, 1, image.Rect(0, 0, 900, 700), true), minimized},
	} {
		if _, _, pause := MaskPlan(ws, rules); !strings.Contains(pause, "window preview") {
			t.Errorf("%s: not paused (%q)", name, pause)
		}
	}
	// A minimized patient window with no preview up: nothing to black out, picture allowed.
	rects, n, pause := MaskPlan([]VisibleWindow{vw(front, 1, image.Rect(0, 0, 900, 700), true), minimized}, rules)
	if pause != "" || n != 0 || len(rects) != 0 {
		t.Errorf("minimized patient window alone: rects=%v n=%d pause=%q", rects, n, pause)
	}
	// A preview with no patient window anywhere does not pause.
	if _, _, pause := MaskPlan([]VisibleWindow{sw, vw(front, 1, image.Rect(0, 0, 900, 700), true)}, rules); pause != "" {
		t.Errorf("preview without a patient window paused: %q", pause)
	}
	// A minimized patient window drops out of the list while the picture is taken: discarded.
	m := &maskFake{fake: fake{w: front}, size: image.Pt(1920, 1080), lists: [][]VisibleWindow{
		{vw(front, 1, image.Rect(0, 0, 900, 700), true), minimized},
		{vw(front, 1, image.Rect(0, 0, 900, 700), true), vw(patient, 2, image.Rect(1000, 0, 1900, 700), true)},
	}}
	if fr := firstShot(t, runMask(t, m)); len(fr.PNG) > 0 {
		t.Error("picture kept while a minimized patient window was restored")
	}
}

func TestSameWindowsComparesHiddenAndClass(t *testing.T) {
	a := VisibleWindow{Window: patient, Handle: 2, Rect: image.Rect(0, 0, 10, 10), Class: "A", Sure: true}
	b := a
	b.Hidden = true
	if sameWindows([]VisibleWindow{a}, []VisibleWindow{b}) {
		t.Error("a window that became minimized counted as unchanged")
	}
	c := a
	c.Class = "B"
	if sameWindows([]VisibleWindow{a}, []VisibleWindow{c}) {
		t.Error("a different window class counted as unchanged")
	}
	if !sameWindows([]VisibleWindow{a}, []VisibleWindow{a}) {
		t.Error("identical lists differ")
	}
}
