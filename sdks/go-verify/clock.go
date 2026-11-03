package keyflint

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// ClockGuard remembers the latest time this machine has seen, in a small JSON file shared with
// the Python and npm packages ({"v": 1, "last_seen": <unix>}), falling back to memory when the
// file cannot be written. Pass LastSeen() in Options.LastSeen and call Record after a successful
// check. Limits: whoever controls the machine can delete the file; a fresh container has no state.
type ClockGuard struct {
	path string
	mu   sync.Mutex
	mem  int64
}

// NewClockGuard uses path; "" means KEYFLINT_CLOCK_STATE or ~/.keyflint/clock_state
// ("off" = memory only).
func NewClockGuard(path string) *ClockGuard {
	if path == "" {
		if raw, set := os.LookupEnv("KEYFLINT_CLOCK_STATE"); set {
			switch strings.ToLower(strings.TrimSpace(raw)) {
			case "", "off", "0", "false":
				return &ClockGuard{}
			}
			path = raw
		} else if home, err := os.UserHomeDir(); err == nil {
			path = filepath.Join(home, ".keyflint", "clock_state")
		}
	}
	return &ClockGuard{path: path}
}

func (g *ClockGuard) readDisk() int64 {
	if g.path == "" {
		return 0
	}
	data, err := os.ReadFile(g.path)
	if err != nil {
		return 0
	}
	var st struct {
		LastSeen float64 `json:"last_seen"`
	}
	if json.Unmarshal(data, &st) != nil {
		return 0
	}
	return int64(st.LastSeen)
}

// LastSeen returns the latest recorded time, or the zero time when none is stored.
func (g *ClockGuard) LastSeen() time.Time {
	g.mu.Lock()
	defer g.mu.Unlock()
	v := g.readDisk()
	if g.mem > v {
		v = g.mem
	}
	if v <= 0 {
		return time.Time{}
	}
	return time.Unix(v, 0)
}

// Record stores now if it is later than the stored time. It never fails.
func (g *ClockGuard) Record(now time.Time) {
	cur := now.Unix()
	g.mu.Lock()
	defer g.mu.Unlock()
	if cur <= g.mem {
		return
	}
	disk := g.readDisk()
	g.mem = cur
	if disk > cur {
		g.mem = disk
	}
	if g.path == "" || disk >= cur {
		return
	}
	if os.MkdirAll(filepath.Dir(g.path), 0o700) != nil {
		return
	}
	tmp, err := os.CreateTemp(filepath.Dir(g.path), ".clock_state.")
	if err != nil {
		return
	}
	data, _ := json.Marshal(map[string]int64{"v": 1, "last_seen": cur})
	_, werr := tmp.Write(data)
	cerr := tmp.Close()
	if werr != nil || cerr != nil || os.Rename(tmp.Name(), g.path) != nil {
		_ = os.Remove(tmp.Name())
	}
}
