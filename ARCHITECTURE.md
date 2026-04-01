# Metor Architecture

This document is the canonical architecture note for the repository.
It currently starts with the transport model because transport state is the most cross-cutting runtime concern in the daemon and chat stack.
Future architecture sections should extend this file instead of introducing parallel top-level architecture notes.

## Transport Model

The following rules describe the transport invariants enforced by the current daemon and chat runtime.
They exist so future work extends one coherent model instead of reintroducing ad-hoc live/drop behavior.

### Core Invariants

1. The daemon owns transport state.
   The UI may choose a peer focus, but it must not infer or manage Tor socket lifecycle directly.

2. Focus is not transport.
   A focused peer is only the selected chat target. Focus may keep a drop tunnel warm, but focus alone never makes a peer live.

3. Each peer has exactly one primary transport.
   Live is the primary transport whenever a peer is connecting, pending, connected, or retunneling.
   Drop may stay available as a standby path only when `daemon.allow_drop_standby_on_live` is enabled.

4. `daemon.drop_tunnel_idle_timeout = 0` means single-drop mode.
   In that mode no cached drop tunnel may survive after a single delivery attempt.

5. Cached drop tunnels close on inactivity, not on arbitrary batch timing.
   `daemon.drop_tunnel_idle_timeout` controls the idle close window for unfocused peers.
   Focused peers may keep their drop tunnel alive until focus is removed or transport policy closes it.

6. Retunnel is a peer-level transport operation.
   `/retunnel` emits a retunnel lifecycle (`initiated`, then `success` or `failed`) instead of generic disconnect/connect noise when the flow succeeds.

7. A successful retunnel only completes when the new route is ready.
   For live, success is emitted after the new live session is established.
   For drop, success is emitted after the cached drop route was discarded and Tor circuit rotation completed.

8. Timeline ordering is timestamp-driven for offline drops.
   Offline batches must be sorted chronologically before they are inserted into the visible chat history.

### Transport Settings

- `daemon.drop_tunnel_idle_timeout`
  Controls drop tunnel caching with one numeric value. A value of `0` disables caching and forces single-drop delivery. A value `> 0` keeps an unfocused cached drop tunnel alive for that many idle seconds.

- `daemon.allow_drop_standby_on_live`
  Controls whether a cached drop tunnel may remain warm while live is the primary transport. It does not reroute drop items into the live tunnel.

## Transport Shared State Model

The single source of truth for peer transport state is the daemon `StateTracker`.
It combines:

- live transport lifecycle
- cached drop tunnel presence
- retunnel flow markers
- UI focus reference counts

The outbox worker and the network stack must both read and write this shared state.

## Transport Default Policy

- Live wins over drop.
- Cached drop standby while live is active is disabled by default.
- Retunnel success/failure is transport-specific and explicit.
- The chat UI renders focus independently from transport state and only decorates the prompt based on the current primary route.
