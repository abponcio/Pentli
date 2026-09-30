# Plentli interface guidelines

## Three core surfaces

1. **Donor chat:** photo plus short note intake, one clarification if facts are missing, then pickup and destination updates.
2. **Live rescue:** allocation, safety window, route, activity, recipient QR handoff, decline/re-plan, dispatch result, impact and records.
3. **Recipient offer:** offer details, Accept/Decline, expiry, in-transit update, receipt confirmation and handover record.

The driver message is a preview/detail view within this flow. A separate driver app is not in the source plan.

## Design tokens and layout

Use a 4 px spacing base with common gaps of 8, 16, 24 and 32 px. Cards have 16 px radii, buttons 10 px radii and thin `#DCE5DE` borders. Minimize shadow. Desktop content max width is around 1440 px with 32–40 px gutters; mobile gutters are 16–20 px plus safe-area insets. Touch targets are at least 44 × 44 px, preferably 48 × 48 px. Keep focus outlines visible.

Desktop operations can use three columns: food/allocation, route, activity/decision. At narrower widths, stack the activity below the route. Mobile puts status and safety before map decoration. Never require horizontal scrolling. Keep one primary action per view. A disabled action must have a visible explanation.

## Shared components

| Component | Required information |
| --- | --- |
| Brand header | Plentli wordmark, language toggle, demo status |
| Food summary | Photo, dish, portions, declared allergens, preparation and storage facts when known |
| Safety window | Deadline plus rule/source label; pending until required facts are known |
| Offer card | Recipient, portions, ETA, allergen, halal declaration if relevant, expiry, Accept and Decline |
| Allocation list | Each recipient, portions and exact offer status; totals reconcile to available food |
| Route | Pickup and ordered stops; accessible text list alongside map |
| Activity timeline | Short event labels and real state; separate optional tool details |
| Handover record | Recipient, time, dish, portions, allergens and measured temperature if captured |

## Behavioral rules

- Intake is a photo and note, with typed text as the dependable fallback. Voice is shown as functional only if built. Ask one focused question when quantity, allergen, preparation time or storage is unclear. Do not show a computed deadline before required inputs exist.
- Exclude recipients whose dietary policy conflicts with the food. A proposed split is pending until offers are accepted. A decline or expiry triggers re-planning; stale offers cannot be accepted.
- The dispatch button is gated by code checks for diet, capacity and ETA versus the approved safety rule. On failure show **Dispatch paused**, exact reason, next step and **No messages sent**. AI cannot override that result.
- Driver **Delivered** and recipient **Received** are separate events. If quantity is disputed, do not mark the full count received. Count impact only after confirmed handover.
- Show food weight and CO₂e as **Not calculated** without a verified weight basis and cited factor. Do not fabricate measured temperature.
- Replace the illustrative **DEMO QR** image with a working QR encoding the reachable offer URL.

## Accessibility and localization

Use semantic buttons, labels, headings and logical focus order. Announce important status changes, but do not announce every timer second. Keep mobile body text at least 16 px, preserve keyboard access and check contrast. Every status uses text plus icon, never color alone. Give food images meaningful alt text and provide route details in text. Respect reduced-motion preferences.

For Arabic, switch layout direction to RTL, mirror directional controls and chat alignment, use reviewed Arabic copy, and isolate times, IDs and Latin van identifiers with LTR/bidi isolation. Keep the Latin Plentli wordmark unchanged. Test mixed Arabic/English strings and small-screen wrapping.

## Reference-image limitations

The PNGs are high-fidelity concept boards. Some illustrative times and small labels do not form a single continuous run. Implement one coherent seeded clock and use this document plus `SCREEN_MAP.md` as the copy/behavior source of truth. Map geography and recipient positions are illustrative. The 22:00 deadline is a **Demo rule**, not operational food-safety advice.
