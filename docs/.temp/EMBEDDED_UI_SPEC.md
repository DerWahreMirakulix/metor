# EMBEDDED_UI_SPEC.md

**Status:** Normative implementation specification for Agent 2
**Target:** Metor `embeddedui` branch / post-Core-refactor codebase  
**Execution order:** Start this task only after `CORE_TERMINAL_REFACTORING.md` is complete and the updated Core/client/Terminal test suite is green.  
**Language:** All user-facing Embedded UI text is English.  
**Primary design goal:** Minimalistic is king. The UI must expose all required capabilities with the fewest concepts, actions, screens, and persistent visual controls possible.

---

# 1. Purpose

Implement the final Embedded UI for Metor as a privacy-first, touch-first communication interface over the Core/client contract prepared by Agent 1.

This UI is not a generic desktop messenger and not a web dashboard. It is a compact dedicated-device interface optimized for:

- DROP communication,
- LIVE communication,
- text,
- Push-to-Talk / Voice,
- multiple simultaneous Live connections,
- fast contact access,
- secure device locking,
- profile switching,
- privacy-aware notifications,
- QR contact exchange,
- a minimal set of settings,
- predictable behavior under disconnect, reconnect, overflow, buffer pressure, UI restart, profile switch, power-off, and purge.

The user-facing product model must remain simple even where the Core behavior is sophisticated.

The UI must never expose technical transport concepts such as:

- `session`
- `tunnel`
- `direct`
- internal socket state
- Tor circuit implementation details

The user-facing communication semantics are only:

```text
DROP
LIVE
```

---

# 2. Non-negotiable design principles

## 2.1 Minimalism over feature visibility

Do not keep buttons visible merely because the feature exists.

A capability should appear:

- where the user expects it,
- only when it is currently relevant,
- with the fewest possible decisions.

Examples:

- `Send as Drop` appears for pending Live content when relevant.
- `Reconnect` appears for disconnected Live state.
- `LIVE` status/count appears only when Live state exists.
- notification details appear only when allowed by the current lock privacy mode.
- advanced technical settings do not clutter the primary Settings page.

---

## 2.2 Navigation never changes communication state implicitly

Navigation actions such as:

- Back,
- switching `DROP | LIVE`,
- opening a peer,
- opening Notifications,
- opening Contacts,
- opening Settings,
- UI restart,
- unlock,
- profile bootstrap

MUST NOT implicitly:

- connect,
- reconnect,
- accept,
- reject,
- disconnect,
- fallback,
- retunnel.

Explicit user actions are required for those state changes.

---

## 2.3 Core state is authoritative

The Embedded UI must not rebuild domain truth locally.

Core owns:

- message state,
- `msg_id`,
- ACK/pending state,
- fallback state,
- Live connection state,
- reconnect state,
- saved/discovered peer state,
- history,
- profile state,
- resource limits,
- auth state.

The UI owns only presentation and transient interaction state.

---

## 2.4 Privacy-first

Never create a hidden substitute history.

In particular:

- no persistent message previews in notifications,
- no persistent Notification Center history,
- no persistent Live transcript beyond Core-authorized unseen/pending state,
- no persistent text drafts,
- no persistent local playback history,
- no persistent frontend-created peer activity log.

Respect Core privacy settings at all times:

- ephemeral Drops,
- Live history recording,
- Drop history recording,
- read-receipt policy.

---

## 2.5 User-facing strings stay English

The Terminal is already English-oriented. Keep Embedded consistent.

Do not introduce German UI strings.

---

# 3. Hardware interaction model

The baseline Embedded device is touch-first with the fewest physical controls possible.

Required physical controls:

```text
Power / Lock button
PTT button
Touchscreen
```

Optional hardware such as status LED, haptics, camera, microphone, speaker, or headset are exposed through platform abstractions.

Do not require:

- physical Back button,
- physical Home button,
- physical keyboard,
- D-pad navigation.

The software keyboard is the primary text input mechanism.

---

# 4. Global information architecture

There is no separate Home screen and no bottom navigation bar.

The root screen after unlock is the communication overview.

Canonical root layout:

```text
METOR                      [Notifications] [Contacts] [Settings]

[ DROP ] [ LIVE ]                                      [+]

<current list>
```

Where:

- `DROP` shows persistent conversation summaries.
- `LIVE` shows active and still-relevant Live contexts.
- Notifications opens the volatile Notification Center.
- Contacts opens Saved Contacts only.
- Settings opens Settings.
- `+` is contextual:
  - in DROP: start/open a Drop context,
  - in LIVE: start a Live connection.

The exact visual iconography may vary, but the navigation model must not.

No additional permanent top-level tabs.

---

# 5. Root DROP list

## 5.1 Contents

The DROP list contains only peers with actual persistent communication state relevant to the Drop conversation.

Do not show every saved contact automatically.

If communication is deleted and no Drop conversation state remains, remove that peer from the DROP list.

Saved contacts remain available in Contacts.

Discovered/anonymized peers may appear in DROP if relevant communication exists.

---

## 5.2 Ordering

Ordering:

1. pinned Drop conversations,
2. then remaining conversations by latest relevant Drop activity.

Pinning is Embedded-local presentation state keyed by stable Onion identity, not alias.

Rename must not lose a pin.

Contact demotion must not lose a pin while the same Onion identity remains relevant.

Deleting a Drop conversation removes its pin.

Removing the peer entirely removes its pin.

---

## 5.3 Long-press actions

Long-press on a Drop conversation:

```text
Pin / Unpin
Delete conversation
```

Do not expose permanent per-row action buttons.

`Delete conversation` invokes the Core DROP-only clear semantics.

The contact itself is not removed.

---

## 5.4 Root DROP `+`

Tap `+` in DROP:

```text
Contact picker
    -> select saved contact
        -> open that peer's DROP view

or
    -> Scan QR
        -> add/save peer
        -> immediately open DROP
```

If the QR introduces a new contact, the primary confirmation CTA should clearly preserve intent:

```text
Save & Open Drop
```

Do not save and then force the user to manually locate the same contact again.

Opening a new Drop view does not create a root DROP conversation entry until actual persistent communication exists.

---

# 6. Root LIVE list

## 6.1 Contents

The LIVE list contains:

- active Live connections,
- connecting/recovering Live contexts,
- disconnected Live contexts that still have relevant Core state,
- contexts with unseen Live content,
- contexts with pending outbound Live content.

A Live context does not disappear merely because the network connection ended.

A disconnected Live context remains relevant while Core still owns meaningful unresolved state.

Example:

```text
LIVE

Alice
active

Bob
disconnected · 3 pending

Charlie
2 new
```

Do not pin Live contexts.

The Live list should sort primarily by:

1. active/recovering importance,
2. actionable/pending/new state,
3. recency.

Avoid complex user-configurable Live sorting.

---

## 6.2 Root LIVE `+`

Tap `+` in LIVE:

```text
Contact picker
    -> select saved contact
        -> immediately start Live / ring the peer

or
    -> Scan QR
        -> add/save peer
        -> immediately start Live
```

For a newly scanned peer, use a clear CTA such as:

```text
Save & Start Live
```

Do not require an extra "Start Live" step afterward.

---

# 7. Peer conversation screen

The peer screen uses the same semantic selector everywhere:

```text
< Back                         Alice

                 [ DROP ] [ LIVE ]
```

Do not use `CHATS | LIVE` in one place and `DROP | LIVE` in another.

The user should learn one product vocabulary:

```text
DROP
LIVE
```

---

# 8. DROP peer view

## 8.1 General behavior

Opening a peer from the root DROP list opens:

```text
peer -> DROP
```

Opening a peer from Contacts via `Start Drop` also opens DROP.

DROP is the persistent conversation projection.

A currently active Live connection to the same peer remains active when the user is viewing DROP.

The header selector must reflect active/new Live state, for example:

```text
[ DROP ] [ LIVE ● ]
```

or with a new-item count:

```text
[ DROP ] [ LIVE ●2 ]
```

Exact badge styling may differ.

---

## 8.2 Switching DROP -> LIVE

If a Live connection already exists:

```text
tap LIVE
-> open existing Live context
```

No new ring/connect request.

If no Live connection exists:

```text
tap LIVE
-> explicitly start Live / ring peer
```

This is an explicit user action and may show:

```text
Calling Alice…
Cancel
```

Do not start Live simply because the peer screen was opened.

---

## 8.3 DROP text composer

Normal state:

```text
[ Message…                              Send ]
```

Tap the input -> software keyboard appears.

Text drafts:

- survive navigation inside the current UI runtime,
- may be distinct for `peer + DROP`,
- are RAM-only,
- do not survive UI restart,
- do not survive profile switch,
- do not survive shutdown/purge.

No cloud dictionary, telemetry, learned personal dictionary, or network-based text suggestions.

Keyboard layout should be configurable locally, at minimum:

- QWERTY
- QWERTZ

Autocorrect is not required for V1.

---

## 8.4 DROP Voice / PTT

PTT down in DROP starts a local voice draft.

During PTT:

- keyboard disappears,
- composer becomes recording state,
- bottom area shows a clear timer,
- a voice placeholder may appear in the Drop view at the correct local chronology,
- incoming content remains visible.

Example:

```text
You
Recording…

                    [ Recording 00:12 ]
```

PTT release does **not** auto-send in DROP.

After release:

```text
Voice draft

[ Play ] [ Delete ] [ Send ]
```

The text keyboard stays hidden while the voice draft is in review.

`Play`:

- plays locally,
- leaves the draft intact.

`Delete`:

- destroys the unsent local draft,
- returns to text composer.

`Send`:

- sends the Voice as DROP,
- returns to text composer.

If the configured local Voice buffer hits:

- ~90% -> warn,
- hard limit -> stop/finalize the recording locally,
- remain in voice review,
- never auto-send a Drop solely because the resource limit was reached.

---

## 8.5 DROP message long-press

For own/received Drop items, support the minimal useful actions.

At minimum:

```text
Copy   (text only, if platform policy allows)
Delete
```

`Delete` means local deletion only.

No "delete for everyone".

No remote deletion protocol.

No Reply/Quote in V1.

---

# 9. LIVE peer view

## 9.1 General model

LIVE is an ephemeral stream of:

- Text,
- Voice.

It is not a transport screen.

Do not expose:

- session/tunnel/direct,
- transport selection,
- raw Tor route metadata.

A Live connection may exist while the user is simultaneously sending/reading Drop communication to the same peer.

---

## 9.2 Entry behavior

Opening a peer from the root LIVE list opens LIVE.

Opening a peer from root DROP opens DROP.

Opening a peer from Contacts using `Start Live` rings/starts Live.

The entry path determines initial projection; do not "remember last tab" in a way that defeats the user's explicit navigation intent.

---

## 9.3 LIVE text

LIVE text appears in the ephemeral stream.

LIVE text send remains available while Live is active or genuinely recovering.

If the Live state is terminally disconnected, do not allow arbitrary new LIVE sends.

The UI should surface:

```text
Reconnect
Send pending as Drop
```

as appropriate.

---

## 9.4 Live Voice / PTT

PTT down in LIVE:

- binds the Voice turn to the current peer immediately,
- starts one logical Voice item,
- starts streaming,
- creates a visible placeholder/bubble immediately,
- hides the software keyboard,
- replaces the composer with a recording timer.

Example:

```text
You
Voice · transmitting…

Alice
Use the back entrance.

                    [ LIVE 00:13 ]
```

Incoming Text and Voice remain visible during the local PTT turn.

The remote peer may speak and text concurrently.

Core supports full duplex; the UI must not impose half-duplex.

---

## 9.5 PTT target immutability

One physical PTT press belongs to exactly one Live peer from PTT-down until finalization.

It must never migrate to another peer.

If the user changes communication context while PTT is still held:

- finalize the current Voice turn,
- navigate,
- do not start a new Voice turn in the new context,
- require physical PTT release before the input is re-armed,
- show a minimal hint such as:

```text
Release PTT
```

Examples that finalize current PTT:

- LIVE Alice -> LIVE Bob
- LIVE Alice -> DROP Alice
- LIVE Alice -> Back
- incoming Bob call -> `Open`

Examples that do not finalize current PTT:

- incoming Bob call -> `Accept` while staying on Alice,
- screen off while Alice remains the explicit allowed locked Live target.

---

## 9.6 LIVE PTT release

PTT release in LIVE:

- finalizes the Voice turn,
- sends/continues send automatically according to Live semantics,
- no review screen,
- normal text composer returns.

If transport is unavailable but genuine recovery is active, the Voice remains pending/recoverable according to Core.

If recovery ultimately fails:

- fallback ON -> Core promotes the finalized Voice to DROP,
- fallback OFF -> the Voice remains pending Live.

---

# 10. LIVE full-duplex behavior

The UI must allow the following simultaneously:

```text
user speaks
peer speaks
user sends text
peer sends text
```

Do not block remote content while local PTT is active.

Do not freeze the Live timeline behind a full-screen recording modal.

Local composer is intentionally simplified during PTT, but incoming communication remains visible.

Platform audio must support full-duplex capture/playback.

Acoustic echo cancellation is a platform requirement.

Where platform AEC is insufficient, platform-level ducking/gain handling may be used, but do not alter the product model to half-duplex.

---

# 11. LIVE Auto-play

## 11.1 Core rule

Auto-play is presentation behavior.

Effective auto-play requires:

```text
current Live context is foreground/eligible
AND
per-context auto-play preference == ON
```

No other Live channel may auto-play.

---

## 11.2 Global default

There is a persistent user setting:

```text
Auto-play default
```

A new Live context starts from this default.

---

## 11.3 Per-Live-context override

Inside LIVE, Auto-play can be toggled directly without going into Settings.

Example:

```text
Auto-play: ON
```

or a compact equivalent.

The override:

- belongs to the current Live context,
- survives switching to another Live peer and back,
- survives reconnect/recovery of that same Live context,
- is discarded only when the Live context is truly closed/dismissed.

A new future Live context starts from the global default again.

---

## 11.4 Outside foreground

If a Live context is not foreground:

- never auto-play,
- incoming Voice becomes unseen/new,
- Text/Voice are still received according to Core.

Returning to that context does not retroactively auto-play old Voice.

Only newly arriving Voice after foreground eligibility is restored may auto-play.

---

# 12. Manual LIVE Voice playback and timeshift

When Auto-play is OFF, incoming Voice appears silently.

For a completed Voice item:

```text
Tap -> play from beginning
```

For a Voice turn still arriving:

```text
Tap -> play from beginning
```

The user may therefore listen behind the current Live edge.

While behind the Live edge, show a minimal `LIVE` jump control.

Example:

```text
Alice
0:07 / 0:19                         LIVE
```

Tap `LIVE` -> jump to current edge.

Manual playback may occur while the user also:

- types,
- sends Text,
- holds PTT.

Do not artificially block these interactions.

---

# 13. LIVE timeline scrolling

When the user is already at the Live edge:

- new incoming items may auto-scroll into view.

When the user:

- scrolls upward,
- or is manually playing an older Voice item,

do not force-scroll.

Show a compact new-item indicator:

```text
3 new ↓
```

Tap -> return to Live edge.

This is frontend-only transient state.

---

# 14. Retunnel / Change route

Retunnel must be directly available from the LIVE view.

Do not call it "Retunnel" in normal user-facing UI.

Use a simple user-facing action:

```text
Change route
```

Recommended location:

```text
peer Live menu
    -> Change route
    -> End Live
```

While in progress:

```text
Changing route…
```

On success:

```text
Route changed
```

briefly.

Do not expose the transport type, route IDs, IPs, or Tor circuit details.

Changing route does not destroy the Live context or transcript.

---

# 15. Disconnect and recovery UI

## 15.1 Reconnecting

During genuine recovery:

```text
Reconnecting…
```

The Live context remains the same.

Text may still be sent and become pending.

Voice/PTT may continue according to buffer limits.

Auto-play override remains unchanged.

---

## 15.2 Terminally disconnected

Once Core reports that recovery is over:

```text
Alice
LIVE disconnected

3 messages pending

[ Reconnect ]
[ Send 3 as Drop ]
```

Do not auto-reconnect merely because the user opens this view.

---

## 15.3 Individual pending fallback

Long-press on an own pending LIVE item:

```text
Send as Drop
```

This is true fallback:

- same `msg_id`,
- selected item leaves Live recovery/replay,
- Core promotes it to Drop.

---

## 15.4 Bulk fallback

When multiple pending Live items exist:

```text
Send 3 as Drop
```

remains available.

---

## 15.5 Delivered LIVE -> DROP

Long-press on an own already-delivered LIVE item:

```text
Resend as Drop
```

This is not fallback.

It creates a new DROP message with a new `msg_id`.

Do not label this action "Persist".

The original LIVE item remains historically ephemeral.

---

## 15.6 Received LIVE item

Do not provide `Resend as Drop` for received Live content in V1.

Do not accidentally create forwarding/quoting semantics.

---

# 16. Incoming Live call overlay

Incoming Live requests are globally visible when lock/privacy policy permits.

The overlay appears above the current UI without destroying the current screen or draft.

Canonical actions:

```text
Incoming Live — Alice

[ Decline ] [ Accept ] [ Open ]
```

Meaning:

### Decline

Reject request.

Stay where the user is.

### Accept

Accept the Live connection but remain in the current UI context.

Do not auto-navigate.

Do not automatically make the accepted peer the foreground Live target.

Do not auto-play unless that peer is already the active eligible foreground Live context.

### Open

Accept and navigate to that peer's LIVE view.

If currently locked and authentication is required, authenticate first using the configured normal unlock method.

---

# 17. Multiple Live connections

Multiple Live connections may exist simultaneously.

Rules:

- only one foreground Live context may have Auto-play eligibility,
- other connections remain active in the background,
- incoming Text/Voice is retained as unseen according to Core limits,
- no automatic foreground switching,
- no automatic PTT target switching.

Root LIVE overview is the canonical global place to see them.

---

# 18. Live backlog overflow

The receiver may terminate a Live session when its unseen Live backlog/resource policy is full.

The UI behavior is based on Core facts.

For the local peer whose Core terminates due to safety policy:

```text
Live with Alice ended
Unread Live limit reached
```

This may appear as a sanitized notification.

For the remote peer:

- show generic Live disconnect/end,
- do not claim knowledge of the other peer's local buffer reason.

If remote side has pending Live and fallback OFF:

```text
Live disconnected
3 pending
```

No forced modal decision.

Let the pending content remain until the user chooses:

```text
Reconnect
Send as Drop
```

---

# 19. Closing / Dismissing a Live context

A disconnected Live context with relevant inbound ephemeral state may be explicitly removed.

Use a clear destructive action such as:

```text
Close Live
```

or

```text
Dismiss Live
```

The exact wording may be chosen for best usability.

When Core allows dismissal:

- remaining Core-owned inbound ephemeral state is destroyed,
- frontend volatile transcript state is discarded,
- context disappears from root LIVE unless new state exists.

If outbound pending Live exists:

- Core rejects dismissal,
- UI must not fake-remove it,
- direct the user to `Reconnect` or `Send as Drop`.

---

# 20. Notification system

## 20.1 No message previews

Absolute rule:

**Never show message body previews in notifications.**

This applies to:

- toast/banner,
- lock screen,
- Notification Center,
- embedded system notification,
- LED/haptic-derived text,
- any custom UI event summary.

Allowed:

```text
Alice
New Drop
```

Not allowed:

```text
Alice
"Meet me at 18:00…"
```

---

## 20.2 Notification Center is volatile

The Notification Center is:

- bounded,
- RAM/volatile,
- profile-scoped,
- presentation-only,
- not communication history.

Do not persist it as a database.

Clear it on:

- UI runtime reset,
- profile switch,
- hard profile lock,
- shutdown,
- purge.

A UI crash may lose info-only notification history.

This is acceptable.

Canonical current state must be reconstructed from Core after reattach.

---

## 20.3 Notification entry model

Use a strict sanitized internal model.

Do not store arbitrary peer-supplied details.

Suggested entry fields:

```text
kind
internal peer identity reference
count
local timestamp
action target
actionable/info classification
```

No:

- message text,
- Voice bytes,
- arbitrary remote strings,
- raw `details` bags,
- peer-controlled markup.

---

## 20.4 Two notification kinds

Keep the model simple:

### State notification

Represents current actionable Core state.

Example:

```text
Bob
Live disconnected · 3 pending
```

It may disappear automatically when the underlying state is resolved.

### Info notification

Represents a transient informational event.

Example:

```text
Bob
3 Live messages sent as Drops
```

It may remain until:

- seen,
- dismissed,
- cleared,
- evicted by the bounded buffer.

Do not build a complex workflow engine.

---

## 20.5 Spam aggregation

Aggregate repeated low-value events such as reconnect churn.

Example:

Instead of:

```text
Disconnected
Connected
Disconnected
Connected
Disconnected
Connected
```

show:

```text
Connection unstable
3 reconnects
```

Aggregate based on a safe local key such as:

```text
kind + peer identity + short time window
```

Do not aggregate away:

- actionable pending state,
- currently pending incoming Live request,
- security/purge/power critical errors.

Bound both:

- entry count,
- total bytes.

Never allow a malicious peer to cause unbounded notification RAM growth.

---

## 20.6 Notification interactions

Root header shows a compact notification affordance and unseen count when appropriate.

Example:

```text
Notifications · 4
```

Opening the Notification Center marks visible entries seen.

Tap an entry -> navigate to current relevant context if available.

Examples:

- new Drop -> peer DROP,
- active/disconnected Live -> peer LIVE,
- pending Live -> peer LIVE,
- fallback info -> relevant peer context.

Long-press:

```text
Dismiss
```

Global:

```text
Clear
```

`Clear` removes only Notification Center entries.

It must never:

- delete messages,
- fallback,
- clear history,
- dismiss Core Live state.

---

## 20.7 Notifications while locked

Setting:

```text
Lock screen notifications

Show all
Anonymize
Off
```

### Show all

May show permitted peer alias/identity metadata and event type.

Example:

```text
Alice
Incoming Live
```

### Anonymize

Show activity type only.

Example:

```text
Incoming Live
```

Do not reveal:

- saved/discovered state,
- alias,
- generated anonymous alias,
- Onion identity.

### Off

Show absolutely no unsolicited notification/call UI while locked.

No:

- incoming call banner,
- activity text,
- notification badge,
- notification-triggered display wake,
- notification-triggered LED/haptic.

However, Core may still perform allowed background policy such as saved-contact auto-accept.

`Off` controls presentation, not network semantics.

---

## 20.8 Missed notification banner after unlock

If notifications occurred while locked, show one compact banner after unlock:

```text
7 notifications while locked
```

Tap -> Notification Center.

Do not create a persistent history merely to support this.

The count may be based on the volatile notification buffer.

---

# 21. Auto-accept vs locked accept vs Auto-play

These are three independent concepts.

## Auto-accept saved contacts

Existing normal Live setting:

```text
Auto-accept Live from saved contacts
```

Core may automatically accept qualifying calls.

---

## Accept Live while locked

Separate device security policy:

```text
Accept Live while locked

All
Saved contacts
None
```

This controls whether the user may press `Accept` without unlocking.

It does not automatically accept anything.

---

## Auto-play

Controls Voice playback only in the eligible foreground Live context.

Do not merge these settings.

---

# 22. Device lock and screen behavior

## 22.1 Normal device lock

Short Power press / configured screen timeout enters the smartphone-like restricted device lock.

The daemon/profile runtime remains active.

On wake, normal UI access requires the configured unlock method.

Do not call Core `LockCommand` for this normal device lock.

Core restricted-client/session state is used.

---

## 22.2 Live while locked

Setting:

```text
Keep Live active while locked
```

When enabled and the user locks while currently in `Alice -> LIVE`:

- Alice remains the single locked foreground Live target,
- physical PTT may still send to Alice,
- Alice Voice may still auto-play if Alice's per-context Auto-play override is ON,
- if Auto-play override is OFF, incoming Voice stays silent/manual,
- incoming Text/Voice remains received,
- status indicator/LED shows locked Live activity.

Do not automatically promote another Live peer.

If Alice disconnects:

- no new locked foreground Live target,
- PTT has no target,
- Bob does not automatically inherit PTT/Auto-play privilege.

---

## 22.3 Lock while not in LIVE

If the user locks from:

- DROP,
- Contacts,
- Settings,
- Notifications,
- root screen,

there is no locked foreground Live target.

Background Live connections may continue, but:

- no Auto-play,
- no PTT target.

---

# 23. Unlock methods

Per profile/device configuration:

```text
PIN
Profile password
None
```

## 23.1 First successful profile entry on Embedded

After the first successful full profile password unlock on the device, prompt once:

```text
Secure this device

Set PIN
Use profile password
No screen lock
```

This is a UI flow over Core auth capabilities.

---

## 23.2 PIN

If PIN is configured:

```text
Enter PIN
```

Provide:

```text
Forgot PIN?
```

`Forgot PIN?` -> full profile password.

After three wrong PIN attempts for the current unlock:

- PIN is no longer accepted,
- require profile password.

Do not auto-purge.

After successful password recovery, PIN remains configured and works again on the next normal device lock cycle.

---

## 23.3 Change lock method

Settings must allow:

- Change PIN,
- Remove PIN,
- use Profile password,
- use None.

Changes use Core auth flows.

Do not store or verify PIN purely inside UI.

---

# 24. Incoming Live while locked

When lock screen notification privacy permits, show call UI.

Example with Show all:

```text
Alice
Incoming Live

[ Decline ] [ Accept ] [ Open ]
```

Example with Anonymize:

```text
Incoming Live

[ Decline ] [ Accept ] [ Open ]
```

### Decline

May be performed without unlock.

### Accept

If `Accept Live while locked` policy allows the caller class:

- accept without unlocking,
- remain locked,
- do not make caller foreground target.

If policy does not allow:

- invoke normal configured unlock method,
- then accept.

### Open

Always needs normal UI unlock.

After successful unlock:

- accept if still pending,
- navigate to peer LIVE.

Use the normal configured unlock method.

Do not introduce a special stronger password requirement.

---

# 25. Profiles

## 25.1 Boot behavior

If a default profile exists, show it as the primary profile.

Example:

```text
METOR

Julian
[ Enter password ]

Switch profile
+ New profile
```

Do not force a profile-picker screen at every boot.

---

## 25.2 Multiple profiles

`Switch profile` opens:

```text
Select profile

Julian
Anonymous
Work

+ New profile
```

Selecting another profile:

```text
Enter <profile> password
```

Cold boot/profile activation always requires the profile password.

PIN is not sufficient to decrypt/start a cold profile.

---

## 25.3 New profile

Creating a new profile must be available from the boot/profile picker.

Do not require an existing profile to be unlocked first.

The exact profile-creation form follows Core profile requirements.

Keep it minimal.

---

## 25.4 Profile switch while running

Settings -> Profiles may switch profile.

If no relevant Live state exists:

- switch without an unnecessary warning dialog.

If relevant state exists:

```text
Switch profile?

2 Live connections active
3 Live messages pending

[ Cancel ] [ Switch ]
```

On `Switch`, Core/client lifecycle performs the safe switch.

The UI must:

- stop/finalize frontend-owned active Voice capture before requesting switch,
- discard current profile's volatile drafts,
- discard current profile's Notification Center,
- discard playback/scroll/UI state,
- authenticate new profile with its password,
- load a fresh authoritative startup snapshot.

If fallback OFF leaves pending Live in old profile:

- returning later to that profile shows disconnected/pending state,
- do not auto-reconnect or auto-fallback.

---

## 25.5 Profile name on lock screen

Setting:

```text
Show profile name on lock screen
```

If OFF:

```text
METOR
Unlock
Switch profile
```

Do not reveal current profile name.

This is presentation-only.

---

# 26. Contacts

## 26.1 Contacts list

Contacts shows **Saved Contacts only**.

Do not include discovered/anonymized peers as a separate "Discovered" address book section.

Root:

```text
CONTACTS                                  +   My QR

Alice
Bob
Charlie
```

---

## 26.2 Contact long-press

Long-press saved contact:

```text
Start Drop
Start Live
Rename
Remove contact
```

Do not clutter the row with permanent action buttons.

---

## 26.3 Rename

Use Core rename.

On success:

- update alias everywhere,
- keep same Onion identity,
- preserve Drop pinning by Onion,
- preserve Live context,
- preserve Drop conversation.

---

## 26.4 Remove contact

User-facing action:

```text
Remove contact
```

Confirmation:

```text
Remove Alice from contacts?

[ Cancel ] [ Remove ]
```

Do not promise physical peer deletion.

Core decides:

- true delete if safe,
- otherwise saved -> discovered/anonymized downgrade.

If Core downgrades:

- remove Alice from Contacts,
- update DROP/LIVE alias to Core-generated anonymous alias,
- active communication may continue.

Optional brief info:

```text
Alice removed from contacts
Active communication continues anonymously
```

Do not preserve the old human alias in hidden UI state after demotion.

---

## 26.5 Discovered/anonymized peer in DROP/LIVE

If an anonymous/discovered peer remains visible because relevant communication exists, long-press/context action may offer:

```text
Save contact
```

Then ask for local alias and promote using Core.

---

## 26.6 Clear all contacts

Under Contacts -> Manage:

```text
Clear all contacts
```

with confirmation.

Rely on Core downgrade/anonymization semantics.

Do not fake-delete peers that Core must retain.

---

# 27. My QR / identity

Contacts exposes a normal everyday action:

```text
My QR
```

Screen:

```text
MY CONTACT

[ QR code ]

<own onion address>

[ Copy ]
```

No need to force the user's local profile/contact alias into the QR if Core identity model does not require it.

Address regeneration is not an everyday action.

Place:

```text
Settings -> Identity -> Generate new address
```

with explicit confirmation and explanation.

---

# 28. History and diagnostics

## 28.1 Privacy settings

Expose normal user-facing privacy settings:

```text
Ephemeral Drops
Record Live history
Record Drop history
Activity history
Clear activity history
```

---

## 28.2 Activity history

Activity history uses the Core projected/user-facing history.

Do not show raw transport rows.

The user should be able to inspect and clear stored metadata.

---

## 28.3 Raw transport history

Only under:

```text
Advanced -> Diagnostics -> Raw transport history
```

This is a technical/debug view.

Do not merge it with normal Activity history.

---

## 28.4 Notification center is not history

Never populate Activity history from Notification Center.

Never persist Notification Center as a substitute for disabled history.

---

# 29. Settings information architecture

Use one mostly flat Settings page with contextual section headings.

Do not structure primary Settings by code ownership such as "UI / Daemon / Core".

Suggested top-level page:

```text
SETTINGS

Live
  ...

Privacy
  ...

Device
  ...

Profiles
  ...

Advanced
  >
```

The section headings are visual grouping, not additional navigation screens unless necessary.

Only `Advanced` is intentionally a deeper technical area.

---

# 30. Settings mapping

The exact final rendering may adapt to available descriptors from Core, but the semantic placement below is normative.

## 30.1 Live

Normal:

```text
Auto-play default
Fallback to Drop
Receive Drops
Auto-accept Live from saved contacts
Keep Live active while locked
Accept Live while locked
Send read receipts
```

`Send read receipts` defaults OFF.

Do not merge Auto-accept, locked acceptance, and Auto-play.

---

## 30.2 Privacy

Normal:

```text
Ephemeral Drops
Record Live history
Record Drop history
Lock screen notifications
Activity history
Clear activity history
```

`Lock screen notifications`:

```text
Show all
Anonymize
Off
```

---

## 30.3 Device

Normal:

```text
Screen timeout
Unlock method
Change PIN              (when applicable)
Voice buffer limit
Show profile name on lock screen
Keyboard layout
```

Other local platform settings may appear if actually supported and useful, e.g.:

```text
Volume
Haptics
Brightness
```

Do not invent settings unsupported by platform capabilities.

---

## 30.4 Profiles / Identity

Normal:

```text
Current profile
Switch profile
Default profile
Add profile
Rename profile
Remove profile
Change profile password
My address
Generate new address
```

---

## 30.5 Advanced

Place technical tuning here, not in the normal UI:

```text
unseen DROP/LIVE limits
pending LIVE count/byte limits
max concurrent connections
reconnect/grace/retry timings
idle timeouts
drop tunnel cache/standby
reuse-live-for-drops
IPC limits/timeouts
external notification sink
rejection-policy details
Raw transport history
```

Only expose a setting if Core's descriptor says it is available/safe for the deployment.

---

## 30.6 Not exposed on hardened Embedded

Do not render development/debug-dangerous options in normal hardened builds:

```text
Tor logging
SQL logging
runtime plaintext DB mirror
plaintext-profile development enablement
raw internal daemon-port wiring
remote-profile internals not meaningful on device
```

These may remain CLI/config capabilities.

---

# 31. Notification sink safety

If external notification sinks are exposed under Advanced:

- show a clear privacy warning,
- make clear they may export metadata,
- never add message body/Voice previews,
- keep default disabled.

Do not automatically enable file/webhook sinks on Embedded.

---

# 32. Software keyboard

## 32.1 General

The software keyboard is simple and local.

Requirements:

- touch-first,
- no network dependency,
- no cloud suggestions,
- no telemetry,
- no learned remote dictionary,
- layouts at least QWERTY/QWERTZ,
- special characters/numbers accessible.

The exact keyboard visual style may be minimal, but it must be usable on the target display.

---

## 32.2 Appearance/disappearance

Keyboard appears when a text composer is focused.

Keyboard disappears when:

- PTT begins,
- Drop Voice review is active,
- user dismisses it,
- user leaves the view.

In LIVE, after PTT release:

- keyboard/text composer becomes available again.

In DROP, after PTT release:

- remain in Voice review,
- keyboard returns only after Send or Delete.

---

# 33. Global Back behavior

Every pushed screen has a visible Back affordance.

Optional left-edge swipe may be added as convenience.

Never make a gesture the only way to go Back.

Back:

- changes view only,
- does not end Live,
- does not reconnect,
- does not fallback,
- does not retunnel.

Examples:

```text
Alice LIVE -> Back -> root LIVE
Alice DROP -> Back -> root DROP
Settings -> Back -> previous/root
Contacts -> Back -> previous/root
Notifications -> Back -> previous/root
```

If PTT is held and Back changes the Live communication context:

- finalize current Voice turn,
- require PTT release before re-arm.

---

# 34. Power and device lifecycle

## 34.1 Short Power press

Short Power:

```text
screen off / normal device lock
```

The daemon remains running.

---

## 34.2 Long Power press

Keep the normal power menu minimal:

```text
Power off
Cancel
```

Do not expose a redundant user-facing "Secure Lock" state unless a real future use case requires it.

Core hard `LockCommand` remains an internal/lifecycle primitive.

---

## 34.3 Normal Power off

Normal power-off is reliability-preserving.

UI responsibilities:

1. if local PTT/recording is active, finalize it cleanly,
2. request Core graceful profile exit/power-off preparation,
3. wait only for Core confirmation that local state transition/persistence is safe,
4. do not wait for remote Drop delivery,
5. invoke platform shutdown.

Do not show transport-level details.

---

# 35. Purge / Emergency self-destruct

Purge is not a normal menu action.

Trigger:

```text
Power + PTT long hold
```

Exact hold duration is a platform/spec constant chosen to prevent accidental activation.

Provide unmistakable physical feedback while arming, preferably:

- LED,
- haptic,
- minimal screen cue if screen is available.

Once the arming threshold is crossed:

- issue Core SelfDestruct immediately,
- do not finalize PTT for delivery,
- do not fallback,
- do not reconnect,
- do not generate normal notifications,
- do not ask another UI confirmation,
- do not wait for network.

After Core destruction-completion signal / deterministic daemon exit:

- request device shutdown immediately.

Do not cut power before Core reaches the documented irreversible key-destruction milestone.

Purge has higher priority than reliability.

---

# 36. Status LED / hardware indicator

Implement through a platform abstraction, not direct UI GPIO calls.

At minimum support semantic states such as:

```text
off
locked_live_active
transmitting
receiving
purge_arming
critical_error
```

Keep patterns simple.

Do not create dozens of undocumented blink codes.

For `Lock screen notifications = Off`:

- unsolicited notification activity must not trigger identifying/attention LED behavior.

For an explicitly continued `Live while locked` session:

- status LED may indicate that Live remains active.

---

# 37. UI restart behavior

If the Embedded UI process restarts while daemon remains alive:

Discard frontend-only volatile state:

- Notification Center,
- drafts,
- consumed Live scrollback,
- scroll positions,
- playback positions,
- keyboard state.

Then:

1. establish client/IPC session,
2. authenticate as required,
3. subscribe to events,
4. obtain authoritative race-safe startup snapshot,
5. apply revision rules,
6. render current state.

Do not reconstruct old UI notifications from Core history.

Do not auto-reconnect.

Do not auto-fallback.

---

# 38. Daemon/profile restart behavior

After daemon/profile restart:

- active sockets are gone,
- durable pending/unseen state may remain,
- root LIVE should show relevant disconnected/pending/new contexts from Core snapshot,
- no automatic reconnect merely because UI started.

Example:

```text
LIVE

Bob
disconnected · 3 pending

Alice
2 new
```

User explicitly chooses next action.

---

# 39. Empty states

Keep empty states minimal and useful.

Examples:

## Empty DROP

```text
No Drop conversations

[ + Start Drop ]
```

## Empty LIVE

```text
No Live activity

[ + Start Live ]
```

## Empty Contacts

```text
No contacts

[ + Add contact ]
```

## Empty Notifications

```text
No notifications
```

No illustrations are required.

---

# 40. Loading and startup states

Avoid complex skeleton interfaces.

Use small clear status text:

```text
Starting Metor…
Connecting to daemon…
Unlocking profile…
Loading…
```

Do not show low-level IPC/Tor technical wording unless in Diagnostics.

If the authoritative startup snapshot cannot be obtained:

- show a recoverable error,
- allow retry where safe,
- do not render stale partial communication state as authoritative.

---

# 41. Error language

User-facing errors should describe the action/state, not implementation internals.

Good:

```text
Could not start Live
Connection lost
Could not change route
Message not sent
Voice buffer full
```

Avoid:

```text
Socket error
Tunnel unavailable
IPC request failed
Tor frame invalid
```

Technical details may be available in Advanced Diagnostics/logs.

---

# 42. Live system events and notifications

Use typed Core reason/actor information.

Examples:

System backlog-limit termination:

```text
Live with Alice ended
Unread Live limit reached
```

Idle timeout:

```text
Live with Alice ended
Inactive connection timed out
```

Peer ended:

```text
Alice ended Live
```

Local user ended:

```text
Live ended
```

Do not infer reason from strings.

---

# 43. End Live

`End Live` is an explicit action available inside LIVE.

Also available from root LIVE context actions.

Do not require a confirmation for ordinary End Live unless destructive/pending conditions require user attention.

If Core reports pending state that cannot be discarded:

- surface the relevant pending/fallback choice,
- do not invent a "Discard pending" action.

Do not terminate Live by Back.

---

# 44. Auto-fallback feedback

When Core auto-fallbacks pending Live content, never do it silently.

Use a compact notification/banner:

```text
Alice
3 Live messages sent as Drops
```

No content preview.

Tap may open Alice context.

If auto-fallback occurs while another screen is visible, notification behavior follows lock/privacy/presentation rules.

---

# 45. Fallback OFF behavior

If Live disconnects and Auto-fallback is OFF:

- pending content remains,
- root LIVE shows the context,
- notification may say:

```text
Alice
Live disconnected · 3 pending
```

No forced modal.

The user decides later.

---

# 46. Read receipts

Expose setting:

```text
Send read receipts
```

Default OFF.

When OFF:

- do not show remote peers that you read their messages because Core does not send receipts.

For messages you send:

- do not display `Unread` as a negative fact when no read receipt arrives.
- absence of READ means unknown.

Minimal outbound status presentation:

- show `pending` / `failed` when important,
- optionally show subtle delivered/read indicators if available,
- avoid persistent verbose status text under every successful message.

If a real remote read receipt arrives and the setting/protocol allows it:

- a subtle Read state may be displayed.

---

# 47. Message status minimalism

Do not copy WhatsApp's multi-checkmark language unless clearly useful.

Prefer:

- visible `pending` when unresolved,
- visible `failed` when action required,
- subtle delivered/read state when meaningful,
- no permanent noise for normal successful messages.

---

# 48. Reply/Quote

Do not implement Reply/Quote in V1.

No swipe-to-reply.

No quote metadata.

No placeholder code paths.

It can be added later without changing the current architecture.

---

# 49. Pinning

Pinning applies only to root DROP conversations.

Do not pin:

- Contacts,
- LIVE contexts,
- Notifications.

Pin state is frontend-local and keyed by Onion identity.

Use long-press:

```text
Pin
Unpin
```

---

# 50. Destructive actions

## 50.1 Single Drop message

Long-press -> `Delete`.

Local only.

---

## 50.2 Drop conversation

Long-press root row -> `Delete conversation`.

DROP-only.

---

## 50.3 All conversations

Settings/Privacy/Data may expose:

```text
Clear all conversations
```

Meaning:

```text
clear all DROP conversations
```

Never implicitly clear LIVE state.

---

## 50.4 Activity history

```text
Clear activity history
```

Only clears projected activity/history metadata.

---

## 50.5 Contacts

```text
Clear all contacts
```

Uses Core demotion/delete semantics.

---

## 50.6 Clear profile DB

Do not expose as a normal Embedded UI action.

It is too technical and overlaps with clearer actions.

---

## 50.7 Purge

Hardware emergency path only.

---

# 51. Saved vs discovered peer UX

The UI must never force the user to understand "discovered peer" as a top-level feature.

Saved peers:

- appear in Contacts.

Discovered/anonymized peers:

- may appear in DROP/LIVE if relevant,
- use the Core-provided anonymous alias,
- can be saved from their context.

Do not create a "Discovered" Contact section.

---

# 52. QR contact flows

## 52.1 Contacts `+`

Flow:

```text
Contacts +
    -> Scan QR / enter supported contact data
    -> validate
    -> choose local alias
    -> Save Contact
```

No automatic Drop/Live action afterward.

---

## 52.2 DROP `+`

Flow:

```text
DROP +
    -> saved contact picker / Scan QR
    -> new peer alias
    -> Save & Open Drop
```

---

## 52.3 LIVE `+`

Flow:

```text
LIVE +
    -> saved contact picker / Scan QR
    -> new peer alias
    -> Save & Start Live
```

This preserving of original intent is required.

---

# 53. Content ordering during PTT

When PTT begins, create the local Voice placeholder at that chronological point.

If remote text arrives while speaking:

```text
You
Voice · transmitting…

Alice
Use the back entrance.
```

When PTT ends, do not reinsert/move the Voice item later.

The visual chronology remains stable.

---

# 54. PTT and composer exclusivity

Although the communication model is full duplex, the local composer intentionally becomes single-mode while local PTT is held.

During PTT:

- keyboard hidden,
- local text composer unavailable,
- recording timer visible,
- incoming communication remains visible/playable.

This is a deliberate UX choice, not a Core restriction.

---

# 55. Voice buffer UI

The local Voice retention budget is a configurable resource limit.

At approximately 90%:

```text
Voice buffer almost full
```

At hard limit while recording:

- Core finalizes/stops according to contract,
- UI shows:

```text
Voice buffer full
Release PTT to continue
```

The physical PTT press is consumed until release.

If the total buffer remains full after release:

- new PTT starts are disabled,
- show:

```text
Voice buffer full
Reconnect or send pending as Drop
```

Do not silently delete/overwrite retained Voice.

After fallback frees Live Voice capacity, PTT may become available again.

---

# 56. Locked foreground Live and notification privacy interaction

Explicitly continued `Live while locked` is not the same as unsolicited lock-screen notification activity.

Therefore:

- `Lock screen notifications = Off` does not stop an explicitly continued locked Live target.
- that target may still use PTT/Auto-play according to `Keep Live active while locked` and per-context Auto-play.
- unrelated incoming calls/notifications remain hidden when Off.

Do not conflate these settings.

---

# 57. Auto-accepted Live behavior

If Core auto-accepts a saved contact:

- show a normal notification if current presentation/privacy permits,
- do not auto-navigate,
- do not auto-promote that peer to foreground,
- no Auto-play while background.

If the user is already in that peer's LIVE context and the connection becomes active:

- the view remains foreground,
- Auto-play eligibility follows that peer's current override/default.

---

# 58. Notification navigation

Tapping a notification must follow current state, not stale historical assumptions.

Examples:

If a notification says:

```text
Bob
3 pending
```

but Core now reports zero pending:

- do not show a stale "3 pending" UI,
- navigate to Bob's current LIVE state or remove the state notification.

If the target peer/context no longer exists:

- dismiss entry gracefully.

Do not crash because a volatile notification outlived the Core state it referenced.

---

# 59. Profile isolation

All frontend transient data is profile-scoped.

On profile switch discard:

- DROP drafts,
- LIVE drafts/transcripts,
- Notification Center,
- pins for the old profile from active in-memory cache,
- playback cursors,
- current selection.

Persistent UI preferences such as pins may be stored locally per profile identity, but must never cross-display between profiles.

Do not show profile A peer metadata while profile B is active.

---

# 60. Secure local UI data storage

If frontend-local persistent preferences are needed (e.g. pinning, keyboard layout, local presentation choices):

- store only minimum necessary metadata,
- avoid message content,
- scope by profile identity,
- do not include secret keys,
- do not include message bodies,
- do not create an alternate contact database.

Use Core settings where the preference is semantically shared across frontends/devices; use local UI storage only for presentation-specific preferences.

---

# 61. Platform abstraction requirements

Agent 2 must implement/adapt platform ports cleanly.

Required areas:

```text
Display
Touch input
Hardware PTT input
Power button
Audio capture
Audio playback
AEC / audio session
Camera / QR scanning
Status LED / indicator
Haptics (if supported)
Local shutdown
```

Do not let UI view-models call GPIO/audio libraries directly.

Provide simulator/mock implementations so the Embedded UI can be exercised on a desktop development environment.

---

# 62. Desktop/simulator mode

The Embedded UI must be runnable in a simulator/development environment without target hardware.

Simulate:

- touch,
- PTT press/release,
- power/screen lock,
- status LED state,
- audio input/output where feasible,
- QR scan injection.

Do not create a separate product UX for simulator.

The simulator should exercise the same UI code and client contract.

---

# 63. Theme / visual style

Design direction:

- minimal,
- high contrast,
- large touch targets,
- restrained color usage,
- no decorative clutter,
- no unnecessary gradients,
- clear status hierarchy,
- predictable spacing.

Do not sacrifice legibility for visual novelty.

Do not use transport/security jargon as decorative badges.

The UI should still be understandable in a low-color or monochrome-ish implementation if needed.

---

# 64. Accessibility / touch ergonomics

At minimum:

- sufficiently large touch targets,
- readable text on the target screen size,
- no critical action available only by tiny icon,
- long-press actions must also be discoverable through contextual affordance where necessary,
- destructive actions require clear wording,
- recording state must be unmistakable,
- lock/purge states must not be visually ambiguous.

---

# 65. Suggested screen inventory

The implementation should remain compact.

Canonical screen/state inventory:

```text
Boot / profile unlock
Profile picker
New profile
First-run unlock method setup
Device lock screen
Root DROP
Root LIVE
Peer DROP
Peer LIVE
Live calling
Live reconnecting
Disconnected Live
Drop Voice review
Notifications
Contacts
Add/Scan contact
My QR
Settings
Activity history
Advanced
Diagnostics/raw history
Profile management
Identity/address
Power-off transition
Purge arming/destruction state
```

Many are states of the same view rather than separate heavyweight pages.

Do not explode this into dozens of unrelated screens.

---

# 66. State-driven rendering

Prefer state machines/view models over imperative "show/hide this widget from random callbacks".

Important UI state machines include:

```text
Root projection:
DROP | LIVE

Peer projection:
DROP | LIVE

Live connection:
idle
calling
connecting
active
reconnecting
disconnected
closing

PTT:
idle
recording
finalizing
release_required
blocked_by_buffer

Drop Voice:
idle
recording
review

Device auth:
unlocked
restricted_locked
authenticating
pin_escalated_to_password

Incoming Live:
none
pending
accepted_background
opened

Notification:
state
info
seen/unseen
```

These are UI state names; Core remains authoritative for domain facts.

---

# 67. Core event handling

Event handling must be:

- typed,
- idempotent,
- revision-aware,
- resilient to out-of-order/stale state per Core contract.

Do not derive persistent truth solely from event order.

On any event that invalidates current state:

- reconcile with Core snapshot/query where required.

Examples:

- rename,
- contact downgrade,
- Live disconnect,
- fallback success,
- message clear,
- profile switch.

---

# 68. Terminal parity requirement

The Embedded UI may provide richer UX, but it must not reinterpret Core semantics differently from Terminal.

Examples:

- fallback means the same thing,
- `msg_id` identity means the same thing,
- contact demotion means the same thing,
- `LockCommand` means the same hard Core lock,
- read receipts mean the same protocol concept.

Do not add an Embedded-only alternate meaning to shared commands.

---

# 69. Explicit Embedded-only presentation features

The following are intentionally frontend-specific and should not be pushed back into Core unless correctness/security requires it:

```text
Drop pinning
notification-center RAM store
notification coalescing presentation
scroll positions
n-new indicator
software keyboard visuals
draft text
current playback cursor
per-Live-context auto-play override
lock-screen profile-name visibility
visual theme
touch gestures
iconography
```

Core security enforcement still applies for locked client permissions.

---

# 70. Explicit non-goals for V1

Do not implement unless separately approved:

- Reply/Quote,
- forwarding received Live content,
- delete-for-everyone,
- message reactions,
- typing indicators,
- presence/online indicator beyond actual Live state,
- user avatars,
- rich link previews,
- cloud autocomplete,
- stickers/GIFs,
- group chats,
- group Live/PTT,
- file transfer UI beyond what future Core may require,
- arbitrary theme marketplace,
- extensive animation,
- webview-based main UI,
- transport selection UI.

---

# 71. End-to-end acceptance scenarios

Agent 2 is not complete until these scenarios work against the post-Agent-1 Core.

## Scenario 1 - Root navigation

1. Unlock.
2. Root opens on DROP.
3. Switch to LIVE.
4. Open Contacts.
5. Back.
6. Open Settings.
7. Back.
8. Open Notifications.
9. Back.
10. Verify no communication state changed because of navigation.

---

## Scenario 2 - Start DROP via QR

1. Root DROP -> `+`.
2. Scan new peer.
3. Enter alias.
4. CTA reads semantically `Save & Open Drop`.
5. Save.
6. Open peer DROP immediately.
7. Peer does not appear in root DROP until real persistent communication exists.

---

## Scenario 3 - Start LIVE via QR

1. Root LIVE -> `+`.
2. Scan new peer.
3. Enter alias.
4. `Save & Start Live`.
5. Save.
6. Live call begins immediately.

---

## Scenario 4 - Multiple Live connections

1. Alice LIVE active.
2. Bob LIVE active in background.
3. Alice is foreground with Auto-play ON.
4. Verify only Alice may Auto-play.
5. Switch to Bob.
6. Verify Alice immediately loses Auto-play eligibility.
7. Return to Alice.
8. Verify her per-context override remains.

---

## Scenario 5 - Incoming call while in another context

1. Alice DROP open.
2. Bob calls.
3. Global call overlay appears.
4. `Accept`.
5. Bob becomes connected in background.
6. Alice DROP remains visible.
7. Bob does not Auto-play.
8. Repeat with `Open`.
9. Verify navigation to Bob LIVE.

---

## Scenario 6 - PTT and context switch

1. Alice LIVE foreground.
2. Hold PTT.
3. Incoming Bob call -> `Open`.
4. Alice Voice finalizes.
5. Navigate to Bob LIVE.
6. While PTT still physically held, Bob recording does not start.
7. UI shows `Release PTT`.
8. Release.
9. Press again.
10. New Bob Voice begins.

---

## Scenario 7 - LIVE full duplex

1. Hold PTT to Alice.
2. Alice sends Text during local recording.
3. Alice sends Voice during local recording.
4. Both remain visible/processable.
5. Local keyboard remains hidden during own PTT.
6. Release.
7. Text composer returns.

---

## Scenario 8 - Manual Voice timeshift

1. Auto-play OFF.
2. Alice begins a 20-second Voice turn.
3. At second 10, tap the active Voice.
4. Playback starts from beginning.
5. Alice continues streaming.
6. `LIVE` jump appears.
7. Tap `LIVE`.
8. Playback catches/jumps to live edge.

---

## Scenario 9 - Live scroll anchoring

1. Scroll up.
2. Alice sends several items.
3. View does not jump.
4. `3 new ↓` appears.
5. Tap.
6. View returns to Live edge.

---

## Scenario 10 - DROP Voice review

1. Alice DROP.
2. Hold PTT.
3. Keyboard hides.
4. Release.
5. Voice is not sent.
6. Review shows Play/Delete/Send.
7. Play works locally.
8. Send sends Drop.
9. Keyboard/composer returns.

---

## Scenario 11 - Reconnect Voice

1. Alice LIVE.
2. Hold PTT.
3. Network drops.
4. UI shows `Reconnecting…`.
5. Recording continues.
6. Network returns.
7. Core resumes stream.
8. UI stays same Live context.
9. Auto-play override unchanged.

---

## Scenario 12 - Buffer pressure

1. Voice buffer reaches 90%.
2. Warning appears.
3. Reach hard limit while PTT held.
4. Recording finalizes/stops.
5. UI shows `Release PTT`.
6. Release.
7. If still full, PTT disabled with clear action text.
8. Fallback one pending Voice.
9. Capacity frees.
10. PTT becomes available.

---

## Scenario 13 - Fallback OFF

1. Alice Live disconnects.
2. Three own items pending.
3. No modal appears.
4. Root LIVE shows `Alice · disconnected · 3 pending`.
5. Open Alice LIVE.
6. `Reconnect` and `Send 3 as Drop` available.
7. Long-press one pending item -> `Send as Drop`.

---

## Scenario 14 - Delivered resend

1. Own LIVE text is delivered.
2. Long-press.
3. Option says `Resend as Drop`.
4. New Drop is created with new identity.
5. Original LIVE semantics remain unchanged.

---

## Scenario 15 - Auto-fallback feedback

1. Pending Live exists.
2. Recovery fails.
3. Auto-fallback ON.
4. Core promotes.
5. UI shows sanitized info notification:
   `3 Live messages sent as Drops`.
6. No message preview.

---

## Scenario 16 - Backlog overflow

1. Core ends Live due unseen backlog limit.
2. Local affected UI shows system reason.
3. Remote UI shows only generic disconnect/end.
4. No peer-local quota details leak remotely.

---

## Scenario 17 - Contact rename

1. Alice Drop pinned.
2. Rename Alice -> Anna.
3. Pin remains.
4. Drop/Live contexts update alias.
5. Same conversation identity remains.

---

## Scenario 18 - Contact downgrade

1. Saved Alice has relevant Live/Drop state.
2. Remove Contact.
3. Alice disappears from Contacts.
4. Core-generated anonymous alias appears in relevant Drop/Live.
5. Communication state remains valid.
6. Old alias is not retained in UI.

---

## Scenario 19 - Save discovered peer

1. Anonymous peer exists in LIVE.
2. Long-press/context -> Save contact.
3. Enter alias.
4. Promote via Core.
5. Saved alias appears everywhere.

---

## Scenario 20 - Lock with Live while locked

1. Alice LIVE foreground.
2. Auto-play ON.
3. `Keep Live active while locked` ON.
4. Lock device.
5. Screen off.
6. Alice remains PTT target.
7. Alice audio may Auto-play.
8. Bob remains background.
9. Bob never steals target.

Repeat with Alice Auto-play OFF and verify inbound audio remains silent.

---

## Scenario 21 - Lock from non-Live

1. Bob Live active in background.
2. User is in Settings.
3. Lock device.
4. No PTT target.
5. Bob cannot Auto-play.

---

## Scenario 22 - Incoming Live on lock screen

Test `Show all`, `Anonymize`, `Off`.

For `Show all`:

- peer identity may appear.

For `Anonymize`:

- show only `Incoming Live`.

For `Off`:

- no lock UI/LED/haptic notification.

Verify `Accept Live while locked` policies.

---

## Scenario 23 - Unlock method

Test:

- PIN,
- Profile password,
- None.

For PIN:

- three wrong attempts -> password required,
- Forgot PIN -> password,
- successful password recovery -> next normal lock may use PIN again.

---

## Scenario 24 - Profile switch

1. Current profile has active/pending Live.
2. Switch from Settings.
3. Relevant-state warning appears.
4. Confirm.
5. Active local PTT finalizes normally.
6. UI volatile state clears.
7. New profile password required.
8. New snapshot loads.
9. No old-profile notifications/data leak.

---

## Scenario 25 - Return to profile with pending

1. Profile A has 3 pending Live, fallback OFF.
2. Switch to B.
3. Switch later back to A.
4. After password/snapshot, root LIVE shows disconnected/pending.
5. No auto-reconnect.
6. No auto-fallback.

---

## Scenario 26 - Power off

1. PTT active.
2. Long Power -> Power off.
3. Current recording finalizes.
4. Core performs graceful local transition.
5. UI does not wait for remote Drop delivery.
6. Platform shutdown occurs after safe Core completion.

---

## Scenario 27 - Purge

1. Multiple active Live sessions.
2. PTT held.
3. Pending Live exists.
4. Hold Power + PTT past purge threshold.
5. No fallback.
6. No Voice delivery finalization.
7. No reconnect.
8. Destruction begins immediately.
9. Platform shutdown only after Core irreversible-destruction completion signal.

---

## Scenario 28 - UI crash/restart

1. Alice Live with consumed transcript.
2. Bob pending Live.
3. Drop draft exists.
4. Notification Center has entries.
5. Crash UI.
6. Restart UI.
7. Draft gone.
8. Notification Center gone.
9. consumed Alice frontend transcript gone.
10. Bob pending restored from Core snapshot.
11. no auto-reconnect.

---

## Scenario 29 - Privacy settings

With:

```text
Ephemeral Drops = ON
Record Live history = OFF
Record Drop history = OFF
```

verify:

- Notification Center never persists history,
- no message previews,
- consumed ephemerals are not recreated after UI restart,
- Activity history reflects Core's configured policy only.

---

## Scenario 30 - Read receipts

Default OFF:

- local read works,
- UI does not claim remote unread/read without evidence.

Enable:

- real remote ReadReceipt may show subtle Read state.

---

# 72. Testing requirements

Agent 2 must add:

- view-model/state-machine tests,
- client integration tests against post-Agent-1 typed contracts,
- simulator tests for PTT/power/lock,
- notification privacy tests,
- profile-isolation tests,
- UI-restart tests,
- resource-pressure UI tests,
- regression tests for navigation invariants.

Prefer deterministic state-machine tests over screenshot-only tests.

Where screenshot/golden tests are useful, keep them secondary.

---

# 73. Security review checklist

Before completion verify:

- no message content in notifications,
- no Notification Center persistence,
- no raw peer-controlled markup rendering,
- no UI-only PIN verification,
- no unrestricted IPC calls while restricted/locked,
- no target switching during held PTT,
- no automatic networking from navigation,
- no old-profile state leakage,
- no persistent Live transcript side store,
- no accidental plaintext DB mirror/debug setting exposed,
- no purge delay caused by normal reliability flows,
- no profile name leak when hidden,
- no alias leak under lock-screen Anonymize,
- no lock-screen activity under Off.

---

# 74. UX review checklist

Before completion verify:

- no bottom nav,
- no extra Home screen,
- `DROP | LIVE` used consistently,
- all critical actions reachable without hidden-only gestures,
- Long-press used for contextual secondary actions,
- incoming Live always understandable,
- recording state unmistakable,
- Drop Voice review clear,
- Auto-play state understandable,
- disconnected/pending state actionable,
- root LIVE meaningful with multiple connections,
- no transport jargon,
- Settings mostly flat,
- Advanced keeps technical tuning out of normal path.

---

# 75. Definition of done

Agent 2 is complete only when:

- the Embedded UI implements this full spec,
- it consumes the post-Agent-1 Core/client contract without domain workarounds,
- root DROP/LIVE navigation is complete,
- peer DROP/LIVE projection switching is complete,
- text and Voice flows work,
- PTT hardware behavior follows target-binding/re-arm rules,
- full-duplex Live behavior works,
- Manual/Auto-play works,
- reconnect/resume/fallback UI works,
- multiple Live contexts work,
- disconnected/pending Live states remain manageable,
- Contacts/QR/rename/remove/demotion flows work,
- Notification Center is bounded/volatile/privacy-safe,
- lock-screen Show all/Anonymize/Off work,
- PIN/password/None unlock flows work,
- Live while locked works without target switching,
- profile switch works,
- My QR works,
- Settings mapping is complete,
- Activity history/Advanced diagnostics are correctly separated,
- power-off lifecycle works,
- purge hardware flow works,
- UI restart/state rehydration works,
- simulator mode works,
- no V1 non-goals were added,
- all tests pass,
- formatting/lint/type checks pass,
- generated/reference docs are updated where Embedded implementation docs require it.

At this point the final Embedded UI is ready for hardware integration/testing and later visual polish without changing the frozen product semantics.
