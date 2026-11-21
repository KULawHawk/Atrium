package inbox

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// ErrOutside means a file resolved to somewhere outside its item folder: a link
// or junction was swapped in. The inbox is writable by Jake's account and the
// service reads it as SYSTEM, so without this check an agent could make the
// service read, show or copy a file Jake's account cannot read itself.
var ErrOutside = errors.New("a file is a link, a junction or a hard link, or resolves outside its item folder; refused")

// finalPath is where an open file really is (seam for tests).
var finalPath = finalPathOS

// links is the open file's hard-link count (seam for tests).
var links = linksOS

// readAll is io.ReadAll (seam for a read that fails mid-file).
var readAll = io.ReadAll

// ReadInside reads root/rel, at most MaxFileBytes, and refuses it unless the
// file that was actually opened lies inside root as it actually is. The check is
// made on the open handle, and the bytes are read from that same handle, so a
// swap after the check changes nothing.
func ReadInside(root, rel string) ([]byte, error) {
	if err := SafeRel(rel); err != nil {
		return nil, err
	}
	realRoot, err := realDir(root)
	if err != nil {
		return nil, err
	}
	// The item folder itself must not be a link or junction either: it must
	// really be the entry of that name in its parent folder.
	realParent, err := realDir(filepath.Dir(root))
	if err != nil {
		return nil, err
	}
	if !strings.EqualFold(realRoot, filepath.Join(realParent, filepath.Base(root))) {
		return nil, ErrOutside
	}
	f, err := os.Open(filepath.Join(root, filepath.FromSlash(rel)))
	if err != nil {
		return nil, err
	}
	defer f.Close()
	real, err := finalPath(f)
	if err != nil {
		return nil, err
	}
	if r, err := filepath.Rel(realRoot, real); err != nil || r == ".." || strings.HasPrefix(r, ".."+string(filepath.Separator)) {
		return nil, ErrOutside
	}
	st, err := f.Stat()
	if err != nil || !st.Mode().IsRegular() {
		return nil, errors.New("not a plain file")
	}
	// A hard link's path is its name inside the item, so the path check cannot
	// see it; a file with more than one name is refused outright.
	if n, err := links(f, st); err != nil || n != 1 {
		return nil, ErrOutside
	}
	b, err := readAll(io.LimitReader(f, MaxFileBytes+1))
	if err != nil {
		return nil, err
	}
	if len(b) > MaxFileBytes {
		return nil, errTooBig
	}
	return b, nil
}

func realDir(p string) (string, error) {
	f, err := os.Open(p)
	if err != nil {
		return "", err
	}
	defer f.Close()
	return finalPath(f)
}
