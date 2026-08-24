# Preserve Active Task Context Across Session Refreshes

Written against: `02932a6981347cf60d722f6cb47743ddc1c92f0f`

## Evidence chain

- Surface: the left task/session sidebar and its synchronization with the center conversation and right workbench in `ui/index.html`.
- Problem: `loadSessions()` rebuilds the session-item DOM, but marks a row active only when there is no `currentSession`. After selecting a second task and refreshing the list, neither row retains `.active`, while the center and right panels still display the selected task. The visual context and application state diverge.
- Design evidence: `DESIGN.md` defines “conversation = paper task = session = dedicated knowledge base” and requires those contexts to switch together. The existing `.session-item.active` treatment is the established owner of visible selection state.
- Owner: session state and rendering functions in `ui/index.html`, especially `loadSessions()`, `sessionItemHtml()`, session opening, and deletion/reselection paths.
- Scope and affected surfaces: initial load, manual task selection, refresh after workflow actions, creation, deletion, and any operation that calls `loadSessions()`. The center and right panels must remain synchronized with the selected session.
- Uncertainty: the API's ordering determines the fallback task when the selected task no longer exists. Preserve that ordering rather than inventing a client-side recency policy.

## Design decision

Make `currentSession` the single source of truth during every session-list render. If its id is still present, render the matching row with `.active` and expose `aria-current="true"` on its primary open control. If it is absent, clear the stale selection, select the first API-ordered task when available, and load its details exactly once. If no tasks exist, render the existing empty state and clear all dependent panels.

Refreshing the list must not silently switch tasks merely because the DOM was recreated. Keep the existing request-race guard so a slower detail response cannot overwrite a newer selection.

## Reuse

- Reuse `currentSession`, `sessionDetailRequest`, the current session-item markup, and the existing open/load functions.
- Reuse `.session-item.active` visual styling; do not add a second selection color or indicator.
- Reuse the API's task order for fallback selection.

## Changes

1. In `ui/index.html`, separate selection resolution from session-item markup creation so each render can determine the selected id before inserting rows.
2. Update `sessionItemHtml()` or its caller to apply `.active` whenever an item's id equals `currentSession.id`, not only during the first load.
3. Add `aria-current="true"` to the selected row's primary task-opening control and omit it from other rows.
4. In `loadSessions()`, handle the three explicit states:
   - current task still exists: retain it and do not reload unrelated details;
   - current task was removed: select the first remaining task and synchronize all panels once;
   - no tasks remain: clear selection and dependent task content.
5. Extend the UI regression coverage under `tests/` for selection preservation and the deletion fallback. Prefer testing a small deterministic selection helper plus a browser-level smoke check over assertions against implementation text alone.
6. After acceptance, update `README.md` with the completed interaction-hardening stage and new test count.

## Scope

- In: selection state, active-row rendering, accessibility state, refresh/delete fallbacks, and targeted regression tests.
- Out: sidebar visual redesign, task reordering, multi-select, URL routing, or persistence of the active task across separate browser launches.

## Validation

- Create at least two tasks, select the second, call the normal list-refresh path, and confirm the second row remains visibly active while the center and right panels still show it.
- Trigger a workflow action that refreshes the list and confirm selection remains unchanged.
- Delete the active task and confirm the first remaining API-ordered task becomes active and all three panels synchronize once.
- Delete the final task and confirm the empty state contains no stale title, stage, evidence, or knowledge-base context.
- Navigate task controls by keyboard and confirm the selected task exposes `aria-current="true"`.
- Run targeted UI tests and the full repository test suite.

## Stop conditions

- Stop if the API does not return stable task ids; selection cannot be preserved safely without a stable identity.
- Stop if `loadSessions()` is discovered to run concurrently from multiple uncontrolled callers; first define or preserve a request-order guard rather than allowing stale list responses to win.
- Do not introduce browser-storage persistence unless it is separately approved.

## Design documentation

No `DESIGN.md` update is required because the change enforces the existing synchronized-context rule. Update the README stage history after the implementation passes regression tests.
