# Make Task Search Functional and Predictable

Written against: `02932a6981347cf60d722f6cb47743ddc1c92f0f`

## Evidence chain

- Surface: the task-search input above the left session list in `ui/index.html`.
- Problem: the field is rendered and localized but has no input handler or filtering behavior. Entering a query leaves every task visible and provides no result feedback, so the control promises an interaction it does not perform.
- Design evidence: `DESIGN.md` treats the sidebar as the user's task navigator and requires the current task to remain legible on the first screen. Search should narrow navigation without changing the active paper context.
- Owner: task-list state, rendering, and search input wiring in `ui/index.html`; targeted UI regression coverage under `tests/`.
- Scope and affected surfaces: filtering the already-loaded task collection, empty/no-match feedback, result accessibility, localization, and interaction with the active selection.
- Uncertainty: the current client list is appropriate for local filtering. If task volumes are expected to exceed roughly 500 entries or the API becomes paginated, server-side search should be designed separately rather than hidden inside this change.

## Design decision

Keep the API result as an in-memory session cache and render a normalized client-side subset as the user types. Match case-insensitively after trimming whitespace against the task title and other already-visible navigation metadata, such as degree/type or current workflow stage when those fields are present. Use a short 150 ms debounce to avoid needless DOM churn without making the field feel delayed.

Filtering must never change `currentSession`. If the active task does not match, it may be absent from the filtered list while the center and right panels continue showing it; clearing the query restores its active row. Provide an explicit localized no-match state and a polite live result count. Escape clears the query and restores the full list.

## Reuse

- Reuse the existing search input, localization dictionary, session-item template, empty-state styling, and active-selection logic.
- Reuse the session data already returned by `loadSessions()`; do not add an API call per keystroke.
- Reuse the corrected selection renderer from `02-preserve-active-session.md` so filtering and refresh share one item-rendering path.

## Changes

1. Implement this plan after `02-preserve-active-session.md` so search can call the same deterministic session renderer.
2. In `ui/index.html`, retain the latest successful session list in a dedicated cache and split API loading from list rendering.
3. Bind the existing search input to a debounced filter function. Normalize the query and candidate fields consistently for Latin text, Chinese text, whitespace, and case.
4. Render filtered rows through the shared renderer without changing `currentSession` or reloading session details.
5. Add a localized no-match message distinct from the no-tasks-yet state, plus a visually appropriate `aria-live="polite"` result-status element. Ensure Chinese and English strings are both supplied.
6. Support Escape to clear the field, restore all cached tasks, and return focus to the search input. If a visible clear affordance already exists in the design system, reuse it; otherwise keyboard and full-text deletion are sufficient for this stage.
7. Add UI regression coverage for empty query, whitespace-only query, case-insensitive Latin text, Chinese text, emoji or punctuation, no matches, Escape clearing, and preservation of the current task.
8. After acceptance, update `README.md` with the completed interaction-hardening stage and final test count.

## Scope

- In: client-side filtering, cache/render separation, localized status states, accessibility feedback, keyboard clearing, and regression tests.
- Out: backend full-text search, ranking, fuzzy matching, saved searches, highlighted substrings, pagination, or task sorting changes.

## Validation

- With multiple tasks loaded, type a unique title fragment and confirm only matching rows remain.
- Verify matching for mixed-case Latin titles, Chinese titles, leading/trailing spaces, and punctuation.
- Enter a guaranteed no-match phrase and confirm the localized no-match state and live result count are announced.
- Select a task, filter it out, and confirm the center/right context is unchanged; clear the query and confirm its row returns active.
- Press Escape with a non-empty query and confirm the full cached list returns without an additional network request.
- Switch the UI language and confirm the placeholder, no-match state, and result status use the selected locale.
- Run targeted UI tests, browser smoke checks, and the full repository test suite.

## Stop conditions

- Stop and redesign if the session API is paginated or does not return the full searchable set.
- Stop if the task collection can be large enough to make client-side filtering visibly slow; define a server search contract first.
- Do not make filtering alter or clear `currentSession`.

## Design documentation

No `DESIGN.md` change is required because search already exists in the documented sidebar surface. After acceptance, record the now-functional behavior and verification in `README.md`.
