//go:build windows

package capture

// Screen text through Windows UI Automation, by raw COM calls (no cgo, no extra
// module). UNTESTED ON A PC: the vtable positions below follow UIAutomationClient.h
// and are proved only by PC test T-10. Screen text is off by default
// (screen_text_seconds = 0) until T-10 passes, because a wrong position here would
// crash the session part (the service restarts it and logs each exit).

import (
	"errors"
	"fmt"
	"runtime"
	"strings"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	ole32              = windows.NewLazySystemDLL("ole32.dll")
	oleaut32           = windows.NewLazySystemDLL("oleaut32.dll")
	pCoInitializeEx    = ole32.NewProc("CoInitializeEx")
	pCoUninitialize    = ole32.NewProc("CoUninitialize")
	pCoCreateInstance  = ole32.NewProc("CoCreateInstance")
	pSysFreeString     = oleaut32.NewProc("SysFreeString")
	clsidCUIAutomation = windows.GUID{Data1: 0xff48dba4, Data2: 0x60ef, Data3: 0x4201, Data4: [8]byte{0xaa, 0x87, 0x54, 0x10, 0x3e, 0xef, 0x59, 0x4e}}
	iidIUIAutomation   = windows.GUID{Data1: 0x30cbe57d, Data2: 0xd9d0, Data3: 0x452a, Data4: [8]byte{0xab, 0x13, 0x7a, 0xc5, 0xac, 0x48, 0x25, 0xee}}
	iidIUIATextPattern = windows.GUID{Data1: 0x32eba289, Data2: 0x3583, Data3: 0x42c9, Data4: [8]byte{0x9c, 0x59, 0x3b, 0x6d, 0x9a, 0x1e, 0x9b, 0x6a}}
	errNoFrontWindow   = errors.New("no front window")
)

// vtable positions (IUnknown is 0..2).
const (
	vRelease = 2
	// IUIAutomation
	vElementFromHandle   = 6
	vCreateTrueCondition = 21
	// IUIAutomationElement
	vFindAll             = 6
	vGetCurrentPatternAs = 14
	vGetCurrentName      = 23
	vGetCurrentIsPasswd  = 35
	// IUIAutomationElementArray
	vArrLength = 3
	vArrGet    = 4
	// IUIAutomationTextPattern
	vGetVisibleRanges = 6
	// IUIAutomationTextRangeArray
	vRangesLength = 3
	vRangesGet    = 4
	// IUIAutomationTextRange
	vGetText = 12

	treeScopeChildren   = 2
	uiaTextPatternID    = 10014
	maxElements         = 400
	maxTextChars        = 20000 // per visible range
	clsctxInprocServer  = 1
	coinitMultithreaded = 0
	rpcEChangedMode     = 0x80010106
)

// vcall calls method idx of a COM object.
func vcall(obj unsafe.Pointer, idx int, args ...uintptr) uintptr {
	vtbl := *(*unsafe.Pointer)(obj)
	fn := *(*uintptr)(unsafe.Add(vtbl, idx*int(unsafe.Sizeof(uintptr(0)))))
	r, _, _ := syscall.SyscallN(fn, append([]uintptr{uintptr(obj)}, args...)...)
	return r
}

func release(obj unsafe.Pointer) {
	if obj != nil {
		vcall(obj, vRelease)
	}
}

func out(p *unsafe.Pointer) uintptr { return uintptr(unsafe.Pointer(p)) }

func bstr(b *uint16) string {
	if b == nil {
		return ""
	}
	s := windows.UTF16PtrToString(b)
	pSysFreeString.Call(uintptr(unsafe.Pointer(b)))
	return s
}

func hr(r uintptr, what string) error {
	if int32(r) < 0 {
		return fmt.Errorf("%s failed (0x%08x)", what, uint32(r))
	}
	return nil
}

// ScreenText returns the front window's visible text: the names of its parts
// (password boxes skipped), then the on-screen lines of any text area.
func (Win) ScreenText() ([]string, error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if r, _, _ := pCoInitializeEx.Call(0, coinitMultithreaded); r != rpcEChangedMode {
		if err := hr(r, "CoInitializeEx"); err != nil {
			return nil, err
		}
		defer pCoUninitialize.Call()
	}
	hwnd, _, _ := pGetForegroundWindow.Call()
	if hwnd == 0 {
		return nil, errNoFrontWindow
	}
	var uia unsafe.Pointer
	r, _, _ := pCoCreateInstance.Call(uintptr(unsafe.Pointer(&clsidCUIAutomation)), 0, clsctxInprocServer,
		uintptr(unsafe.Pointer(&iidIUIAutomation)), out(&uia))
	if err := hr(r, "UI Automation start"); err != nil {
		return nil, err
	}
	defer release(uia)
	var root, cond unsafe.Pointer
	if err := hr(vcall(uia, vElementFromHandle, hwnd, out(&root)), "ElementFromHandle"); err != nil {
		return nil, err
	}
	defer release(root)
	if err := hr(vcall(uia, vCreateTrueCondition, out(&cond)), "CreateTrueCondition"); err != nil {
		return nil, err
	}
	defer release(cond)
	// Walk the window's parts breadth-first, one level at a time, and stop at
	// maxElements, so a huge window never builds its whole tree in one call.
	var lines []string
	seen := map[string]bool{}
	visited := 0
	level := []unsafe.Pointer{root}
	vcall(root, 1) // AddRef: root is released below with the rest of its level
	for len(level) > 0 && visited < maxElements {
		var next []unsafe.Pointer
		for _, parent := range level {
			if visited < maxElements {
				next = append(next, children(parent, cond, maxElements-visited-len(next))...)
			}
			release(parent)
		}
		for _, e := range next {
			if visited >= maxElements {
				break
			}
			visited++
			if isPassword(e) {
				continue // never read a password box, not even its name
			}
			var name *uint16
			if hr(vcall(e, vGetCurrentName, uintptr(unsafe.Pointer(&name))), "name") == nil {
				if s := strings.TrimSpace(bstr(name)); s != "" && !seen[s] {
					seen[s] = true
					lines = append(lines, s)
				}
			}
			lines = append(lines, visibleText(e)...)
		}
		level = next
	}
	for _, e := range level {
		release(e)
	}
	return lines, nil
}

// children returns up to max direct children of e (each must be released).
func children(e, cond unsafe.Pointer, max int) []unsafe.Pointer {
	var arr unsafe.Pointer
	if max <= 0 || hr(vcall(e, vFindAll, treeScopeChildren, uintptr(cond), out(&arr)), "FindAll") != nil || arr == nil {
		return nil
	}
	defer release(arr)
	var n int32
	if hr(vcall(arr, vArrLength, uintptr(unsafe.Pointer(&n))), "array length") != nil {
		return nil
	}
	var out_ []unsafe.Pointer
	for i := int32(0); i < n && len(out_) < max; i++ {
		var c unsafe.Pointer
		if hr(vcall(arr, vArrGet, uintptr(i), out(&c)), "element") == nil && c != nil {
			out_ = append(out_, c)
		}
	}
	return out_
}

// isPassword reports whether e is a password box. If the answer cannot be read,
// it is treated as one.
func isPassword(e unsafe.Pointer) bool {
	var v int32
	if hr(vcall(e, vGetCurrentIsPasswd, uintptr(unsafe.Pointer(&v))), "is password") != nil {
		return true
	}
	return v != 0
}

// visibleText returns the lines of an element's text area that are on screen
// now (GetVisibleRanges), not the whole document.
func visibleText(e unsafe.Pointer) []string {
	var tp, ranges unsafe.Pointer
	if hr(vcall(e, vGetCurrentPatternAs, uiaTextPatternID, uintptr(unsafe.Pointer(&iidIUIATextPattern)), out(&tp)), "text pattern") != nil || tp == nil {
		return nil
	}
	defer release(tp)
	if hr(vcall(tp, vGetVisibleRanges, out(&ranges)), "visible ranges") != nil || ranges == nil {
		return nil
	}
	defer release(ranges)
	var n int32
	if hr(vcall(ranges, vRangesLength, uintptr(unsafe.Pointer(&n))), "ranges length") != nil {
		return nil
	}
	var all []string
	for i := int32(0); i < n && len(all) < MaxTextLines; i++ {
		var rng unsafe.Pointer
		if hr(vcall(ranges, vRangesGet, uintptr(i), out(&rng)), "range") != nil || rng == nil {
			continue
		}
		var text *uint16
		if hr(vcall(rng, vGetText, maxTextChars, uintptr(unsafe.Pointer(&text))), "get text") == nil {
			all = append(all, strings.Split(strings.ReplaceAll(bstr(text), "\r\n", "\n"), "\n")...)
		}
		release(rng)
	}
	return all
}
