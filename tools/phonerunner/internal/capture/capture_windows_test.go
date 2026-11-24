//go:build windows

package capture

import (
	"image"
	"runtime"
	"testing"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/config"
)

var (
	pRegisterClassExW = user32.NewProc("RegisterClassExW")
	pCreateWindowExW  = user32.NewProc("CreateWindowExW")
	pDestroyWindow    = user32.NewProc("DestroyWindow")
	pShowWindow       = user32.NewProc("ShowWindow")
	pDefWindowProcW   = user32.NewProc("DefWindowProcW")
	pPeekMessageW     = user32.NewProc("PeekMessageW")
	pTranslateMessage = user32.NewProc("TranslateMessage")
	pDispatchMessageW = user32.NewProc("DispatchMessageW")
)

type wndClassEx struct {
	Size, Style                        uint32
	WndProc                            uintptr
	ClsExtra, WndExtra                 int32
	Instance, Icon, Cursor, Background uintptr
	MenuName, ClassName                *uint16
	IconSm                             uintptr
}

const (
	wsOverlappedWindow = 0x00CF0000
	wsVisible          = 0x10000000
	swMinimize         = 6
	swRestore          = 9
)

func pump() {
	var msg [48]byte
	end := time.Now().Add(300 * time.Millisecond)
	for time.Now().Before(end) {
		for {
			r, _, _ := pPeekMessageW.Call(uintptr(unsafe.Pointer(&msg[0])), 0, 0, 0, 1)
			if r == 0 {
				break
			}
			pTranslateMessage.Call(uintptr(unsafe.Pointer(&msg[0])))
			pDispatchMessageW.Call(uintptr(unsafe.Pointer(&msg[0])))
		}
		time.Sleep(20 * time.Millisecond)
	}
}

func makeWindow(t *testing.T, title string, style uintptr, x, y, w, h int) uintptr {
	t.Helper()
	cls, _ := windows.UTF16PtrFromString("PhoneRunnerMaskTest")
	wc := wndClassEx{WndProc: pDefWindowProcW.Addr(), ClassName: cls}
	wc.Size = uint32(unsafe.Sizeof(wc))
	pRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc))) // a second registration fails harmlessly
	tp, _ := windows.UTF16PtrFromString(title)
	hwnd, _, err := pCreateWindowExW.Call(0, uintptr(unsafe.Pointer(cls)), uintptr(unsafe.Pointer(tp)), style,
		uintptr(x), uintptr(y), uintptr(w), uintptr(h), 0, 0, 0, 0)
	if hwnd == 0 {
		t.Fatalf("CreateWindowExW %q: %v", title, err)
	}
	t.Cleanup(func() { pDestroyWindow.Call(hwnd) })
	pump()
	return hwnd
}

func find(t *testing.T, hwnd uintptr) (VisibleWindow, bool) {
	t.Helper()
	ws, err := Win{}.VisibleWindows()
	if err != nil {
		t.Fatalf("VisibleWindows: %v", err)
	}
	for _, w := range ws {
		if w.Handle == hwnd {
			return w, true
		}
	}
	return VisibleWindow{}, false
}

func near(a, b int) bool { d := a - b; return d >= -16 && d <= 16 }

// A real patient window on this Windows machine is found with a certain position,
// and the blackout plan covers it. Minimized and hidden windows are not listed.
func TestRealWindowFoundAndCovered(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if err := InitDPI(); err != nil {
		t.Logf("InitDPI: %v (positions will be marked not certain)", err)
	}
	patient := makeWindow(t, "Conclave Workbench (patient run)", wsOverlappedWindow|wsVisible, 120, 140, 420, 300)
	hidden := makeWindow(t, "Conclave Workbench (patient run) hidden", wsOverlappedWindow, 200, 200, 300, 200)

	w, ok := find(t, patient)
	if !ok {
		t.Fatal("the visible patient window was not listed")
	}
	if w.Title != "Conclave Workbench (patient run)" || w.PID != uint32(windows.GetCurrentProcessId()) {
		t.Fatalf("wrong window details: %+v", w.Window)
	}
	if !w.Sure {
		t.Fatalf("position not certain on this machine (rect %v); the picture would pause, which is safe but should not happen here", w.Rect)
	}
	if !near(w.Rect.Min.X, 120) || !near(w.Rect.Min.Y, 140) || !near(w.Rect.Max.X, 540) || !near(w.Rect.Max.Y, 440) {
		t.Fatalf("rect %v is not where the window was placed (120,140)-(540,440)", w.Rect)
	}
	if _, ok := find(t, hidden); ok {
		t.Fatal("a hidden window was listed")
	}

	ws, _ := Win{}.VisibleWindows()
	rects, n, pause := MaskPlan(ws, config.DefaultDenyRules())
	if pause != "" {
		t.Fatalf("plan paused: %s", pause)
	}
	if n == 0 {
		t.Fatal("plan blacked out nothing")
	}
	covered := false
	for _, r := range rects {
		if w.Rect.In(r) {
			covered = true
		}
	}
	if !covered {
		t.Fatalf("no blackout rectangle covers the patient window %v: %v", w.Rect, rects)
	}

	pShowWindow.Call(patient, swMinimize)
	pump()
	if _, ok := find(t, patient); ok {
		t.Fatal("a minimized window was listed")
	}
	pShowWindow.Call(patient, swRestore)
	pump()
	if _, ok := find(t, patient); !ok {
		t.Fatal("the restored window was not listed again")
	}
}

// The screen picture on this machine has the virtual-screen size and origin, and
// a blackout over a real window's rectangle leaves only black there.
func TestRealScreenBlackOut(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	_ = InitDPI()
	hwnd := makeWindow(t, "Conclave Workbench (patient run)", wsOverlappedWindow|wsVisible, 100, 100, 300, 200)
	w, ok := find(t, hwnd)
	if !ok || !w.Sure {
		t.Fatalf("window not found with a certain position: %+v", w)
	}
	img, origin, err := Win{}.ScreenImage()
	if err != nil {
		t.Skipf("no screen picture on this machine: %v", err)
	}
	r := w.Rect.Inset(-MaskMargin)
	if err := BlackOut(img, origin, []image.Rectangle{r}); err != nil {
		t.Fatalf("BlackOut: %v", err)
	}
	vis := r.Sub(origin).Add(img.Rect.Min).Intersect(img.Rect)
	for y := vis.Min.Y; y < vis.Max.Y; y++ {
		for x := vis.Min.X; x < vis.Max.X; x++ {
			if c := img.RGBAAt(x, y); c.R != 0 || c.G != 0 || c.B != 0 {
				t.Fatalf("pixel %d,%d not black: %v", x, y, c)
			}
		}
	}
}
