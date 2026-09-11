# METOR GUI LAYOUT SPECIFICATION

**Version:** 0.2 — design and handoff draft  
**Date:** 11 September 2026  
**Functional baseline:** `METOR_GUI_SPEC.md` v1.0  
**Visual baseline:** Penpot revision `METOR GUI v0.7 · shared spacing and optical alignment`  
**Suggested repository destination:** `docs/specs/METOR_GUI_LAYOUT_SPEC.md`  
**Language:** English for documentation, implementation identifiers and application copy.

> Implement relationships, content sizing and state rules. A screenshot is a reference for visual judgment, not a collection of independent coordinates.

## 1. Authority and readiness

This draft captures the design decisions developed in the Penpot review through v0.7. It complements the functional specification; it does not replace it or certify that the complete implementation-facing design packet is finished.

| Source | Authority |
| --- | --- |
| `METOR_GUI_SPEC.md` v1.0 | Navigation meaning, action eligibility, communication and media lifecycle, privacy, authorization, persistence, platform behavior and functional acceptance |
| This companion | Component composition, sizing, spacing, typography, visual state presentation, understandable labels and visual acceptance |
| Accepted public Core/SDK contract | Actual imports, commands, results, identities and integration boundaries |
| Pinned Penpot references / future repository renders | Visual examples of the specified state and content |
| `GUI_PLATFORM_ADR.md` | Toolkit/runtime proof, display/input adapters, density mapping and platform implementation |

Kivy with a small Metor UI kit is the agreed technical direction. The functional specification still requires the platform ADR and vertical slice. Do not introduce a webview or a second GUI product because the reference can be exported as an image or SVG.

If an example and a functional requirement conflict, correct the example. If a layout decision changes behavior, version the functional contract first. The old `docs/.temp/EMBEDDED_UI_SPEC.md` is historical and must not be merged back into the assignment.

Source provenance: the two available copies of the functional v1.0 file were byte-identical, SHA-256 `8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7`.

**Readiness:** the component rules below are concrete design input. Section 8 explicitly identifies incomplete view/state coverage. Exported local assets, complete interaction/focus references and repository golden fixtures remain to be delivered before this becomes the complete approved companion required by functional section 21. Do not interpret a coverage-board entry as a finished screen.

## 2. Visual principles

1. **Perceived balance is the acceptance criterion.** Equal bounding-box gaps can look unequal because of letter shapes, capitalization, font size and weight. Judge the rendered composition at its intended size.
2. **Content determines height.** Free space belongs to the timeline or viewport, not inside an artificially stretched message or notice.
3. **Related elements form one unit.** Name plus status, icon plus label, and text plus metadata must read as a group. Adjust the group before tuning individual pixels.
4. **Shared content edges stay shared.** Notices must not protrude beyond adjacent lists and selectors without a deliberate, documented full-width role.
5. **One visible affordance per purpose.** Timeline scrolling and audio seeking are different actions. Their location and wording must explain the difference.
6. **The GUI is universal.** Everyday controls name the action, not a presumed physical button, operating system or device. Hardware-specific instructions appear only in a genuinely configured hardware flow, such as the authorized purge chord.
7. **Status is restrained and truthful.** Color supports words and icons; it does not invent delivery, presence, authorization or playback facts.

Local optical adjustments belong to a named component rule, not to scattered per-screen offsets. Never shrink text to make an undersized control appear to fit.

## 3. Display contract

All dimensions below are **logical design units**, not verified physical display pixels or hardware claims.

| Reference | Current composition |
| --- | --- |
| Device / portrait | 480 × 800 content viewport |
| Small portrait | 360 × 640 content viewport |
| Desktop | 1180 × 760 content viewport; 360-unit master pane, divider and remaining detail pane |
| Screen / pane outer inset | 24 on each edge for header controls, ordinary content and bottom-anchored controls |
| Device content width | 432 or 312, after two 24-unit side insets |
| Desktop detail content | 24 on each side; 771 usable units in the current 819-unit detail pane |
| Ordinary header | Actions start 24 from the top and are 48 high; following content starts at 88 or later |
| Primary content separation | Usually 16 or 24, according to grouping |

The outer black presentation cards, captions, frame labels and illustrative physical-button markers are documentation, not application chrome. Export the inner viewport for implementation golden images.

The desktop resizing breakpoint, minimum desktop window, landscape behavior, scale/density mapping, safe-area treatment and keyboard-visible small-screen composition require explicit closure before release of the full packet. Do not infer an arbitrary breakpoint from the two desktop drawings. Preserve one foreground peer and the same DROP/LIVE semantics when changing arrangement.

## 4. Tokens and assets

### 4.1 Current color palette

| Token | Value | Role |
| --- | --- | --- |
| `color.background` | `#101619` | Main application background |
| `color.surface` | `#171F22` | Rows, cards and composer surface |
| `color.raised` | `#202A2E` | Secondary controls / incoming media surface |
| `color.line` | `#334247` | Separators and restrained outlines |
| `color.text` | `#F3F7F6` | Primary text |
| `color.textSecondary` | `#9AA9AD` | Supporting information |
| `color.textDisabled` | `#68777B` | Disabled treatment; pair with explicit eligibility |
| `color.drop` | `#4ED7C8` | DROP accent |
| `color.dropSurface` | `#123B38` | DROP tint |
| `color.live` | `#FFB454` | LIVE accent |
| `color.liveSurface` | `#432E16` | LIVE tint |
| `color.danger` | `#FF6474` | Destructive action / error |
| `color.dangerSurface` | `#471E27` | Destructive tint |
| `color.success` | `#72D68C` | Positive status |
| `color.info` | `#78AFFF` | Informational / recovery accent |
| `color.lock` | `#C5B4FF` | Restricted / privacy context |
| `color.onAccent` | `#070A0B` | Text and icons on bright accent fills |

These are the current reference colors, not a claim that every possible state pairing has passed accessibility testing. Verify actual foreground/background combinations, disabled readability and focus visibility in the final packet.

### 4.2 Sizing and typography

The current Penpot text uses **Inter Tight** (`gfont-inter-tight`), not an unspecified Inter substitution.

| Token / role | Current reference value |
| --- | --- |
| Spacing scale | 4 / 8 / 12 / 16 / 24 |
| Message body | 15, weight 400, line height 20 |
| Message metadata | 11, weight 500, line height 14 |
| Conversation name | 17 with stronger weight than supporting status |
| Conversation supporting status | 13 |
| Peer header name | 20 |
| Simple page title | 23 on 480 reference; 22 on small reference |
| Ordinary action target | At least 48 × 48 |
| Passive status pill | 28 high; natural text width plus horizontal padding |
| Message radius | 16 |
| Standard icon/action radius | 12 |
| Selector height | 48; internal selected fill inset 4 |
| LIVE composer height | 64 |
| LIVE composer action slot | 148 × 48, inset 8 vertically and from right edge |

Passive pills are not 28-high buttons. A clickable action retains an adequate hit area. The selector's inner 40-high fill is decoration; the selectable half uses the full control height.

Before the final handoff, export named tokens and actual font/icon assets to the repository, include font and icon licensing/provenance, and define permitted fallbacks. Package assets locally. No runtime cloud font or icon fetch is authorized. The current Penpot file alone is not the asset delivery packet.

## 5. Component rules

### C01 — Header

Use a common header arrangement for Back, title/context and right-side actions. Align the visible title and action content optically around the header's central band.

- A simple title such as Notifications, Contacts or Settings is one line. It must not inherit the top alignment used by a name-plus-status peer header.
- Header actions use 24 top inset, 24 left/right edge inset, 48 height and 8 between adjacent actions. Back is 48 wide. Keep a 12-unit gap from Back to the title slot. The first control below the header starts at 88, leaving 16 below the action row; a section label or date may use additional separation.
- The Inter Tight reference places a simple 23-unit title at text origin 36, a peer name at 28 and peer status at 53. The root wordmark starts at 37. These font-specific origins reproduce the reviewed visible composition; they are not centering formulas to reuse with a different font.
- Peer name and connection status form one compact group. Long permitted names ellipsize in the available title slot; they must not overlap End Live or overflow controls.
- Root state text and its dot align with the METOR wordmark's visual center rather than its top edge. The current root dot is 6 × 6 at y=45; its 10-unit status text starts at y=42. Leave 16 after the wordmark and 6 between dot and text. Inspect capital-letter ink as well as the font's layout box. Keep the notification badge attached to the Notifications button when that button moves.
- `End Live` is a persistent, subdued contextual header action in the normal active reference. Its neutral raised surface and danger text keep it identifiable without making it a large standalone banner over the timeline.
- Define the small-width and recording-state placement explicitly in the remaining state packet. Do not silently drop A08 when space is limited.

### C02 — Buttons, pills and selectors

Size a label naturally, then center it with its icon as one unit. The standard labeled action uses a leading 18 × 18 icon and an 8-unit gap. This applies to Reconnect, Send Drop, Start Live and the microphone action; it does not convert a row's trailing navigation chevron into a leading icon. Icon-only controls retain their own larger icon and 48-unit target.

For the current Inter Tight labeled-button fixture, the icon sits 1 unit above and the label 1 unit below the flex group's nominal center. This balances the rendered icon mass and letterforms; the entire group remains horizontally centered. Apply this once in the shared component and review again if the font or asset changes. A long label grows the control within available space or uses an approved wrapped composition; it is not squeezed or reduced in font size.

The visible design currently has no authored prototype hover interactions on device/desktop pages. Future default, hover, focus, pressed, busy and disabled variants must preserve dimensions, text size, padding and neighboring positions. Use non-geometric feedback. Reserve border/focus space so adding a stroke cannot cause reflow.

### C03 — Conversation and settings rows

In a normal 84-high conversation row, the avatar is 48 high. The name and supporting status are a compact unit beside it. Current reference text origins are 22 and 47 from the row top; their unequal spacing is deliberate optical correction for the different text sizes.

For the 76-high settings row, current title/supporting origins are 20 and 43. Keep trailing values, toggles and chevrons balanced with the group. These heights apply to the pictured single-line content. An explicitly supported multi-line state must grow or use a defined alternative; it must not clip.

Unread counts center within their badge, and initials center within their avatar. Recheck the visible glyphs after the font is loaded. Preserve consistent row gaps and left/right content edges.

### C04 — Text message bubble

Height follows the rendered body and metadata at the available width:

```text
bubble_height = 12 + measured_body_height + 4 + measured_metadata_height + 10
```

The current reference body line is 20 and metadata line is 14. Consequently, a one-line message is 60 high and the two-line component fixture is 80 high. Those are **results**, not independent hard-coded heights for message types.

- Horizontal padding is 16.
- Short messages hug the wider of body and metadata, subject to a reasonable minimum (128 in the current fixture) and the approved message-column maximum.
- Incoming messages align to the left content edge. Outgoing messages retain the right content edge as their width changes.
- Metadata follows the body with a small 4-unit layout gap. It is never positioned at the bottom of an arbitrarily tall rectangle.
- The metadata row may grow if a truthful status requires wrapping. The bubble then grows with it.
- Adjacent timeline items use a consistent 12-unit gap in these fixtures. A structural notice uses a separate 16-unit gap.
- On width, font, scale or text change, remeasure and relayout. Do not preserve a stale one-line height after wrapping.
- Do not stretch a message to fill spare screen height. Keep unused space in the timeline viewport.
- A transient delivery-state change updates the existing message identity. It does not reorder the transcript.

The 128 minimum and column maximum are layout choices, not a reason to truncate actual message content. Final small-width, long-word and scaling fixtures must validate the wrapping policy.

### C05 — Voice message and audio position

The current Voice reference is 88 high because it includes a 48-high playback target, waveform and duration/status. This is a distinct composition; do not impose its minimum on text messages.

Keep waveform, playback controls and metadata in their allocated areas. Play has matching 16 top and left insets. Go live has matching 16 top and right insets. The waveform starts at 76, leaving 12 after Play, and ends 12 before Go live or 16 before the card's right edge if that action is absent. Duration/status occupies the lower part of the waveform column. A waveform must shrink to the remaining width when a playback action is present. It must not overlap an action or metadata.

The old passive-looking `LIVE` pill is replaced by **`Go live`** inside the affected incoming Voice item. The current action is 80 × 48, with a subdued LIVE tint. It is a playback operation, not a channel selector or call-start button.

- Show it only for the appropriate arriving item when the playback position is behind the available audio edge.
- Accessible purpose: `Jump to current audio`.
- Follow functional `GUI-AUDIO-04`: use the newest safe decoder position and truthful buffering/availability state.
- It must not initiate a call, change the route or mark skipped unheard content fully played/consumed.
- Hide or replace the action with an explicitly noninteractive current-position state when it is no longer applicable. Design that variant in the final packet.
- `0:18 / …` in the reference illustrates an elapsed position with unknown ongoing duration, not a completed 18-second clip or a guarantee of latency.

### C06 — Timeline new-item affordance

The timeline uses one compact **`N new items ↓`** action, centered above the composer with a 16-unit gap in the current reference. The sample is 160 × 48.

This replaces the duplicated full-width `2 new items / Jump to current Live edge` notice and standalone `LIVE` button. It follows `GUI-AUDIO-06` and only restores the timeline's newest position. It does **not** start playback, initiate a call or fabricate listening coverage. Hide it when already at the timeline edge. Do not force-scroll someone reviewing older content.

Audio position and scroll position are independent. Both controls can legitimately exist at the same time because they operate on different things.

### C07 — Status notice

Notices align with the same content edges as adjacent lists, selectors and cards. The previous 16-unit notice inset against a 24-unit device content inset was incorrect.

A short two-line notice uses a 64-high reference with 16 horizontal padding. Current title/supporting text origins are 14 and 36. This compact pair is optically balanced within the surface. Longer content grows the notice and moves later content; it must not be clipped into a fixed 64-high box.

Keep application copy concise and relevant to the user's decision. Engineering descriptions of SDK ownership or widget behavior belong in documentation. Notifications and notices never contain message body previews.

### C08 — Notification Center

The header uses C01. Back and Clear share the same vertical placement; Notifications must not appear above their visual center.

The current one-line entry is 88 high: 16 top padding, a 28-high kind row, 8 gap, an 18-high summary and 18 bottom padding. Entry gaps are 12.

- The timestamp aligns with the kind row.
- The navigation chevron aligns with the summary.
- Keep summaries left aligned for scanning; centering means balancing their component placement, not centering every paragraph across the screen.
- Grow entries for explicitly permitted multi-line summaries. Preserve sanitized, privacy-authorized content only.
- Clear/Dismiss affect center entries only. Navigation, request actions, stale targets and seen state follow `GUI-NOTIFY-01` through `GUI-NOTIFY-04`.
- The selection-mode presentation and eligibility for `Dismiss selected` still need their complete state reference. A final implementation must not present an active selection action with no valid selection.

### C09 — Composer, recording and review

The idle LIVE microphone action contains the concise label **`Hold to talk`**. Do not display a floating instruction referring to “the hardware button.” Desktop and device controls use the same action language.

The text-ready LIVE action uses `Send` in the same 148 × 48 action slot. Hover/press must not change its geometry. The actual state transition from text to capture follows functional section 9; this document does not invent concurrent editable text while this GUI is recording.

Recording uses **`Release to finish`** and a clear recording indicator/timer. The release-required state after interruption needs its own concise instruction and re-arm behavior. It is not inferred from a hover or focus change.

DROP Voice review replaces the ordinary composer while the owned unsent draft exists. Keep Play, Delete and Send separate and reachable. Review controls are anchored as an input-stage composition; they do not need to move up simply because the message timeline becomes shorter.

The 480 reference review panel is 432 × 200 with 16-unit internal side and bottom padding. Label starts at 16, audio preview at 40, and Delete/Send at 136 with 48 height. This leaves 16 below the actions, matching their side insets. Its previous 192-unit height left an incorrect 8-unit bottom margin. The following review hint sits 24 below the panel. The wide component gallery uses a horizontal composition; it follows the same 16-unit container padding instead of copying the portrait height.

### C10 — Container edges and anchors

| Container or relationship | Rule |
| --- | --- |
| Screen / desktop pane | 24-unit outer inset shared by header, content edges and anchored footer |
| Root floating action | 24 from both right and bottom; adjacent label visually centered on the action |
| Composer / footer action | 24 from bottom; side edges align with the pane's 24-unit content inset |
| Voice review / voice playback target | 16-unit interior edge inset; preserve distinct waveform/metadata composition |
| Composer action inside its surface | 8 top, right and bottom; 148 × 48 action in the 64-high LIVE composer |
| Bottom sheet | 24 from screen sides and bottom; 24 internal horizontal padding |
| Rows / notification entries | Shared content width; 12 gap between entries; 16 from a preceding structural notice |
| Centered authentication form | Deliberately narrower form column; fields and actions share that column, rather than pretending to be screen-edge controls |

Use one parent layout to own these relationships. An anchored control must not have independent per-screen x/y offsets. Growing header or timeline content must not move the anchored composer/footer; the available scroll area changes instead. A control's corner is checked against both adjacent edges of its actual container. Optical corrections move visible icon/label content within the target; they do not make outer container padding inconsistent.

Do not apply a 24-unit screen inset to every nested widget. Screen edges, panel interiors and icon/label spacing are distinct levels. Preserve a coherent rule at each level. Presentation-gallery framing is outside the application viewport.

## 6. Interaction and implementation invariants

- Selectors and Back navigate only. Only explicit lifecycle actions start, accept, reconnect, end, change route, fallback or close a LIVE context.
- Bind a control to the correct current identity and eligibility. Revalidate after authorization, asynchronous results and state changes according to the functional contract.
- Keep logical widget identity stable across ACK, capture finalization, recovery and delivery changes.
- Keep the composer independent from timeline scrolling. Keyboard appearance changes available timeline space and must preserve readable/reachable input controls.
- PTT press, hold, release, interruption and focus loss are state transitions, not decorative pointer effects.
- Focus order and accessible labels must follow the same meaningful reading/action order. A hover-only label cannot be the only explanation of an action.
- Perceived alignment is reviewed with the bundled font at actual reference sizes. Geometry checks are secondary guards against overlap/clipping, not proof that the UI looks balanced.
- Changes to glyph shape, weight or font fallback can require a shared component-level optical adjustment. Do not add arbitrary offsets to individual screen instances.

For Kivy, retain this separation: ViewModels expose display-ready state and command eligibility; reusable widgets implement visual rules; platform adapters implement actual input/output capabilities. Use the real accepted SDK interfaces. This draft does not prescribe unverified imports or dependency versions.

## 7. Reference inventory

Penpot file ID: `d8ac01df-6646-81d2-8008-9fb60724c80a`. Use the v0.7 saved revision, not whatever later edits happen to be on the current canvas.

| Reference | Board ID | Purpose |
| --- | --- | --- |
| Components / Messages | `39a2d0c5-e9da-8024-8008-9fbda1292399` | One-line and wrapped two-line text; Voice and Go live |
| Components / Input States | `39a2d0c5-e9da-8024-8008-9fbdd1f8be11` | Text-ready, recording and review |
| V06 Root DROP | `39a2d0c5-e9da-8024-8008-9fbe6ce67bc3` | Normal conversation list |
| V07 Root LIVE | `39a2d0c5-e9da-8024-8008-9fbe6dddb58e` | Active/recovering/unresolved contexts |
| V08 Peer DROP | `39a2d0c5-e9da-8024-8008-9fbe6f73fd5e` | Compact text and Voice review |
| V09A Peer LIVE | `39a2d0c5-e9da-8024-8008-9fbe71a24168` | Explicit End Live; audio jump distinct from timeline jump |
| V09B Peer LIVE | `39a2d0c5-e9da-8024-8008-9fbe74df1e54` | Ended context with pending content |
| V09R Small LIVE PTT | `39a2d0c5-e9da-8024-8008-9fbf38515d45` | Incoming content during recording at 360 × 640 |
| V16 Notification Center | `39a2d0c5-e9da-8024-8008-9fbeec9352a9` | Balanced header and compact entries |
| V17 Settings | `39a2d0c5-e9da-8024-8008-9fbeeecd7cfd` | Shared row treatment |
| D01 Desktop DROP | `39a2d0c5-e9da-8024-8008-9fbfd5229464` | Master/detail and content-driven text |
| D02 Desktop LIVE | `39a2d0c5-e9da-8024-8008-9fbfd6e61b14` | Same LIVE semantics in desktop arrangement |

The screen-card IDs include presentation chrome. Resolve/export their inner viewport for runtime comparison. Component boards intentionally present examples in a gallery; the whitespace between gallery examples is not timeline spacing.

## 8. Coverage and remaining design work

Each row below distinguishes an existing reference from the missing completion work. Functional requirements remain applicable regardless of visual coverage.

| View | Existing visual material | Remaining completion |
| --- | --- | --- |
| V01 Profile entry | 480 reference | Complete startup/auth/error variants |
| V02 Profile picker | Coverage entry / reuse direction | Dedicated picker states, long names, unavailable target |
| V03 New profile | Coverage entry | Form, validation, progress and failure |
| V04 Lock-method management | PIN component and lock references | Password/None/setup/change/recovery compositions |
| V05 Restricted lock | Normal lock, continued LIVE, cooldown | Full privacy/auth mode matrix and focus behavior |
| V06 Root DROP | Normal, empty, long/pending-only | Loading/error/scaling completeness |
| V07 Root LIVE | Multiple context states | Empty/loading/error variants |
| V08 Peer DROP | Review at normal/small size | Keyboard-visible text, recording/finalizing, rejection/unknown states |
| V09 Peer LIVE | Active, ended pending, small recording, no microphone | Idle/calling/recovering/quota/finalizing; complete playback availability and current-edge variants |
| V10 Incoming LIVE | Normal overlay and anonymous multiple requests | Complete busy/stale/expiry/authorization/focus variants |
| V11 Contact picker | Contacts reuse direction | Intent-labelled picker and already-active/no-contact states |
| V12 Contacts | Normal list | Empty/filter/manage and identity-transition states |
| V13 Contact forms | Coverage entry | Add/save/rename forms and failures |
| V14 QR input | No-camera/manual fallback | Scanning, permission, invalid/duplicate QR |
| V15 My identity | Coverage entry | Actual QR/address, loading, unavailable and allowed Copy |
| V16 Notifications | Normal populated center | Empty, selection, aggregated/stale entries and all privacy variants |
| V17 Settings | Grouped normal settings and row examples | Complete supported/unavailable/value-edit variants |
| V18 Activity history | Coverage entry | Metadata-only list, retention disabled, clear failure |
| V19 Advanced | Coverage entry | Approved diagnostics controls and safe error presentation |
| V20 Profile management | Switch/pending/failure reference | Remaining profile/identity management forms and confirmations |
| V21 Exit/power | Normal power/exit reference | Separate desktop/device flows and saving/finalizing/failure |
| V22 Purge | Physical arming reference | Accepted, irreversible-safe, cleanup failure and unknown outcomes |
| V23 Startup/platform error | Graphical failure reference | Configuration/driver/capability cases and documented no-display outcome |

The final action map must cover **A01–A25 individually**, including accessible label, control surface, eligibility, confirmation, busy state, typed failure and reference fixture. Existing examples cover many normal actions, but a complete audited action/state matrix is not claimed here.

Particular handoff checks: A08 End Live across narrow/recording states; A09 route change; A10 close with pending content; A16/A17 selective/bulk fallback; A18 unavailable cached resend; A19/A20 local deletion semantics; A21–A25 auth/lifecycle outcomes. Also map the functional playback and timeline-jump requirements even though they are not separate new A-numbered lifecycle actions.

## 9. How to deliver this to the implementation agent

Deliver one versioned packet in the repository:

| Artifact | Contents |
| --- | --- |
| `METOR_GUI_SPEC.md` | Functional authority, unchanged unless an explicit product decision requires revision |
| `METOR_GUI_LAYOUT_SPEC.md` | Completed visual/interaction contract derived from this draft |
| Named token file | Machine-readable values, semantic names and allowed state overrides |
| Local assets and licenses | Font files, SVG icons and any permitted bitmap assets |
| Reference manifest | View/state → component composition → tokens → data fixture → asset/render → A/GUI requirement IDs → GAT IDs |
| Reference renders | Inner-viewport images pinned to a layout version, with size/scale/font and file hash |
| Visual acceptance fixtures | Reproducible UI state and content independent of a live peer or Penpot connection |

The exact asset/test directories should follow the accepted repository structure. Do not create a parallel design system in an arbitrary `shared` or `utils` directory. Only the suggested specification path is fixed here.

For each fixture, record at least: stable fixture ID; functional and layout versions; view and substate; viewport and scale; permitted mock content; command eligibility; component tree; token set; exact render/asset references; relevant functional/GAT IDs; and any intentional optical adjustment.

Implementation order:

1. Record the accepted repository SHA, SDK surface and platform ADR status.
2. Build the token layer and reusable Header, Button, Selector, Row, TextBubble, VoiceBubble, Notice and Composer primitives.
3. Prove C04 with short, wrapped, long and changing-status messages before assembling large screens.
4. Build a thin V06 → V09 vertical slice at normal, small and desktop sizes using the same widgets.
5. Verify separate timeline navigation and audio seeking, PTT ownership and eligibility against functional tests.
6. Complete the remaining view/state matrix and local reference packet, then implement that matrix without inventing missing states.
7. Review rendered UI for optical fidelity, as well as functional acceptance. Do not accept a numerical-center or screenshot-diff score as the sole design sign-off.

## 10. Visual acceptance fixtures

| Fixture | Required visual/behavioral evidence | Functional anchor |
| --- | --- | --- |
| `layout.text.short` | One-line message is compact; metadata immediately follows body | C04; message identity/status requirements |
| `layout.text.wrap` | Two/three lines grow the bubble without increasing body-to-meta gap | C04; GUI-DESIGN-03 |
| `layout.text.status` | Longer status cannot overlap content or escape the bubble | GUI-SAFE-03 |
| `layout.header.simple` | Notifications/Contacts/Settings visually align with both side actions | C01 |
| `layout.container.edges` | Header corner actions and footer/FAB use equal 24-unit edge insets; desktop rows share selector edges | C01/C10 |
| `layout.icon.label` | Reconnect and other labeled actions form one centered unit; icon and visible letters feel balanced | C02 |
| `layout.review.padding` | Delete/Send have the same 16-unit side and bottom breathing room; waveform stays clear of playback actions | C05/C09 |
| `layout.notification` | Kind/time and summary/chevron share their own alignment; no previews | GUI-NOTIFY-01–04; GAT-58 |
| `layout.live.behind` | Go live belongs to arriving audio; timeline new-items action remains independent | GUI-AUDIO-04/06; GAT-08, GAT-53 |
| `layout.live.edge` | Inapplicable audio-jump/timeline-new-item actions are not misleadingly present | GUI-AUDIO-04/06 |
| `layout.ptt.incoming` | Incoming content remains usable while recording replaces composer | Functional section 9 |
| `layout.minimum.keyboard` | Input, focus and required actions remain reachable at minimum size with keyboard | GUI-DESIGN-03 |
| `layout.pointer.focus` | Hover/focus/press do not move text, resize controls or shift neighbors | C02/C09; GUI-DESIGN-02 |
| `layout.long.labels` | Labels, pills and headers remain legible without accidental clipping or font shrinking | GUI-DESIGN-03 |

Review at intended display scale and with real bundled assets. Check perceived weight, whitespace, rhythm and grouping first; use bounds/overlap checks to catch defects. Pixel-level differences caused by a renderer require visual judgment, while actual clipping, hidden actions or altered semantics are failures.

## 11. Review record and next completion step

The v0.6 pass adjusted 11 text bubbles, including a wrapped two-line component fixture; reflowed affected message stacks; balanced simple headers, status notices and four notification entries; and separated four item-level audio jump controls from the timeline new-item affordance. The affected text-bounds check and Penpot document validation reported no errors.

The v0.7 pass standardized 21 screen/pane headers and the two header gallery examples, 14 anchored footer controls, six desktop master rows, two device bottom sheets, 13 voice cards and 19 labeled icon buttons. Review padding was corrected in the portrait and wide component examples. The 24-unit outer inset now applies to desktop detail content as well as its header and footer. The root status and floating-action captions received a rendered optical correction after the first geometry pass.

Rendered references were inspected across the review passes for Peer DROP, Peer LIVE, the small recording state, Notification Center, root LIVE, desktop LIVE and the navigation/action/message galleries. Geometry checks of the revised screen/pane headers, footers and voice targets found no violations of their shared inset rules, and no direct child-board overflow in the inspected viewports. Penpot document validation reported no errors. These checks supplement visual judgment; they are not a running Kivy test, exhaustive state coverage or a reproduced pointer-hover test.

Next, complete the open state/interaction matrix, confirm the remaining display/resizing decisions and export the local token/asset/reference packet. Then promote this draft to the implementation baseline. Until then, the agent may use these rules to build and review shared components, but must not claim the full GUI design or all V01–V23 states are complete.

## 12. Change log

| Revision | Change |
| --- | --- |
| Penpot v0.3 | Native text alignment in labels, controls, tabs, keys, initials and counts |
| Penpot v0.4 | Optical row balance and consistent content edges |
| Penpot v0.5 | Universal LIVE input copy and subdued header End Live |
| Penpot v0.6 / companion 0.1 | Content-sized bubbles, timeline reflow, balanced notifications, distinct audio/timeline jumps, and explicit implementation handoff plan |
| Penpot v0.7 / companion 0.2 | Shared 24-unit screen/pane anchors, corrected nested review padding, leading icon/label balance, optical root status/caption alignment, desktop row/content edges and explicit container acceptance rules |
