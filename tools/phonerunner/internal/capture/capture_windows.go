//go:build windows

package capture

import (
	"bytes"
	"errors"
	"fmt"
	"image"
	"image/png"
	"strings"
	"sync"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	user32 = windows.NewLazySystemDLL("user32.dll")
	gdi32  = windows.NewLazySystemDLL("gdi32.dll")

	pGetForegroundWindow       = user32.NewProc("GetForegroundWindow")
	pGetWindowTextLengthW      = user32.NewProc("GetWindowTextLengthW")
	pGetWindowTextW            = user32.NewProc("GetWindowTextW")
	pGetWindowThreadProcessId  = user32.NewProc("GetWindowThreadProcessId")
	pOpenInputDesktop          = user32.NewProc("OpenInputDesktop")
	pGetUserObjectInformationW = user32.NewProc("GetUserObjectInformationW")
	pCloseDesktop              = user32.NewProc("CloseDesktop")
	pGetSystemMetrics          = user32.NewProc("GetSystemMetrics")
	pGetDC                     = user32.NewProc("GetDC")
	pReleaseDC                 = user32.NewProc("ReleaseDC")
	pSetDpiAwarenessCtx        = user32.NewProc("SetProcessDpiAwarenessContext")
	pEnumWindows               = user32.NewProc("EnumWindows")
	pIsWindowVisible           = user32.NewProc("IsWindowVisible")
	pIsIconic                  = user32.NewProc("IsIconic")
	pGetThreadDpiAwarenessCtx  = user32.NewProc("GetThreadDpiAwarenessContext")
	pGetAwarenessFromDpiCtx    = user32.NewProc("GetAwarenessFromDpiAwarenessContext")

	dwmapi                 = windows.NewLazySystemDLL("dwmapi.dll")
	pDwmGetWindowAttribute = dwmapi.NewProc("DwmGetWindowAttribute")

	pCreateCompatibleDC     = gdi32.NewProc("CreateCompatibleDC")
	pCreateCompatibleBitmap = gdi32.NewProc("CreateCompatibleBitmap")
	pSelectObject           = gdi32.NewProc("SelectObject")
	pBitBlt                 = gdi32.NewProc("BitBlt")
	pGetDIBits              = gdi32.NewProc("GetDIBits")
	pDeleteObject           = gdi32.NewProc("DeleteObject")
	pDeleteDC               = gdi32.NewProc("DeleteDC")
)

const (
	desktopReadObjects = 0x0001
	uoiName            = 2
	smXVirtual         = 76
	smYVirtual         = 77
	smCXVirtual        = 78
	smCYVirtual        = 79
	srcCopy            = 0x00CC0020
	captureBlt         = 0x40000000
	dibRGBColors       = 0

	dwmwaExtendedFrameBounds = 9
	dwmwaCloaked             = 14
	dpiAwarenessPerMonitor   = 2
)

// Win is the Windows Capturer. It must run inside Jake's desktop session.
type Win struct{}

// New returns the platform Capturer.
func New() Capturer { return Win{} }

// InitDPI makes screen metrics physical pixels so screenshots are not cropped on
// scaled displays. Failure is harmless (older Windows); it is reported, not fatal.
func InitDPI() error {
	if err := pSetDpiAwarenessCtx.Find(); err != nil {
		return err
	}
	r, _, err := pSetDpiAwarenessCtx.Call(^uintptr(3)) // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
	if r == 0 {
		return err
	}
	return nil
}

// Foreground reports the front window. No front window (for example while locked)
// is an empty Window, not an error.
func (Win) Foreground() (Window, error) {
	hwnd, _, _ := pGetForegroundWindow.Call()
	if hwnd == 0 {
		return Window{}, nil
	}
	return windowInfo(hwnd), nil
}

func windowInfo(hwnd uintptr) Window {
	n, _, _ := pGetWindowTextLengthW.Call(hwnd)
	buf := make([]uint16, n+1)
	pGetWindowTextW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
	var pid uint32
	pGetWindowThreadProcessId.Call(hwnd, uintptr(unsafe.Pointer(&pid)))
	w := Window{Title: windows.UTF16ToString(buf), PID: pid}
	if h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, pid); err == nil {
		name := make([]uint16, windows.MAX_LONG_PATH)
		size := uint32(len(name))
		if windows.QueryFullProcessImageName(h, 0, &name[0], &size) == nil {
			w.Exe = windows.UTF16ToString(name[:size])
		}
		windows.CloseHandle(h)
	}
	return w
}

type winRect struct{ Left, Top, Right, Bottom int32 }

// perMonitorAware is true only when this thread works in physical pixels on every
// monitor (InitDPI succeeded). Otherwise window positions may be scaled and are
// not certain.
func perMonitorAware() bool {
	if pGetThreadDpiAwarenessCtx.Find() != nil || pGetAwarenessFromDpiCtx.Find() != nil {
		return false
	}
	ctx, _, _ := pGetThreadDpiAwarenessCtx.Call()
	a, _, _ := pGetAwarenessFromDpiCtx.Call(ctx)
	return int32(a) == dpiAwarenessPerMonitor
}

// One EnumWindows callback for the whole process (Windows allows only a limited
// number of callbacks to be created), guarded by enumMu.
var (
	enumMu   sync.Mutex
	enumOnce sync.Once
	enumCB   uintptr
	enumList []uintptr
)

// VisibleWindows lists the top-level windows on screen, front first: shown, not
// minimized and not hidden by Windows (cloaked). A window whose cloaked state cannot
// be read counts as shown. Its rectangle is the visible frame from the desktop
// window manager in physical pixels; when that is not available, or this process
// does not work in physical pixels, the window is marked not Sure.
func (Win) VisibleWindows() ([]VisibleWindow, error) {
	enumOnce.Do(func() {
		enumCB = windows.NewCallback(func(hwnd, _ uintptr) uintptr { enumList = append(enumList, hwnd); return 1 })
	})
	enumMu.Lock()
	enumList = enumList[:0]
	r, _, err := pEnumWindows.Call(enumCB, 0)
	hwnds := append([]uintptr(nil), enumList...)
	enumMu.Unlock()
	if r == 0 {
		return nil, fmt.Errorf("capture: EnumWindows failed: %w", err)
	}
	aware := perMonitorAware()
	var out []VisibleWindow
	for _, h := range hwnds {
		if v, _, _ := pIsWindowVisible.Call(h); v == 0 {
			continue
		}
		if ic, _, _ := pIsIconic.Call(h); ic != 0 {
			continue
		}
		var cloaked uint32
		if hr, _, _ := pDwmGetWindowAttribute.Call(h, dwmwaCloaked, uintptr(unsafe.Pointer(&cloaked)), 4); hr == 0 && cloaked != 0 {
			continue
		}
		var rc winRect
		sure := aware
		if hr, _, _ := pDwmGetWindowAttribute.Call(h, dwmwaExtendedFrameBounds, uintptr(unsafe.Pointer(&rc)), unsafe.Sizeof(rc)); hr != 0 {
			sure = false
		}
		rect := image.Rect(int(rc.Left), int(rc.Top), int(rc.Right), int(rc.Bottom))
		if sure && rect.Empty() {
			continue
		}
		out = append(out, VisibleWindow{Window: windowInfo(h), Handle: h, Rect: rect, Sure: sure})
	}
	return out, nil
}

// Locked is true when the input desktop is not Jake's normal desktop (lock screen,
// sign-in screen, or a secure UAC prompt). Being unable to open the input desktop
// at all is treated as locked: the strict reading.
func (Win) Locked() (bool, error) {
	h, _, _ := pOpenInputDesktop.Call(0, 0, desktopReadObjects)
	if h == 0 {
		return true, nil
	}
	defer pCloseDesktop.Call(h)
	buf := make([]uint16, 256)
	var need uint32
	r, _, err := pGetUserObjectInformationW.Call(h, uoiName, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)*2), uintptr(unsafe.Pointer(&need)))
	if r == 0 {
		return true, fmt.Errorf("capture: desktop name unreadable: %w", err)
	}
	return !strings.EqualFold(windows.UTF16ToString(buf), "Default"), nil
}

type bitmapInfoHeader struct {
	Size          uint32
	Width         int32
	Height        int32
	Planes        uint16
	BitCount      uint16
	Compression   uint32
	SizeImage     uint32
	XPelsPerMeter int32
	YPelsPerMeter int32
	ClrUsed       uint32
	ClrImportant  uint32
}

// Screenshot captures all monitors as one PNG.
func (w Win) Screenshot() ([]byte, error) {
	img, _, err := w.ScreenImage()
	if err != nil {
		return nil, err
	}
	var out bytes.Buffer
	enc := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := enc.Encode(&out, img); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

// ScreenImage captures all monitors as one image; origin is the virtual-screen
// position of its top-left pixel.
func (Win) ScreenImage() (*image.RGBA, image.Point, error) {
	metric := func(i uintptr) int32 { r, _, _ := pGetSystemMetrics.Call(i); return int32(r) }
	x, y, w, h := metric(smXVirtual), metric(smYVirtual), metric(smCXVirtual), metric(smCYVirtual)
	if w <= 0 || h <= 0 {
		return nil, image.Point{}, errors.New("capture: no screen area (no desktop in this session?)")
	}
	screen, _, _ := pGetDC.Call(0)
	if screen == 0 {
		return nil, image.Point{}, errors.New("capture: GetDC failed")
	}
	defer pReleaseDC.Call(0, screen)
	mem, _, _ := pCreateCompatibleDC.Call(screen)
	if mem == 0 {
		return nil, image.Point{}, errors.New("capture: CreateCompatibleDC failed")
	}
	defer pDeleteDC.Call(mem)
	bmp, _, _ := pCreateCompatibleBitmap.Call(screen, uintptr(w), uintptr(h))
	if bmp == 0 {
		return nil, image.Point{}, errors.New("capture: CreateCompatibleBitmap failed")
	}
	defer pDeleteObject.Call(bmp)
	old, _, _ := pSelectObject.Call(mem, bmp)
	defer pSelectObject.Call(mem, old)
	if r, _, err := pBitBlt.Call(mem, 0, 0, uintptr(w), uintptr(h), screen, uintptr(x), uintptr(y), srcCopy|captureBlt); r == 0 {
		return nil, image.Point{}, fmt.Errorf("capture: BitBlt failed: %w", err)
	}
	bi := bitmapInfoHeader{Size: uint32(unsafe.Sizeof(bitmapInfoHeader{})), Width: w, Height: -h, Planes: 1, BitCount: 32}
	pix := make([]byte, int(w)*int(h)*4)
	// GetDIBits wants a BITMAPINFO; a header followed by no colour table is valid for 32-bit BI_RGB.
	if r, _, err := pGetDIBits.Call(mem, bmp, 0, uintptr(h), uintptr(unsafe.Pointer(&pix[0])), uintptr(unsafe.Pointer(&bi)), dibRGBColors); r == 0 {
		return nil, image.Point{}, fmt.Errorf("capture: GetDIBits failed: %w", err)
	}
	img := image.NewRGBA(image.Rect(0, 0, int(w), int(h)))
	for i := 0; i+3 < len(pix); i += 4 {
		img.Pix[i], img.Pix[i+1], img.Pix[i+2], img.Pix[i+3] = pix[i+2], pix[i+1], pix[i], 0xff
	}
	return img, image.Pt(int(x), int(y)), nil
}
