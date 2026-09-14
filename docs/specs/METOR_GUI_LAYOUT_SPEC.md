# METOR GUI LAYOUT SPECIFICATION

**Version:** 1.0 — complete layout and interaction definition  
**Date:** 11 September 2026  
**Functional baseline:** `METOR_GUI_SPEC.md` v1.0  
**Visual baseline:** Penpot revision `METOR GUI v0.7 · shared spacing and optical alignment`, supplemented by the normative compositions and states in this document  
**Suggested repository destination:** `docs/specs/METOR_GUI_LAYOUT_SPEC.md`  
**Language:** English for documentation, implementation identifiers and application copy.

> Implement relationships, content sizing and state rules. A screenshot is a reference for visual judgment, not a collection of independent coordinates.

## 1. Authority and readiness

This is the completed layout companion to functional v1.0. Together, the two documents define the required GUI. Penpot v0.7 supplies the reviewed visual language and representative screens; this document supplies complete reusable compositions, responsive rules and action/state coverage, including variants without a separate Penpot frame. A newly specified variant is a binding design definition, not a claim that a corresponding render or implementation has already passed review.

| Source | Authority |
| --- | --- |
| `METOR_GUI_SPEC.md` v1.0 | Navigation meaning, action eligibility, communication and media lifecycle, privacy, authorization, persistence, platform behavior and functional acceptance |
| This companion | Component composition, sizing, spacing, typography, visual state presentation, understandable labels and visual acceptance |
| Accepted public Core/SDK contract | Actual imports, commands, results, identities and integration boundaries |
| Pinned Penpot references / implementation renders | Visual examples; explicit rules in this v1.0 resolve incomplete or conflicting older examples |
| `GUI_PLATFORM_ADR.md` | Toolkit/runtime proof, display/input adapters, density mapping and platform implementation |

Kivy with a small Metor UI kit is the agreed technical direction. The functional specification still requires the platform ADR and vertical slice. Do not introduce a webview or a second GUI product because the reference can be exported as an image or SVG.

If an example and a functional requirement conflict, correct the example. If a layout decision changes behavior, version the functional contract first. The old `docs/.temp/EMBEDDED_UI_SPEC.md` is historical and must not be merged back into the assignment.

Source provenance: the two available copies of the functional v1.0 file were byte-identical, SHA-256 `8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7`.

**Handoff scope:** the owner's final instruction is to complete the definition with likely Penpot access and avoid an oversized duplicate design package. Accordingly, this single companion contains the token/asset mapping, V01–V23 recipes, A01–A25 matrix and reproducible visual fixture definitions. Existing Penpot references are reused. Separate files for every state, duplicated PNG galleries and a standalone design-system service are not prerequisites. The implementation agent packages assets and records a small set of comparison renders during the required vertical slice. This delivery choice refines the artifact packaging in functional section 21; it does not waive any functional or visual state requirement.

**Completion boundary:** no open layout decision is delegated as an unspecified product choice. Toolkit installation, actual SDK names, codec/audio proof, physical-device support and executed acceptance tests remain implementation work under the functional contract. Owner review of this final definition remains distinct from authoring completeness. Do not label unseen variants as visually reviewed, or a completed specification as a completed GUI.

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

### 3.1 Supported geometry and scaling

The minimum usable application rectangle is **360 × 640 logical units**, excluding native window decoration, simulator controls and platform safe insets. Desktop default is 1180 × 760; its minimum client size is 360 × 640. Device reference is 480 × 800, minimum 360 × 640, portrait. V1 does not support a physical landscape rectangle whose usable logical height is below 640. Rotation is a mounting/input transform: swap native width/height at 90/270 degrees before validating the resulting usable rectangle. A sufficiently large landscape desktop window is supported under the same minimum and breakpoint rules.

On device, logical dimensions equal rotated physical pixel dimensions divided by the validated display scale, minus adapter-reported safe insets converted to logical units. Thus 480 × 800 at scale 1 and 960 × 1600 at scale 2 represent the same reference; neither is a hardware procurement requirement. Unknown safe insets default to zero only for a rectangular display declared to have no occlusion. Unsupported geometry fails via V23 before normal device activation. No forced shrink-to-fit or clipped controls.

Desktop uses the toolkit's actual OS density mapping, once. A display at 200% density must not double all sizes again. Window size constraints use logical client units. If a monitor/OS transition temporarily violates the minimum, cover the unusable surface with `Increase the window size or reduce display scaling`; preserve state and permit safe close, rather than operating invisible controls. Record native pixels, scale and safe insets in platform evidence, not in peer UI.

### 3.2 Responsive composition

- Below 960 logical width: one foreground panel. Its ordinary content is centered with maximum width 560 and 24-unit minimum side insets. On a 480/360 device, this yields 432/312. Header and footer align to this same panel, not opposite edges of a much wider window.
- At 960 or above: root master pane is 360 wide, divider is 1, detail uses the remainder. Master content is 312 wide; detail has 24-unit side insets and a maximum centered content column of 800. Default detail width is 819 and content width 771. This closes the former 32/31-unit mismatch.
- Root DROP/LIVE operates on the master list. Selecting a peer installs one detail foreground view. The peer selector changes that peer projection only. A root-tab change does not silently navigate the detail or promote a background peer. Back from detail clears it to `Choose a conversation` and preserves the originating master tab. Compact Back returns to that root tab.
- Contacts, Notifications and Settings occupy the foreground panel (detail in wide mode). The master may remain visible, but the old peer is no longer foreground for media. Auth, restriction, profile transition and purge cover the entire application, including the master.
- Crossing the breakpoint preserves current route, focus target, selected IDs, drafts and scroll anchor; it issues no communication command. In wide mode, an empty detail uses a muted prompt without a new Home product view.
- Reference font sizes are unchanged by window resizing. Density scales all drawing uniformly. Support text scale 1.0–1.5 through measured wrap/growing rows, and verify 1.5 at the minimum. Never reduce text to fit. Long header names ellipsize; their complete permitted value is accessible in peer/contact details. Body and critical consequence text wrap, including long unbroken strings.
- At elevated text scale or long copy, buttons grow vertically and stack when their measured label, icon and padding do not fit the available row. Forms and sheet bodies scroll. Keep at least one 48-high usable timeline slice with input visible; reduce the composer to one visible editable line and hide optional date/section decoration before consuming that slice. Input content remains editable through internal scrolling.

Software keyboard docking is defined in C14; its temporary inset replaces the ordinary 24-unit bottom edge. It never covers a focused input or an explicit required action.

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

These reference colors are normative. Verify actual foreground/background combinations, disabled readability and focus visibility in native comparison renders using section 12 targets.

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

Section 12 completes named tokens, asset sources, fallbacks and the icon mapping. The implementation packages those assets locally; this handoff does not require an extra archive duplicating Penpot. No runtime cloud font or icon fetch is authorized.

## 5. Component rules

### C01 — Header

Use a common header arrangement for Back, title/context and right-side actions. Align the visible title and action content optically around the header's central band.

- A simple title such as Notifications, Contacts or Settings is one line. It must not inherit the top alignment used by a name-plus-status peer header.
- Header actions use 24 top inset, 24 left/right edge inset, 48 height and 8 between adjacent actions. Back is 48 wide. Keep a 12-unit gap from Back to the title slot. The first control below the header starts at 88, leaving 16 below the action row; a section label or date may use additional separation.
- The Inter Tight reference places a simple 23-unit title at text origin 36, a peer name at 28 and peer status at 53. The root wordmark starts at 37. These font-specific origins reproduce the reviewed visible composition; they are not centering formulas to reuse with a different font.
- Peer name and connection status form one compact group. Long permitted names ellipsize in the available title slot; they must not overlap End Live or overflow controls.
- Root state text and its dot align with the METOR wordmark's visual center rather than its top edge. The current root dot is 6 × 6 at y=45; its 10-unit status text starts at y=42. Leave 16 after the wordmark and 6 between dot and text. Inspect capital-letter ink as well as the font's layout box. Keep the notification badge attached to the Notifications button when that button moves.
- Below 440 panel width, omit the supplemental root wordmark status to preserve the three 48-unit Notifications/Contacts/Settings targets; actual communication state remains in rows/notices. In V16, put Clear and Select inside the visible More menu at this width, preserving Back/title/More. Other secondary header actions move to More when their measured labels would consume the title slot. Essential Back/More targets never shrink; the permitted title ellipsizes only after secondary actions have moved.
- `End Live` is a persistent, subdued contextual header action in the normal active reference. Its neutral raised surface and danger text keep it identifiable without making it a large standalone banner over the timeline.
- At panel widths below 440, keep Back/name/status/More in the first row; place `End Live` in a 48-high context row 16 below the peer selector, right aligned, with `Auto-play: Off/On` on the left. This row grows/stacks for large text. It remains available during recording. At 440 and above End Live stays in the header; Auto-play is the first item in More, or a directly labelled control alongside the selector where both fit. Calling uses `Cancel call` in the same lifecycle slot; idle/terminal views omit this row and use their explicit Start/Reconnect composition. This rule supersedes small v0.7 examples lacking End Live.

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

The bubble maximum is `min(520, floor(0.85 × content_width))`, with 128 minimum unless available width is smaller. Voice may use the full content width. Break long unbroken message text at grapheme boundaries without modifying stored content. Selected metadata and status can wrap; timestamp/status alignment follows incoming-left or outgoing-right. These rules preserve compact short messages while making minimum-size and text-scale behavior deterministic.

### C05 — Voice message and audio position

The current Voice reference is 88 high because it includes a 48-high playback target, waveform and duration/status. This is a distinct composition; do not impose its minimum on text messages.

Keep waveform, playback controls and metadata in their allocated areas. Play has matching 16 top and left insets. Go live has matching 16 top and right insets. The waveform starts at 76, leaving 12 after Play, and ends 12 before Go live or 16 before the card's right edge if that action is absent. Duration/status occupies the lower part of the waveform column. A waveform must shrink to the remaining width when a playback action is present. It must not overlap an action or metadata.

The old passive-looking `LIVE` pill is replaced by **`Go live`** inside the affected incoming Voice item. The current action is 80 × 48, with a subdued LIVE tint. It is a playback operation, not a channel selector or call-start button.

- Show it only for the appropriate arriving item when the playback position is behind the available audio edge.
- Accessible purpose: `Jump to current audio`.
- Follow functional `GUI-AUDIO-04`: use the newest safe decoder position and truthful buffering/availability state.
- It must not initiate a call, change the route or mark skipped unheard content fully played/consumed.
- At the current arriving edge, replace the action with passive `At live edge` text in its reserved column; it has no button surface or activation. On finalized audio, remove the live-edge column. The waveform may grow; neighboring timeline items do not move unless wrapping genuinely changes height. `Buffering…`, `Audio incomplete` and `Audio unavailable` replace false duration/completion claims. Unavailable playback is disabled with its reason, never consumed.
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
- Normal mode has Clear and no bottom `Dismiss selected` button. More/Select, long press or the keyboard context action enters selection mode: Back becomes Cancel selection, title becomes `N selected`, entries gain 48-high checkbox targets, and a bottom `Dismiss selected` action is disabled for N=0. Clear is disabled while clearing or when empty. This supersedes the v0.7 populated example with a selection footer but no selection. Per-entry More includes Dismiss; both selection and dismissal affect presentation entries only.

### C09 — Composer, recording and review

The idle LIVE microphone action contains the concise label **`Hold to talk`**. Do not display a floating instruction referring to “the hardware button.” Desktop and device controls use the same action language.

The text-ready LIVE action uses `Send` in the same 148 × 48 action slot. Hover/press must not change its geometry. The actual state transition from text to capture follows functional section 9; this document does not invent concurrent editable text while this GUI is recording.

Recording uses **`Release to finish`** and a clear recording indicator/timer. After interruption, the composer-sized strip reads `Release to continue`; new capture stays disabled until all relevant held inputs release. It is not inferred from a hover or focus change. Finalizing uses `Finishing recording…` in the same strip, disables new text/PTT for this GUI, and keeps incoming content and eligible playback usable. Buffer-full and operation states follow section 10.

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

### C11 — Menus, sheets and confirmation

Every contextual capability has a visible More entry point; long press/right click/Shift+F10 are equivalent shortcuts. A menu uses surface/raised colors, 16 interior padding, minimum 48-high rows, leading 18-unit icon where useful and explicit text. Maximum width is 320, constrained to the safe rectangle with 24 outer inset. Position beside the invoker where it fits; otherwise use the shared bottom sheet. Disabled relevant actions show a short reason below the label; absent capabilities are omitted only where the user would not expect them.

Sheets use 24 internal padding and 16 content gaps; maximum width 480, maximum height viewport minus 48. Narrow mode anchors 24 above the safe bottom; wide mode centers. Header is title plus a 48 × 48 Close target, followed by scrollable body and action area. When labels fit, Cancel is left and the explicit operation is right, gap 12; otherwise stack the primary operation above Cancel. Consequences must be visible/readable through body scrolling while actions remain reachable. Reversible dismissal: Escape, Back or outside click; destructive confirmation never commits on outside click or implicit Enter. On opening a destructive confirmation focus Cancel. No hold-to-confirm or typed magic words are added.

Incoming-call sheets retain independent call actions and target identity as V10 specifies; they are not generic destructive confirmations. Busy operations may only be cancelled through an actual supported cancellation path. Dismissing a menu/sheet does not imply that a committed operation was cancelled.

### C12 — Forms, settings and reusable list panels

Form column width is `min(400, panel_width - 48)`, centered. Standard form order is title, concise purpose, fields, operation error, primary submit and secondary Cancel/Back. Field label is 13/18 semibold, gap 8 to a minimum 52-high field with 16 horizontal inset; helper/error gap 4, next field gap 16. Labels are always visible, not placeholders alone. Description and error text wrap. Focus ring is inset and does not change dimensions. Mask secret fields; show/hide is an explicit 48 target and does not export a secret. No secret Copy action.

Use registry descriptors for actual supported field names, length/range constraints, scope and effective values. This is deliberate Core-driven form content, not an invitation to invent required fields or repeat business validation. For name/password creation use name, password and password confirmation; extra fields exist only if required by the accepted public creation contract. Validation is local feedback plus authoritative submit result. Keep nonsecret values on failure; clear rejected credential inputs. Unknown results use reconciliation, not a second submit.

Settings are grouped on one scrollable page. A 76-high row contains label plus optional scope/help and a trailing value/toggle; grow for wrapped text. Edit values in the same form/sheet component: bool toggle, enum single choice, numeric input with unit/range, supported bounded text. Show saving in the control's existing slot, do not display an unconfirmed value as saved, and restore the authoritative value with an inline reason on rejection. Full-auth requirements use C13 before the intended operation. No extra settings pages for each toggle.

List panels use 24 edges, optional 52-high search, 16 below search, and 12 row gaps. Search is local filtering of authorized inventory; no added network discovery. Empty filtered result reads `No matches` and offers Clear search. Additional pages append with a labelled loader or retry row, preserving existing content and anchor. No fake avatars: the reference's circles contain derived permitted initials only; locked anonymization removes them.

### C13 — Authentication and restriction

Use a centered max-400 form on the background, with a scrollable body when needed. Cold entry shows Metor, permitted profile name, masked password, Open profile, Switch profile and New profile. Restricted entry shows a lock symbol and `Unlock Metor`; profile name is absent by default, including title/accessibility. The normal window title is `Metor`; simulator adds `Simulator`, never a peer or hidden profile name.

PIN presentation has masked dots and a 3-column numeric keypad (1–9, Backspace, 0, Unlock), 48-high keys with 8 gaps; no clipboard. PIN length/rules come from Core. Submission is explicit Unlock/Enter, one challenge at a time. The profile password alternative is always a labelled `Use profile password` / `Forgot PIN?` route. Typed cooldown appears below the field; disable PIN, retain authorized password recovery and show only Core-reported retry timing. Do not invent local attempt counts. None uses an explicit `Unlock` button backed by the same valid restricted session; it does not silently reveal content on wake.

First-run setup offers Set PIN, Use profile password and No screen lock, with Profile password selected until successfully changed. PIN setup/change requests the Core-required full authorization and new PIN plus confirmation. Removing PIN/choosing None has one consequence confirmation. Normal access after PIN is not proof of full-strength authorization. Before acknowledged restriction, cover all private pixels/accessibility and show `Locking…`; if unconfirmed, remain covered with `Unlock required` and a safe reconnect/auth action.

### C14 — Keyboard and input docking

The software keyboard is local, uses QWERTY by default and QWERTZ when selected, and has four 48-high key rows, three 4-unit row gaps, 4 top and 8 bottom padding, plus a 48-high toolbar: total 264 logical height at normal text scale. Toolbar contains a labelled `Hide keyboard` target. Ten-character row width is shared evenly after two 8-unit side insets and nine 4-unit gaps. At 360 this yields 30.8-wide character targets. **Character keys (letters, digits and punctuation) are the sole narrow-target exception** to ordinary 48 × 48 actions; their full tile is active, no overlapping hitboxes. Shift, Backspace, page switching, Enter, PIN and ordinary controls keep 48 × 48. Space takes remaining row width. Short character rows center within the available width. Verify the 15-unit key font at text scale 1.5; rows can grow when actual font metrics require it.

Rows: QWERTYUIOP; ASDFGHJKL; Shift + ZXCVBNM + Backspace; `123` + Space + punctuation-page toggle + Enter/Done. QWERTZ exchanges Y/Z. Number/symbol pages cover digits, whitespace and the printable ASCII punctuation needed for supported passwords/contact data, with visible page navigation. Additional accepted Unicode can be entered through the OS keyboard/permitted paste; message rendering does not discard it. No suggestions, dictionary, network assets or learned history. Shift is single-use; explicit double activation within 300 ms locks it, with an announced Caps state. Backspace may repeat; PTT and lifecycle actions never do.

Keyboard fills the safe width and docks to its bottom. Composer docks 8 above it; its ordinary bottom-24 rule is suspended while keyboard is shown. Forms scroll the focused field plus validation into the area above the keyboard; put Submit in a reachable sticky action row or make it the explicit Done action. A sheet with input uses the same available height, not a second overlapping keyboard.

Desktop defaults to the physical keyboard. A visible Keyboard action in the composer context menu/form field menu exposes the local keyboard. It hides on PTT admission, Voice review, view departure or explicit Hide; after PTT, text input returns without forcing a previously dismissed keyboard open.

At 360 × 640: keyboard begins y=376; normal 64-high composer is y=304..368. A simple peer header/selector ends at y=136, timeline begins y=152 and ends y=288. A compact active-LIVE context row ends at y=200 and its timeline begins y=216, leaving 72 units. At large text, move Auto-play into More and use a labelled End Live item in More while the keyboard consumes space; the visible More target remains fixed. This keyboard-only compression restores at least 48 units of timeline, with one-line internally scrolling composer. Recording hides keyboard and restores the explicit End Live context row.

### C15 — Loading, errors and progress

Loading is a 24-unit indicator plus concise text inside the relevant content region; no shimmering fake messages. Empty/error panels use max-400 centered text with title 20/26, body 15/20, gap 12 and an eligible 48-high action 16 below. Forms use inline field/global errors; list-wide failure uses a full content panel; a failed page uses a retry row; media failure remains attached to that item. Retain safe known content with a `Updating…` notice during reconciliation; do not present stale authorization as actionable.

Show no fabricated percentage. Buttons preserve target geometry and label/operation identity while busy; use a reserved leading spinner slot. A small success notice lasts 3 seconds while visible/focused, never steals focus and contains no message preview. Actionable errors, quota pressure and unknown outcomes persist until resolved or explicitly dismissed, with the underlying state still accessible. `Checking result…` disables duplicate initiation and exposes Check status only if public reconciliation supports it. Unsupported recovery offers safe Back/Close without promising rollback.

### C16 — Indicators and motion

Always pair color with text/icon. Local recording shows a solid danger dot plus Recording and elapsed accepted media time. Media timers use tabular numerals; unknown duration is an ellipsis. Optional physical indicator mappings: off = off; locked_live_active = steady dim amber; transmitting = amber pulse, 250 ms on/off; receiving = steady mint; both directions = transmitting pattern plus independent on-screen receiving status; purge_arming = danger pulse, 125 ms on/off; critical_error = steady danger. Do not flash the whole display. Use the nearest supported monochrome equivalent with the same cadence; absence of a hardware indicator retains the permitted visible recording cue. Haptics, when configured: one 40 ms acknowledgment for admitted capture, two 40 ms pulses separated by 80 ms for rejection, one 100 ms arming-start acknowledgment; otherwise no substituted OS notification.

Core's authorization/privacy filter applies before indicator selection. Purge/critical overrides media; media overrides continued-idle. Locked notification Off suppresses unrelated wake/LED/haptics; only exact authorized continued media gets non-identifying safety indication. Optional patterns are requests to registered adapters, not new hardware requirements or authentication. Reduced motion removes animation, retains steady semantic color/text and all safety feedback. No animation delays PTT release, lock cover or purge fencing.

## 6. Interaction and implementation invariants

- Selectors and Back navigate only. Only explicit lifecycle actions start, accept, reconnect, end, change route, fallback or close a LIVE context.
- Bind a control to the correct current identity and eligibility. Revalidate after authorization, asynchronous results and state changes according to the functional contract.
- Keep logical widget identity stable across ACK, capture finalization, recovery and delivery changes.
- Keep the composer independent from timeline scrolling. Keyboard appearance changes available timeline space and must preserve readable/reachable input controls.
- PTT press, hold, release, interruption and focus loss are state transitions, not decorative pointer effects.
- Focus order and accessible labels must follow the same meaningful reading/action order. A hover-only label cannot be the only explanation of an action.
- Perceived alignment is reviewed with the bundled font at actual reference sizes. Geometry checks are secondary guards against overlap/clipping, not proof that the UI looks balanced.
- Changes to glyph shape, weight or font fallback can require a shared component-level optical adjustment. Do not add arbitrary offsets to individual screen instances.

For Kivy, retain this separation: ViewModels expose display-ready state and command eligibility; reusable widgets implement visual rules; platform adapters implement actual input/output capabilities. Use the real accepted SDK interfaces. This definition does not prescribe unverified imports or dependency versions.

Input/focus contract: Tab/Shift+Tab follow the visual reading order: Back, header actions, selector, context controls, content actions, composer/input, submit/PTT. Inside a selector/list/radio group, arrows move among items and Enter activates the focused item; selection alone never starts a call unless the list is explicitly the Start Live picker. Space/Enter activate focused ordinary buttons on release. On focused Hold to talk, Space-down/up owns PTT; Enter does not simulate a recording. No global shortcut or text-field Space capture. The composer uses Enter for a newline and Ctrl+Enter to send; explicit Send remains visible. Password/PIN Enter submits only a valid focused authentication form. Context menu: Shift+F10/right-click/500 ms long press with cancellation after 8 units of pointer travel; More provides the always-visible alternative. PTT starts immediately on admitted down, not after a long-press timer.

Focus stays stable on asynchronous list updates. New content never steals it. A modal traps focus in its permitted controls and returns it to its invoker (or the nearest valid safe control). Only a clicked Open/unlock flow intentionally navigates. An unsolicited incoming call uses a nonmodal sheet: preserve typing/PTT ownership; announce permitted event text politely, expose the sheet in normal Tab order, and never finalize a capture merely by arrival. Privacy cover/purge preempts every overlay. Otherwise newest actionable call remains separately addressable; a confirmation/auth sheet is not stacked underneath another modal—show a permitted call indicator and allow explicit switching to that call surface.

Escape/Back closes a reversible overlay, then hides the software keyboard if open, then performs view Back. It never dismisses restriction or accepted destructive work. If the physical PTT source is held during a context transition, render Release to continue until released. Screen readers receive safe labels/state, not color names, raw exceptions or continuous waveform/timer chatter. Unknown/rejected operations are announced once and stay readable. Tooltip-only information is never required to operate a control.

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

## 8. Complete view definitions

These recipes are normative realizations of the functional V inventory. Each composes C01–C16 and the common states in section 10. A view need not be a separate heavyweight page or Penpot frame. The reference inventory supplies visual exemplars; additional variants use these explicit compositions. Core owns operation/permission values and validation; this document owns where and how they appear. All recipes inherit responsive, focus and privacy rules.

### V01 — Boot / profile entry

Full-application C13 entry form with C15 startup/error, no private master pane. Show the configured/default or explicit permitted profile, Password, Open profile, Switch profile (V02), New profile (V03). No profiles goes directly to V03; removed default goes to V02. Loading reads Starting Metor / Opening profile with communication disabled. Invalid credentials use a generic inline error and fresh challenge. Local autostart Ask uses C11 Start Metor / Cancel only for the eligible local service; remote endpoint failure offers Retry / Select profile / Exit without starting a local substitute. No terminal prompt. Cancellation abandons this attempt and callbacks. Successful bootstrap leads V04 first setup or V06 root DROP.

Reference: device V01, C13. Functional: GUI-BOOT-01–03, GUI-START-01–03; GAT-35, 41, 42.

### V02 — Profile picker

C01 Back / Choose profile, C12 permitted local profile list, bottom New profile. Rows contain permitted name and optional Default marker, no peer/activity preview. Selection proceeds V01; startup selection is not A22. Empty: No profiles / Create profile. Long names ellipsize with accessible permitted full value; many rows paginate/scroll. Unavailable target leaves the list visible with Profile unavailable / Retry / Choose another. Running restricted GUI requires normal unlock before exposing this list. Active-runtime switch uses V20/A22.

Reference: C12 list using Contacts spacing, C13 privacy. Functional: GUI-BOOT-01, GUI-LOCK-05; GAT-23, 42, 62.

### V03 — New profile

C01 Back / New profile, C12 Name / Password / Confirm password and Create profile. Only encrypted-profile creation. Confirm starts one public operation; supported constraints and additional required fields come from the accepted creation contract. Field mismatch/errors appear below their field; operation errors above Create. Creating disables duplicate submit. Known failure retains nonsecret name and clears rejected secrets; unknown checks the existing operation before retry. Success enters/authenticates that exact profile then V04. Cancel before acceptance creates nothing; after acceptance show the actual created-profile result rather than pretending cancellation deleted it.

Reference: C12/C13. Functional: GUI-BOOT-01–03; GAT-41, 42, 46, 67.

### V04 — Lock-method setup / management

C01 Back / Secure Metor or Unlock method, C13 choices PIN / Profile password / No screen lock. First-run default remains Profile password. Set/change PIN uses Core-required full authorization plus new PIN and confirmation. Change/remove or None requires the required stronger proof and one consequence confirmation: No screen lock / Profile password is still required when opening the profile. Forgotten PIN requests a fresh password challenge; never submit a deliberately wrong PIN. Busy/error retains the effective method. Interrupted setup leaves Profile password. A PIN-unlocked UI is not evidence of full-strength permission. This subflow never changes the OS lock.

Reference: Auth Keyboard gallery, C12/C13. Functional: GUI-BOOT-02, GUI-LOCK-02; GAT-23, 56, 67.

### V05 — Restricted lock

Full privacy cover plus C13 unlock; optional privacy-permitted V10 and exact authorized continued-media strip. Default title Unlock Metor omits profile/peer name in pixels, window title and accessibility. PIN/password/None/forgot PIN/cooldown follow C13; unknown restriction remains covered. Show all may display authorized alias and event kind, never preview. Anonymize shows Incoming Live / New Drop and permitted aggregate counts, no initials, generated anonymous alias, saved classification or Onion. Off shows no unsolicited event/count/wake/LED/haptic. Exact continued locked LIVE under Off may show nonidentifying Live active / Recording and PTT within its grant; auto-play still obeys the existing override. Contacts/settings/center require unlock. Terminal context revocation removes media permission and enforces release. Unlock refreshes current state without reconnect or backlog playback.

Reference: V05, V05O/V05C/V10L, C13/C16. Functional: GUI-LOCK-01–05, GUI-NOTIFY-04–05; GAT-20–23, 56–60.

### V06 — Root DROP

Root C01, DROP/LIVE selector, C03 list, bottom-right New Drop (56 target and adjacent label), or labelled full-width action in wide master. No Home/bottom navigation. Row activation A01; More exposes Pin/Unpin, Save contact for a relevant unsaved peer, and eligible DROP clear. Membership follows Core-published DROP state, never an unsent draft. Pins order relevant rows first; other ordering follows authoritative activity and stays stable on rename. Pinning does not manufacture a conversation. Pending-only rows show Queued and remain after eligible clear. Row subtitle uses safe metadata such as New Drop / Voice message / Queued, distinct from notification previews. Empty: No Drops yet / New Drop. Loading/error replaces the list and prevents stale authorization. Long names ellipsize; counts/time retain trailing slots. Demotion replaces all stale aliases. Root clear-all is the DROP-only Privacy action.

Reference: V06/V06E/V06L, C03. Functional: GUI-NAV-01, 03; GAT-01, 02, 17–19, 29, 61.

### V07 — Root LIVE

Same root shell, LIVE selected and Start Live. Rows show actual active/reconnecting/ended state with separate pending/unseen counts; active tint amber, recovery info, ended unresolved neutral. Tap A02 only. Row More includes eligible End Live / Reconnect / Send N as Drop / Close Live and Save contact. Empty: No Live conversations / Start Live; loading/error C15. Retained local transcript can keep a row labelled Local conversation, not Connected. Other-client changes refresh pending/unseen eligibility. Background updates never promote foreground or start playback; counts never imply consumption.

Reference: V07/D02 master, C03. Functional: GUI-NAV-04, GUI-MSG-01–03; GAT-04, 13, 15, 16, 25.

### V08 — Peer DROP

Peer C01, DROP selector, C04/C05 timeline, anchored C09 composer or recording/review. Empty: No Drops yet with authorized input usable. A11 explicit Send Drop; idle mic Hold to record. Release finalizes to unsent review, never sends. Review: Unsent voice, Play/Delete/Send Drop; second PTT blocked with Send or delete this recording first. Navigation retains same-runtime review for this peer. Optional review hint is omitted at minimum height. Sending/unknown commit retains bound review, blocks duplicate Send and only enables Delete/retry after exact outcome reconciliation. Invalid/empty capture: No audio recorded, no fake playable item. Item More: eligible Delete locally and permitted Copy text. Peer More: Save contact, Clear Drops, Show keyboard. Rejected delete leaves the item and reason visible. LIVE history and lifecycle are unaffected.

Reference: V08/V08R, Messages/Input States. Functional: GUI-INPUT-01–05, GUI-VOICE-01–05, GUI-MSG-04–05; GAT-02, 10, 12, 28–30, 46–49, 51.

### V09 — Peer LIVE

Peer header, LIVE selector, context actions C01, virtualized timeline, composer/recording strip.

| Substate | Controls and presentation |
| --- | --- |
| Idle, no context | No Live connection; Start Live; no composer implying eligible send |
| Calling | Calling… plus Cancel call in lifecycle slot; no fabricated connected state |
| Active | End Live, per-context Auto-play, Send/Hold to talk, playback and More |
| Recovering | Reconnecting…; same transcript/turn/auto-play override; new admission only if Core permits genuine recovery; no second Reconnect worker |
| Ended, pending | Disconnected plus truthful reason; Reconnect / Send N as Drop; no new LIVE composer; Close disabled with Resolve queued messages first |
| Ended, no pending | Reconnect / eligible Close Live; retained unseen playback available; explain actual local transcript loss if closing removes it |
| Recording/finalizing | C09 replaces only this GUI's composer; outgoing placeholder stays at admission position; incoming items/playback continue |
| Quota/media failure | C15 item/strip reason and section 10 resolution; preserve admitted prefix and release barrier |
| Behind audio/older timeline | Go live and N new items remain independent |
| Cache-evicted media | Audio unavailable / Recording no longer available; replay/resend disabled, no refetch of erased content |

More: Auto-play if not directly shown, eligible Change route, Send N as Drop, Select pending items, relevant Close Live, Save contact, Show keyboard. Own pending item More offers Send as Drop; own delivered complete source offers Resend as Drop. Received LIVE has no resend/forward. Selection adds checkbox targets and footer Send N as Drop / Cancel; new arrivals never join automatically, recording/finalizing items are ineligible. End Live remains reachable in its header/context slot. Selection does not freeze incoming content. Leaving selection restores composer or ended controls.

Reference: V09A/V09B/V09R/V09M/D02, C04–C06/C09. Functional: sections 8–12; GAT-01, 04, 06–09, 11–16, 44–55, 57.

### V10 — Incoming LIVE

Nonmodal C11 sheet preserves underlying route/drafts. Title Incoming Live, permitted identity, concise explanation that Accept keeps this view and Open switches to Live; Decline / Accept / Open Live. Below 360 inner content width stack full-width actions; otherwise three equal columns with 12 gaps. No preview. Multiple requests use Previous/Next 48 targets and N of M; selection remains bound to the exact request/opaque handle. A new request never changes the target beneath a press.

Accept remains on original route, accepted peer background/silent. Open authenticates if needed, revalidates and accepts/navigates once. Expiry becomes Request ended / Close, never call-back or advance-and-activate. Already accepted offers Open only for a known permitted context. Anonymous denied Accept says Unlock to accept and keeps Decline, no caller-class leak. Unlock uses normal configured method, not an invented stronger password. Locked Off suppresses the surface entirely. Closing presentation leaves permitted current actionable facts discoverable.

Reference: V10/V10L, Overlays. Functional: GUI-FLOW-02, GUI-NOTIFY-04, GUI-LOCK-04; GAT-05, 22, 58, 60.

### V11 — Intent-labelled contact picker

C01 New Drop or Start Live, C12 saved-contact search/list, Scan QR / Enter contact data. Under New Drop selection opens DROP; under Start Live it explicitly starts once or opens an already active/recovering context. Accessible row label includes intent. Active row says Open active Live, no duplicate ring. Empty: No saved contacts plus scan/manual actions. Unavailable target stays in picker with safe retry. New peer uses V14/V13 preserving Save & Open Drop / Save & Start Live through validation/auth/cancel. General Contacts browsing never inherits implicit start intent.

Reference: Contacts list plus C12/C11. Functional: GUI-FLOW-01, GUI-CONTACT-03; GAT-02, 03, 19.

### V12 — Saved Contacts

C01 Contacts / Add / My QR, C12 search and saved-only rows. Plain activation opens C11 contact sheet with permitted full alias/identity and Open Drop / Start Live (or Open active Live) / Rename / Remove contact; never an unlabelled call. Add uses Save-only V14/V13; My QR uses V15. Empty: No saved contacts / Add contact. More/Manage enables selection and confirmed Remove selected; Clear all contacts is separately labelled/confirmed. Successful demotion removes saved rows, updates relevant contexts to current Core labels and uses generic Contact removed; active communication continues. Failure retains the row. Long names, duplicates, rename and in-flight demotion use stable identity.

Reference: V12, Rows, C12. Functional: GUI-CONTACT-01–03; GAT-17–19, 68.

### V13 — Add / save / rename contact

C01 intent title, C12 supported contact identity (editable manual input, read-only after scan), local alias, explicit Save / Save & Open Drop / Save & Start Live / Rename. No invented optional fields. Rename cannot edit canonical identity. Unsupported/self/invalid identity or duplicate alias gets field error. Existing peer resolves to canonical contact/open/start route, not a duplicate. Discovered peer may be promoted through Save contact. Denied save retains nonsecret input and never continues to call. Busy/unknown S04–S06. Success updates authoritative labels and completes original intent exactly once.

Reference: C12/C11 and V12 visual language. Functional: GUI-CONTACT-01–03; GAT-02, 03, 17–19, 46.

### V14 — Camera / QR input

C01 Scan contact / Back, camera preview square up to 320 or content width, instruction, Cancel / Enter contact data. Camera permission starts only after explicit Scan. Pending/denied permission occupies preview; offer the supported permission flow or manual entry, no automatic OS-settings launch. No camera goes to manual entry. Unreadable code: Could not read this code; unsupported/self/malformed data is a validation result, no URL action. Valid scan releases camera and proceeds V13 with intent. Duplicate uses canonical peer. Cancel releases camera promptly. Manual entry is multiline plain contact data plus Validate using the same public validator.

Reference: V14, C12/C15. Functional: GUI-CONTACT-03, GUI-SAFE-01–02; GAT-02, 03, 39, 68.

### V15 — My contact / identity

C01 My contact, centered QR on plain light square, supported address in wrapped plain text, optional Copy address and Back. QR maximum 240 or content width; four-module quiet zone, integer module scaling, black on white, no decorative overlay. Use actual public encoding. If it cannot be rendered decodably at this size, show address/manual-transfer fallback, never a fake QR. Loading reserves the QR region; unavailable offers Retry / Back without stale previous-profile identity. Copy omitted when disabled/forbidden. Generate new address belongs explicitly to V20, not a refresh gesture.

Reference: C01/C12 and QR primitive above. Functional: GUI-CONTACT-04, GUI-SAFE-01; GAT-39, 67, 68.

### V16 — Notification Center

C01 Notifications / Clear and contextual Select, optional no-preview note, C08 entries. Kind/count/time/summary use permitted metadata only. Normal mode has no selection footer; selection follows C08. Empty: No notifications, Clear disabled. Aggregation example Connection unstable · 3 updates; current requests/failures retain actionable identities. Tap navigates without Accept/Reconnect; explicit call actions expose V10. Dismiss/Clear use volatile watermarks, leave root/Core facts intact. Stale target updates/removes with Item no longer available, no deleted-peer navigation. Permission change sanitizes before painting/accessibility or covers V05. Off history cannot be reconstructed from current unread count.

Reference: V16/C08; selection correction overrides v0.7. Functional: GUI-NOTIFY-01–05; GAT-22, 29, 58–60.

### V17 — Settings

C01 Settings, C12 single scroll list grouped Live / Privacy / Device / Profiles and Advanced. Include all functional section 16 mappings/defaults: exact receive/drop scope, fallback, independent locked-call/audio policies, receipts, histories, method/timeout, keyboard and profile actions. Scope is visible during edits; no independent authoritative GUI policy copy. Links: V18 Activity history, V19 Advanced, V20 profiles/identity, V04 unlock method. Explicit Lock Metor row A21; desktop Exit Metor A23; supported device Power off A24. Optional unsupported volume/brightness/haptics omitted or explained when relevant. Lower limits cannot delete content. Weakening security/disabling timeout uses one warning plus required auth. Rejected/unknown saves retain actual effective values.

Reference: V17, settings rows, C12. Functional: GUI-SET-01–04; GAT-21, 29, 61, 67.

### V18 — Activity history

C01 Activity history / Clear, C12 paginated metadata rows: kind, permitted identity, display timestamp and approved Core detail, no body/audio excerpts. Empty: No activity recorded. Disabled retention: Activity recording is off / Open privacy settings, no substitute event log. Clear requires an explicit scope confirmation and exact Core history-clear operation, including actual ledger effects. Failure retains available current rows and safe retry. No Notification Center export or reconstructed LIVE transcript.

Reference: C08 geometry adapted to metadata, C12/C15. Functional: GUI-HISTORY-01; GAT-29, 67, 68.

### V19 — Advanced diagnostics

C01 Advanced, C12 approved descriptor groups, explicit Raw activity history / Platform diagnostics. Only permitted quotas/concurrency/recovery/cache/IPC/rejection/sink controls. No debug/plaintext/SQL mirror/arbitrary shell or transport-selection additions. Technical names are allowed here with help/scope; safe errors contain no secrets/payloads. Unsupported capability is disabled with reason. Raw history uses V18 geometry with Technical history title and approved metadata. Allowed external sink needs explicit metadata-export warning and authorized save; do not invent an unsupported destination field.

Reference: C12/C15. Functional: GUI-SET-02, 04, GUI-HISTORY-01, GUI-PLAT-05; GAT-67, 68, 74.

### V20 — Profile / identity management

C01 Profiles, current/default rows with More, Switch profile / New profile / My contact. More: Set default, Rename, Change password, Remove profile. Identity: Generate new address. Reuse V02/V03/C12/C13; password change requires actual full proof, new password and confirmation. Active-profile removal/default/rotation obey public eligibility; refusal explains restrictions, not forced shutdown. Remove/rotation uses one explicit effects confirmation and required auth, no promise that old conversations follow rotation.

A22 with relevant active/pending/drafts/other-client consequences uses one truthful summary including own-draft discard. No consequences means no extra warning. During switch cover all private content: Finishing recording / Preserving queued messages / Closing profile / Opening profile, driven by actual phase. If A remains active, offer Return to current profile only when true; if A locked and B failed, Choose profile / Retry entry, never auto-unlock A. Returning later restores Core pending/unseen, not GUI drafts or implicit reconnect.

Reference: V20, C11–C13. Functional: GUI-LIFE-01–02, GUI-CONTACT-04; GAT-24, 25, 46, 62, 67.

### V21 — Normal exit / device power

C11 Exit Metor on desktop or Power off on supported appliance, Cancel where confirmation is needed. Desktop idle close needs no confirmation; own-draft loss/finalization failure gets one precise consequence/error choice. Close affects this GUI only. Device long Power opens Power off / Cancel; explicit action prepares local safety then authorized shutdown. Unsupported/remote/unsafe runtime binding disables shutdown. Progress: Finishing recording / Saving local state / Powering off only for actual phases; never wait for remote delivery. Failed preparation keeps power on with eligible Retry/Cancel. Unknown finalization says Could not confirm recording preservation. Desktop Exit anyway exists only if the public owner-loss preservation contract supports it; no force-delete and no analogous unknown-safety device power cut.

Reference: V21, C11/C15, mode-specific rules override gallery copy. Functional: GUI-LIFE-03–04; GAT-26, 63, 64.

### V22 — Emergency purge

Minimal privacy cover; no everyday Purge button/settings/desktop shortcut. Authorized Power + PTT presents Hold both buttons with progress driven by five continuous seconds. Early release: Cancelled / Release both buttons, consume delayed Power/PTT. Unavailable grant: Purge unavailable without identity/proof detail. Accepted/fenced: Purging profile, stop normal producers, no Cancel. Never show Safe to power off before combined documented milestone. Safe plus terminal cleanup success: Profile access destroyed / Powering off. Safe plus cleanup failure: Profile access destroyed; cleanup incomplete. Unknown/key-release failure: Destruction not confirmed / Keep device powered; Check status only via authorized destruction-status API. Never unlock/recreate/retry a new destructive operation as recovery. Safe milestone with missing cleanup follows the functional bounded platform wait. Simulator labels Simulation and cannot destroy or shut down production.

Reference: V22, C13/C15/C16. Functional: GUI-PURGE-01–03; GAT-27, 40, 65, 66.

### V23 — Startup / platform error

If graphical output exists, C15 title, safe config path/field or capability reason, eligible Retry / Exit / Select profile. Invalid requested config/geometry never silently falls back to desktop/mock. No graphical backend reports sanitized stderr/service status and the functional Terminal/supported-display suggestion; no invented GUI success. Before-display failure stops activation. Optional mic/output/camera loss stays local to dependent V08/V09/V14 actions. Required driver/power-security failure refuses device readiness. Diagnostics may expose validated mode/config source, never peer content.

Reference: V23/C15. Functional: GUI-START-03–06, GUI-PLAT-01–06; GAT-35–40, 42, 69, 72.

## 9. Complete action-to-control matrix

Every row specifies visible/accessibility wording and placement. Dynamic labels use only the current permitted identity. Exact authorization, generation and operation identity are revalidated by Core, including after auth. No confirmation means no redundant confirmation, never waived authorization. All unknown outcomes inherit S06: reconcile the same operation/message ID before allowing duplicate initiation.

| ID | Control / accessible label and location | Eligibility / confirmation | Busy / rejection |
| --- | --- | --- | --- |
| A01 OPEN_DROP | Open Drop: root row, peer selector, contact action, intent picker | Current authorized target; navigation only; no confirmation | Loading content / unavailable panel, preserve originating root tab |
| A02 OPEN_LIVE | Open Live: root row, peer selector, existing-active picker result | Authorized target; navigation only | Loading context; idle if no call, never implicit Reconnect |
| A03 START_LIVE | Start Live: V09 idle, V07/V11 picker, V13 Save & Start Live | No conflicting active/recovering attempt; Save must succeed; intent-labelled selection already confirms | Calling… / Cancel call; Could not start Live; exact attempt reconciliation |
| A04 RECONNECT | Reconnect: V09 ended main action or V07 More | Terminal, publicly eligible; not a second genuine-recovery worker; none | Reconnecting… / Could not reconnect |
| A05 ACCEPT | Accept or Unlock to accept: V10 | Exact pending request/handle, policy; normal unlock if necessary; none | Accepting…; stay in current view; denial retains Decline |
| A06 DECLINE | Decline: V10 | Exact permitted pending handle; none | Declining… / Request ended when stale; no navigation |
| A07 OPEN_CALL | Open Live: V10 | Restore normal access; revalidate; accept if pending or navigate accepted known context; none | Opening…; expired → Request ended, no replacement outgoing call |
| A08 END_LIVE | End Live: V09 header/compact context row, V07 More | Current eligible context; no ordinary confirmation; show pending consequence if relevant | Ending Live…; failure preserves current context/transcript; no discard-pending option |
| A09 CHANGE_ROUTE | Change route: V09 More | Active/publicly eligible; none | Changing route… / Route changed / Could not change route; no route IDs |
| A10 CLOSE_LIVE | Close Live: ended V09, V07 More | No pending outbound/active/recovery; explain and confirm only actual eligible content loss when needed | Closing…; Resolve queued messages first on rejection; retain context |
| A11 SEND_TEXT | Send Drop / Send: composer; Ctrl+Enter | Nonempty valid-length text and delivery-specific admission; none | Queueing…; clear only after local acceptance; rejected/unknown retains draft |
| A12 PTT | Hold to record (DROP) / Hold to talk (LIVE): composer or physical source | Mic/auth/capacity; LIVE active/genuinely recovering; no conflicting review; admitted down is intent | Recording → Finishing recording; preserve accepted prefix; Release to continue |
| A13 PLAY_VOICE | Play voice message / Pause voice message: item/review | Authorized available supported source and output; none; draft playback never commits | Buffering… / Audio incomplete / Audio unavailable; no false consumption |
| A14 SEND_DRAFT | Send Drop: V08 review | Exact finalized valid own unsent draft; none | Queueing…; retain review on failure/unknown; reconcile before Send/Delete |
| A15 DELETE_DRAFT | Delete recording: review trash, accessible name and tooltip | This owner's uncommitted non-unknown draft only; deliberate Delete needs no extra confirm | Deleting… / Could not delete recording; committed winner cannot be erased |
| A16 FALLBACK_SELECTED | Send as Drop: own pending More; Send N as Drop: selection footer | Exact eligible complete selected IDs; explicit action supplies intent | Queueing as Drop…; reconcile atomic result; N Live messages queued as Drops |
| A17 FALLBACK_ALL | Send N as Drop: ended V09/More, V07 More | Current eligible peer count, excludes recording/finalizing; none | Refresh count after races; local conversion wording, never delivered |
| A18 RESEND_DROP | Resend as Drop: own delivered LIVE More | Complete permitted source, no received forwarding; helper Creates a new Drop | Queueing new Drop…; new ID; missing source Recording no longer available |
| A19 DELETE_DROP | Delete locally: DROP item More/selection | Direction-qualified eligible item; confirm Delete this local message? and relevant queued-message protection | Deleting…; rejected queued item stays visible, no optimistic permanent removal |
| A20 CLEAR_DROP | Clear Drops: peer More; Clear all conversations: Privacy | Confirm Local Drops only. Queued messages are not cancelled | Clearing…; retain actual pending rows; no LIVE/contact effect |
| A21 LOCK_APP | Lock Metor: Settings; configured short Power/idle | Current GUI restriction flow; none | Immediate cover then Locking…; failure remains covered and requires safe auth/reconnect |
| A22 SWITCH_PROFILE | Switch profile: V20 selection | Public coordinator; one warning only for relevant active/pending/drafts/shared-client consequences | Actual V20 phases; A-active vs A-locked/B-failed handling, no fake rollback |
| A23 EXIT_GUI | Exit Metor: desktop Settings/window close | Own cleanup only; warn only actual discard/failure consequences | Finishing recording… / Closing Metor…; safe owner-loss alternative only if supported |
| A24 POWER_OFF | Power off: device menu/Settings | Valid local binding and safe preparation; explicit menu action confirms | Saving local state… → Powering off; failed/unknown safety keeps device on |
| A25 PURGE | Physical Power + PTT five seconds; Hold both buttons | Current prior-authenticated scoped grant; no desktop shortcut/menu trigger | V22 milestones; no success from EOF/timeout, no power cut before combined safe guarantee |

Auxiliary controls are not new lifecycle IDs: Back, search, selection, Pin/Unpin, Save/Rename/Remove contact, profile forms, setting save, notification Dismiss/Clear, keyboard visibility, Auto-play, Go live and N new items. Their surfaces are defined in C/V recipes. Contact remove/clear-all, profile removal, address rotation, history clear and security weakening use C11 consequences and required authorization. Navigation/search/keyboard/auto-play/notification presentation do not substitute for A03–A10 or A25.

## 10. Shared state and privacy realization

All views inherit these states even without separate frames. Fixtures set actual public eligibility facts, not merely an error-colored happy-path widget.

| State | Presentation and allowed response |
| --- | --- |
| S01 Initial loading | C15 in body; stable shell/Back if safe; no private stale data or pre-bootstrap communication |
| S02 Empty / filtered empty | Purpose-specific No… and relevant create/scan, or No matches / Clear search; no invented peer |
| S03 Content growth | Wrapped bodies/errors/consequences, ellipsized row names, reserved count/time, pagination; stable focus/anchor |
| S04 Operation pending | Existing target disabled/spinner, identity retained, neighbors fixed; no duplicate pointer/key initiation |
| S05 Known rejection | Inline reason, safe input retained, exact eligible retry/alternate; preserved Core items stay visible |
| S06 Unknown outcome | Checking result…; duplicate barrier; same-ID reconciliation; Check status only if supported; never a fresh send or fake rollback |
| S07 Stale/replaced target | Reconcile identity; Request ended / Item no longer available; safe Close/Back, no callback retarget |
| S08 Capacity / interruption | Core threshold warns; refusal finalizes accepted prefix, explains resource, requires release; no overwrite/auto-send |
| S09 Capability failure | No microphone disables PTT; no output disables Play/auto-play; no camera offers manual; text/unrelated functions remain |
| S10 Restriction / redaction | Policy applies before pixels/accessibility; immediate cover, hidden profile default, no preview even Show all |
| S11 Lifecycle phase | V20/V21/V22 cover; exact phase/safe guarantee controls next action; invalidate old jobs/secret references |
| S12 Media/message truth | Preparing / Queued / Pending / action-required failure; Delivered/Read only from facts, absent READ unknown; buffering/incomplete/unavailable distinct |

Capacity copy follows the resource: pending LIVE → eligible Reconnect / Send pending as Drop; DROP staging → Send/delete your unsent recording; playback cache → Stop playback or Recording no longer available after eviction; text draft budget → Draft limit reached, finish another draft; event overload → Updating state… or explicit failed recovery. Never suggest an action incapable of freeing that resource. Interrupted producer/finalization failure stays preserved pending/error, not endless Recording.

| Locked combination | Visible surface | Input/audio |
| --- | --- | --- |
| Show all, no continuation | V05 plus authorized named V10/event kind | Normal unlock; permitted handles only; no background auto-play |
| Anonymize, no continuation | V05 plus generic event/count/request | No alias/initials/Onion/saved class in pixels, accessibility or denial; Core decides Accept |
| Off, no continuation | V05 only | No unsolicited wake/badge/LED/haptic or invented missed count |
| Off, exact continuation | V05 plus nonidentifying media strip | Only granted target PTT/eligible output, respecting Auto-play Off |
| Continued genuine recovery | Same authorized restricted composition | Only while grant/context generation valid |
| Continued terminal/revoked | Remove privileged controls, show release barrier if held | Stop unauthorized audio/new capture; later same-peer call cannot inherit grant |

Auth outcomes and hidden-profile rules apply throughout. Unlock refreshes facts, never reconstructs Off history or auto-plays old media. Clipboard Disabled removes Copy everywhere; allowed clipboard requires explicit warned policy choice and never exports secrets. If platform policy permits an editable opt-in, expose Copy to system clipboard under Privacy, initially Off, with the warning Copied text may be accessible to other applications. Otherwise omit that preference and Copy actions. This is a platform permission, not a new Core delivery setting. Peer content remains plain, with no executable links/markup or automatic preview requests.

## 11. Lightweight reference and acceptance matrix

This table is the reference manifest inside the companion. R denotes an existing Penpot exemplar; D a normative derived fixture composed from specified C/V rules. D does not claim a drawn or visually approved frame. The coding agent reads R via Penpot and builds D from these definitions, capturing representative variants during implementation. No separate per-state JSON registry or image collection is required.

All fixtures use functional/layout 1.0, sections 4/12 tokens, synthetic Rhea/Orion identities and fixed display clock 18:42; no production messages/keys. Sizes are logical usable rectangles. Public-contract test fixtures supply actual state/eligibility.

| Fixture | View/state and concrete setup | Composition / reference | Size; GAT anchors |
| --- | --- | --- | --- |
| L01 | DROP empty; then 1 pinned real row, 1 pending-only, 60-character alias, 130 rows | V06/C01/C03; R V06/V06E/V06L, D pin/pagination | 480×800 and 360×640; GAT-01, 17, 18, 61, 69 |
| L02 | LIVE one active, one recovering/3 pending, one ended/2 pending, one unseen/local | V07/C03; R V07/D02 | 480×800, 1180×760; GAT-04, 13, 15, 16, 25 |
| L03 | LIVE idle/calling/active/recovery/ended; inject lifecycle reject/unknown | V09/C01/C09/S04–07; R V09A/B, D variants | 360×640, 480×800; GAT-01, 11, 13, 16, 46 |
| L04 | Hold PTT while text/Voice arrive; release/finalize; repeat focus-loss and hard quota | V09/C05/C09/S08; R V09R, D failure | 360×640; GAT-06, 07, 11, 12, 47, 51 |
| L05 | DROP capture/review/play/delete/send; second hold blocked; commit unknown | V08/C09/S06; R V08/V08R/Input States, D unknown | 480×800, 360×640; GAT-10, 46, 48, 49, 51 |
| L06 | Arriving audio at 18 s behind edge, Go live, missing range, finalization, evicted own resend | V09/C05/S12; R Messages/V09A, D media failure | 360×640, 480×800; GAT-08, 14, 52–55 |
| L07 | Scroll up, 2 items arrive, N new items while audio stays paused/manual | V09/C06; R V09A/D02 | 360×640, 1180×760; GAT-09, 53, 54 |
| L08 | Rhea foreground, Orion request; Accept vs Open; second request then first expires | V10/C11/S07; R V10, D expiry | 480×800, 360×640; GAT-05, 06, 58, 60 |
| L09 | Two anonymous calls, denied Accept then unlock/revalidate; all lock modes/continuation | V05/V10/S10; R V10L/V05O, D policy variants | 360×640; GAT-20–23, 56–60 |
| L10 | PIN/password/None, escalation/cooldown/forgot PIN, hidden profile, failed restriction | V01/V04/V05/C13; R V01/V05C/Auth Keyboard, D remaining auth | 360×640, 480×800; GAT-23, 41, 42, 56, 67 |
| L11 | Switch with 1 active, 3 pending, 1 own draft; failure before old exit vs after old lock | V20/C11/C15/S11; R V20, D phases | 360×640; GAT-24, 25, 49, 62 |
| L12 | Desktop close with capture/other client; device prep failure; purge arm/cancel/initiated-only/safe/cleanup-failed/unknown | V21/V22/C15/C16/S11; R V21/V22, D results | 480×800, 1180×760; GAT-26, 27, 40, 63–66 |
| L13 | No mic/output/camera, denied permission, invalid config and absent display | V09/V14/V23/S09; R V09M/V14/V23, D service output | 360×640; GAT-35–40, 69, 72 |
| L14 | Keyboard visible; 1/3-line and 200-character unbroken input; text scale 1.5; complete Tab path | V08/V09/C04/C09/C14; R keyboard style, D minimum docking | 360×640; GAT-46, 47, 68–70 |
| L15 | Center empty/populated/aggregated/stale; 0/2 selected; Clear unknown; privacy change | V16/C08/S02/S06/S07/S10; R V16, D corrected selection | 360×640, 480×800; GAT-22, 58–60, 70 |
| L16 | Profile create invalid/busy; picker empty/active; invalid/self/duplicate QR; contact save/rename/demotion; own QR Copy disabled | V02/V03/V11–V15/C12/C13; R V12/V14, D forms/QR | 360×640; GAT-02, 03, 17–19, 41, 46, 68 |
| L17 | Bool/enum/number save reject/unknown, full-auth weakening, history disabled/clear failed, unsupported diagnostics, rotation denied | V04/V17–V20/C11–C13; R V17/V20, D forms/history | 360×640, 1180×760; GAT-23, 29, 62, 67, 68, 74 |
| L18 | Same peer at widths 959/960/1180, density 1/2, long name/copy, hover/focus/press/busy; resize during held PTT | Sections 3/6, C01–C16; R D01/D02, D boundaries | Height ≥640; GAT-06, 44, 47, 69, 70, 75 |

Acceptance: no clipped labels/inaccessible mandatory controls, no hover/focus reflow, compact body-to-metadata gap, equal adjacent corner insets, correct anonymous/masked pixels and accessible text, no implicit audio/call, no false success/consumption. Verify C14 measured docking and large-text stacking, not a bitmap zoom.

Keep comparison captures representative: root, peer text/media, minimum keyboard, form/auth, notification selection, privacy/call, lifecycle failure and wide desktop. One image can cover several components; logic tests cover state combinations. Native outputs are implementation evidence, not another design-only gallery. Judge visible ink/weight/spacing at intended scale; bounds/diff scores alone do not prove visual fidelity.

## 12. Tokens, assets and implementation handoff

### 12.1 Additional named tokens

Section 4 palette is normative. These names complete the token contract; C01–C16 measurements/formulas are component tokens, not per-screen literals. Translate into one native theme/token module; no separate delivery file is necessary.

| Token | Value / rule |
| --- | --- |
| space.xs / sm / md / lg / xl | 4 / 8 / 12 / 16 / 24 |
| size.target / iconTarget / fab | 48 / 48 / 56 |
| size.headerStart / rowGap / sectionGap | 24 / 12 / 24 |
| size.formMax / sheetMax / compactContentMax / wideContentMax | 400 / 480 / 560 / 800 |
| radius.control / surface / bubble / pill | 12 / 16 / 16 / half actual height |
| stroke.divider / boundary / focus | 1 / 1 / 2; reserved/inset, never reflow |
| icon.inline / action / status / empty | 18 / 24 / 16 / 32; 24-unit SVG viewBox |
| icon.stroke | 1.75 at 24-unit viewBox, rounded caps/joins; no emoji font |
| type.hero | Inter Tight 28/34, weight 600 |
| type.title | 23/28, weight 600; compact 22/28 |
| type.peer / emptyTitle | 20/26, weight 600 |
| type.row | 17/22, weight 600 |
| type.body | 15/20, weight 400 |
| type.button | 14/20, weight 600; optically centered visible group |
| type.support | 13/18, weight 400; field labels weight 600 |
| type.caption / pill | 12/16, weight 500 / 600 |
| type.meta | 11/14, weight 500 |
| type.rootState | 10/12, weight 600; supplemental only, never sole critical state |
| type.wordmark | 18/22, weight 700, tracking 1.5 |
| type.timer | 16/22, weight 500, tabular numerals |
| color.focus / controlBoundary | #4ED7C8 / #68777B |
| color.lockSurface | #332B48 |
| color.hoverOverlay / pressedOverlay | White at 6% / 10% over current surface |
| color.darkHoverOverlay / darkPressedOverlay | Black at 6% / 10%; use instead of white for controls with textSecondary or danger labels |
| color.scrim | #070A0B at 72%; only modal/cover excludes underlying input |
| motion.hover / pressed / overlay | 80 / 40 / 120 ms; no geometry change |
| motion.reduced / safetyCover | 0 ms; safety effects immediate |
| optical.inlineLabel / inlineIcon | +1 / −1 vertical from nominal center, Inter Tight reference only |

C01–C16 are stable roles, not mandatory class/package names. Disabled controls use surface/raised + textDisabled, with readable textSecondary reason rather than whole-container opacity. Selected DROP uses dropSurface + drop; LIVE liveSurface + live. Error uses dangerSurface + danger text/icon and reason. Information uses surface/raised + info; lock notice uses lockSurface + lock. Destructive actions normally use raised + danger label until explicit confirmation.

Readable normal text targets contrast ≥4.5:1; large text and meaningful icons/focus ≥3:1 against their actual adjacent surface. Decorative dividers may be subtle; required boundaries use controlBoundary when fill difference is insufficient. Recheck composited hover/pressed states and font fallback in native rendering. These are acceptance targets, not a claim of certified platform accessibility. No state depends solely on color or sound. Ordinary labels/body never shrink to root-state size.

### 12.2 Asset realization

Use Inter Tight upright weights 400/500/600/700, no synthetic bold where actual weights can be bundled. Redistributable source: [Google Fonts / Inter Tight](https://github.com/google/fonts/tree/main/ofl/intertight), including InterTight[wght].ttf and [OFL.txt](https://github.com/google/fonts/blob/main/ofl/intertight/OFL.txt). Package the license. If the native renderer cannot use its variable font, instantiate these four static weights at build time from the same source and record the revision. Missing production font is a packaging failure; an emergency startup error may use platform sans but is not a conforming normal UI. Extra glyph coverage uses an explicitly packaged redistributable fallback with its license; no runtime download or silent deletion of message characters. Unsupported glyphs remain visible replacement glyphs without altering canonical text.

Use the reference's simple rounded line icons. Export available native Penpot vectors when provenance permits; the production-safe standard symbol source is [Lucide SVG icons](https://github.com/lucide-icons/lucide/tree/main/icons), with its [ISC and applicable Feather-derived MIT notices](https://github.com/lucide-icons/lucide/blob/main/LICENSE). This defines the production realization, not a claim that every historical vector came from Lucide. Pin chosen source revision/local hashes during implementation packaging. No React/JS icon runtime is needed.

| Semantic asset | SVG symbol / purpose |
| --- | --- |
| Back / next | chevron-left / chevron-right |
| Notifications / contacts / settings | bell / users / settings |
| More / add / search | ellipsis / plus / search |
| PTT / no microphone | mic / mic-off |
| Play / pause / output | play / pause / volume-2; unavailable volume-x |
| Reconnect / change route | rotate-cw / refresh-cw, paired with explicit label |
| Send / delete | send / trash-2 |
| Lock / unlock method / profile | lock / key-round / user-round |
| Camera / QR / copy | camera / qr-code / copy; policy controls Copy |
| Pin / keyboard / close | pin / keyboard / x |
| Error / info / history | triangle-alert / info / history |
| Exit / power | log-out / power |
| Success / selection | check / square / square-check |
| Wordmark / badges / waveform / dots | Native text/simple geometry, no bitmap dependency |
| My contact QR | Locally generated approved public encoding, never a static fake QR |

Icon-only controls have safe accessible names and pointer tooltips; touch never depends on tooltips. Delete draft is Delete recording to accessibility, not Trash. No photo avatars, decorative bitmap pack or external emoji service. Asset acquisition happens during development/build; installed GUI operates offline with respect to fonts/icons.

### 12.3 Penpot access and precedence

File ID d8ac01df-6646-81d2-8008-9fb60724c80a; human name at finalization Design. Match by ID, since names change. Saved visual revision is v0.7, with section 7 board IDs. Pages: Foundations d8ac01df-6646-81d2-8008-9fb60724c80b; Components 39a2d0c5-e9da-8024-8008-9fbd9e9dc3f1; Device 39a2d0c5-e9da-8024-8008-9fbe6cbba7ae; Edge States 39a2d0c5-e9da-8024-8008-9fbf370a5cde; Desktop 39a2d0c5-e9da-8024-8008-9fbfd4f82678.

With access, inspect the relevant component/view and export only references needed for comparison. Penpot geometry cannot override this document's dynamic sizes, state additions or Core eligibility. Do not silently edit the design while coding. Without access, these compositions/tokens/assets still permit implementation; report unavailable visual comparison and use existing exports when present. Access failure does not authorize redesign or omitted states.

Older-example corrections: normal V16 has no selection footer; compact V09 retains End Live via C01/C14; missing forms/privacy/busy variants follow section 8; keyboard gallery cannot override C14 docking; all selectors use DROP/LIVE. Export inner application viewports, excluding screen-card captions, illustrated physical controls and simulator surround. Illustration-only engineering prose does not belong in product UI.

### 12.4 Bounded coding-agent assignment

Use functional v1.0 + layout v1.0 + accepted public SDK/Core contract as the implementation definition. Penpot is shared visual evidence. Do not restart the design phase or create a parallel token service, per-state document collection or exhaustive static gallery.

1. Record accepted repository SHA and integration capabilities under the functional gate. Preserve existing package ownership; no arbitrary shared/utils layer for this design.
2. Package the chosen font/icon subset and translate tokens into the native theme module. Record source/license/revision in ordinary repository asset/dependency records.
3. Build reusable components, then V06 → V08/V09 at reference, minimum with keyboard, and desktop. Include short/wrapped messages, input ownership, one failure, anonymous/Off restriction and real hover/focus rendering.
4. Implement every V recipe/A action with public eligibility and S states. Tests exercise enclosing view/operation boundaries, not only happy-path mocks.
5. Capture a compact comparison set covering L01–L18 families using existing test structures. Each permutation need not first be drawn in Penpot.
6. Run functional GAT groups at the appropriate layer; report visual comparison, native input/audio, installed package and physical support separately. Name actual public-contract gaps precisely.

Concrete Kivy/backend dependencies, physical drivers/display selection, codec/AEC/seek, protected preference APIs and executed tests remain implementation work already assigned by the functional contract. They are not missing screen decisions. If a technical constraint cannot realize an explicit layout rule, report the concrete conflict instead of silently weakening it.

## 13. Finalization record

This v1.0 replaces provisional v0.1/v0.2. It preserves reviewed dark/mint/amber styling and content-sized messages, completes responsive/forms/auth/keyboard/overlay/indicator definitions, V01–V23, A01–A25, S01–S12 and L01–L18.

Penpot v0.7 examples were visually reviewed during creation. This finalization verified current file/page/board identities and reconciled the written definition with functional v1.0. Newly defined variants have not all been drawn or executed in Kivy. Their definitions are complete; native rendering, owner review and functional/platform acceptance remain distinct evidence. Final means a complete implementation definition, not approval of unseen renders or a finished GUI.

Functional v1.0 remains unchanged, SHA-256 8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7. Visual baseline remains Penpot v0.7.

| Revision | Change |
| --- | --- |
| Penpot v0.3 | Native label/control centering |
| Penpot v0.4 | Optical row balance and consistent content edges |
| Penpot v0.5 | Universal LIVE copy and subdued header End Live |
| Penpot v0.6 / companion 0.1 | Content-sized bubbles, independent audio/timeline jumps, initial handoff |
| Penpot v0.7 / companion 0.2 | Shared spacing, review padding, optical icon/label balance |
| Companion 1.0 | Complete declarative view/action/state coverage, responsive/keyboard/focus/privacy rules, token/asset mapping and lightweight Penpot-assisted handoff |
