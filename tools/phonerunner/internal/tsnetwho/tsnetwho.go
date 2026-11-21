// Package tsnetwho turns Tailscale's own answer about a connection into a gate.Identity.
package tsnetwho

import (
	"context"
	"errors"

	"tailscale.com/client/tailscale/apitype"

	"github.com/kulawhawk/atrium/tools/phonerunner/internal/gate"
)

// WhoIsFunc is tsnet's LocalClient.WhoIs.
type WhoIsFunc func(ctx context.Context, remoteAddr string) (*apitype.WhoIsResponse, error)

// Adapter implements gate.WhoIser.
type Adapter struct{ Fn WhoIsFunc }

// WhoIs asks the tailnet who is behind remoteAddr.
func (a Adapter) WhoIs(ctx context.Context, remoteAddr string) (gate.Identity, error) {
	r, err := a.Fn(ctx, remoteAddr)
	if err != nil {
		return gate.Identity{}, err
	}
	if r == nil || r.Node == nil {
		return gate.Identity{}, errors.New("tailnet returned no device for this connection")
	}
	id := gate.Identity{NodeID: string(r.Node.StableID), NodeName: r.Node.ComputedName, Tagged: r.Node.IsTagged()}
	if r.UserProfile != nil {
		id.Login = r.UserProfile.LoginName
	}
	return id, nil
}
