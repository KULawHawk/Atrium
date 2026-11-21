//go:build windows

package pccheck

import (
	"unsafe"

	"golang.org/x/sys/windows"
)

// ReadPerms reads a file or folder's owner and explicit and inherited entries.
func ReadPerms(path string) (Perms, error) {
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return Perms{}, err
	}
	owner, _, err := sd.Owner()
	if err != nil {
		return Perms{}, err
	}
	p := Perms{Owner: owner.String()}
	dacl, _, err := sd.DACL()
	if err != nil {
		return Perms{}, err
	}
	if dacl == nil {
		// A missing DACL grants everyone everything.
		p.ACEs = []ACE{{SID: "S-1-1-0", Allow: true, Mask: 0x10000000}}
		return p, nil
	}
	for i := uint16(0); i < dacl.AceCount; i++ {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, uint32(i), &ace); err != nil {
			return Perms{}, err
		}
		switch ace.Header.AceType {
		case windows.ACCESS_ALLOWED_ACE_TYPE, windows.ACCESS_DENIED_ACE_TYPE:
		default:
			// Object or callback entries: count as a grant to an unknown principal,
			// so the check fails closed and a person looks.
			p.ACEs = append(p.ACEs, ACE{SID: "unrecognised-entry", Allow: true, Mask: uint32(ace.Mask)})
			continue
		}
		sid := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
		p.ACEs = append(p.ACEs, ACE{SID: sid.String(), Allow: ace.Header.AceType == windows.ACCESS_ALLOWED_ACE_TYPE,
			Mask: uint32(ace.Mask), InheritOnly: ace.Header.AceFlags&windows.INHERIT_ONLY_ACE != 0})
	}
	return p, nil
}
