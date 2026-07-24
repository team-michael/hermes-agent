---
name: accessibility
description: Use when auditing or improving WCAG 2.2 web accessibility, a11y, screen reader support, keyboard navigation, accessible UI, or WCAG compliance.
license: MIT
metadata:
  author: web-quality-skills
  version: "1.1"
  upstream-revision: "95d6e255afe1596b557d7a8498517884438f5b3a"
  bg-patch: "security-1"
---

# Accessibility (a11y)

> Provenance: MIT-licensed BG compatibility copy of `addyosmani/web-quality-skills` revision `95d6e255afe1596b557d7a8498517884438f5b3a`, with security-only edits.

Comprehensive accessibility guidelines based on WCAG 2.2 and Lighthouse accessibility audits. Goal: make content usable by everyone, including people with disabilities.

## WCAG Principles: POUR

| Principle | Description |
|-----------|-------------|
| **P**erceivable | Content can be perceived through different senses |
| **O**perable | Interface can be operated by all users |
| **U**nderstandable | Content and interface are understandable |
| **R**obust | Content works with assistive technologies |

## Conformance levels

| Level | Requirement | Target |
|-------|-------------|--------|
| **A** | Minimum accessibility | Must pass |
| **AA** | Standard compliance | Should pass (legal requirement in many jurisdictions) |
| **AAA** | Enhanced accessibility | Nice to have |

---

## Perceivable

### Text alternatives (1.1)

**Images require alt text.**

Bad — missing alt:

```html
<img src="chart.png">
```

Good — descriptive alt:

```html
<img src="chart.png" alt="Bar chart showing 40% increase in Q3 sales">
```

Good — decorative image with empty alt:

```html
<img src="decorative-border.png" alt="" role="presentation">
```

Good — complex image with a longer description:

```html
<figure>
  <img src="infographic.png" alt="2024 market trends infographic"
       aria-describedby="infographic-desc">
  <figcaption id="infographic-desc">
    Revenue increased in all four regions, led by 40% growth in the west.
  </figcaption>
</figure>
```

**Icon buttons need accessible names.**

Bad — no accessible name:

```html
<button>
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <path d="M4 6h16v2H4zM4 11h16v2H4zM4 16h16v2H4z"></path>
  </svg>
</button>
```

Good — use `aria-label`:

```html
<button aria-label="Open menu">
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <path d="M4 6h16v2H4zM4 11h16v2H4zM4 16h16v2H4z"></path>
  </svg>
</button>
```

Good — use visually hidden text:

```html
<button>
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <path d="M4 6h16v2H4zM4 11h16v2H4zM4 16h16v2H4z"></path>
  </svg>
  <span class="visually-hidden">Open menu</span>
</button>
```

**Visually hidden class:**
```css
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

### Color contrast (1.4.3, 1.4.6)

| Text Size | AA minimum | AAA enhanced |
|-----------|------------|--------------|
| Normal text (< 18px / < 14px bold) | 4.5:1 | 7:1 |
| Large text (≥ 18px / ≥ 14px bold) | 3:1 | 4.5:1 |
| UI components & graphics | 3:1 | 3:1 |

```css
/* ❌ Low contrast (2.5:1) */
.low-contrast {
  color: #999;
  background: #fff;
}

/* ✅ Sufficient contrast (7:1) */
.high-contrast {
  color: #333;
  background: #fff;
}

/* ✅ Focus states need contrast too (3:1 against background, WCAG 1.4.11) */
:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}
```

**Don't rely on color alone.**

Bad — only color indicates the error:

```html
<input class="error-border">
<style>.error-border { border-color: red; }</style>
```

Good — combine color, an icon, and text:

```html
<div class="field-error">
  <input aria-invalid="true" aria-describedby="email-error">
  <span id="email-error" class="error-message">
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10"></circle>
      <path d="M12 6v8M12 18h.01"></path>
    </svg>
    Please enter a valid email address
  </span>
</div>
```

### Media alternatives (1.2)

Video with captions:

```html
<video controls>
  <source src="video.mp4" type="video/mp4">
  <track kind="captions" src="captions.vtt" srclang="en" label="English" default>
  <track kind="descriptions" src="descriptions.vtt" srclang="en" label="Descriptions">
</video>
```

Audio with a transcript:

```html
<audio controls>
  <source src="podcast.mp3" type="audio/mp3">
</audio>
<details>
  <summary>Transcript</summary>
  <p>Full transcript text...</p>
</details>
```

---

## Operable

### Keyboard accessible (2.1)

**All functionality must be keyboard accessible.** Prefer native interactive elements — `<button>`, `<a href>`, and form controls handle Enter/Space activation, focus, and assistive-tech semantics for free. Only add manual keyboard handling when you cannot use a native element.

Bad — a click-only non-interactive element is not focusable and has no keyboard activation:

```html
<div class="card" onclick="handleAction()">Open</div>
```

Good — prefer a native button:

```html
<button type="button" onclick="handleAction()">Open</button>
```

```javascript
// ✅ When you MUST use a non-interactive element (e.g. div with role="button"),
// make it focusable AND handle keyboard activation. Do NOT add this to a native
// <button> — Enter/Space already fire click, so you'd double-trigger.
element.setAttribute('role', 'button');
element.setAttribute('tabindex', '0');
element.addEventListener('click', handleAction);
element.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    handleAction();
  }
});
```

**No keyboard traps.** Users must be able to Tab into and out of every component. Use the [modal focus trap pattern](references/A11Y-PATTERNS.md#modal-focus-trap) for dialogs—the native `<dialog>` element handles this automatically.

### Focus visible (2.4.7)

```css
/* ❌ Never remove focus outlines */
*:focus { outline: none; }

/* ✅ Use :focus-visible for keyboard-only focus */
:focus {
  outline: none;
}

:focus-visible {
  outline: 2px solid currentColor; /* inherits text color → already contrast-checked */
  outline-offset: 2px;
}

/* ✅ Or pick a brand color and verify ≥3:1 contrast against every background it lands on */
button:focus-visible {
  box-shadow: 0 0 0 3px rgba(0, 95, 204, 0.5);
}
```

### Focus not obscured (2.4.11) — new in 2.2

When an element receives keyboard focus, it must not be entirely hidden by other author-created content such as sticky headers, footers, or overlapping panels. At Level AAA (2.4.12), no part of the focused element may be hidden.

```css
/* ✅ Account for sticky headers when scrolling to focused elements */
:target {
  scroll-margin-top: 80px;
}

/* ✅ Ensure focused items clear fixed/sticky bars */
:focus {
  scroll-margin-top: 80px;
  scroll-margin-bottom: 60px;
}
```

### Skip links (2.4.1)

Provide a skip link so keyboard users can bypass repetitive navigation. See the [skip link pattern](references/A11Y-PATTERNS.md#skip-link) for full markup and styles.

### Target size (2.5.8) — new in 2.2

Interactive targets must be at least **24 × 24 CSS pixels** (AA). Exceptions: inline text links, elements where the browser controls the size, and targets where a 24px circle centered on the bounding box does not overlap another target.

```css
/* ✅ Minimum target size */
button,
[role="button"],
input[type="checkbox"] + label,
input[type="radio"] + label {
  min-width: 24px;
  min-height: 24px;
}

/* ✅ Comfortable target size (recommended 44×44) */
.touch-target {
  min-width: 44px;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
```

### Dragging movements (2.5.7) — new in 2.2

Any action that requires dragging must have a single-pointer alternative (e.g., buttons, inputs). See the [dragging movements pattern](references/A11Y-PATTERNS.md#dragging-movements) for a sortable-list example.

### Timing (2.2)

```javascript
// Allow users to extend time limits
function showSessionWarning() {
  const modal = createModal({
    title: 'Session Expiring',
    content: 'Your session will expire in 2 minutes.',
    actions: [
      { label: 'Extend session', action: extendSession },
      { label: 'Log out', action: logout }
    ],
    timeout: 120000
  });
}
```

### Motion (2.3)

```css
/* Respect reduced motion preference */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

---

## Understandable

### Page language (3.1.1)

Bad — no page language:

```html
<html>
```

Good — specify the page language:

```html
<html lang="en">
```

Good — mark a language change within the page:

```html
<p>The French word for hello is <span lang="fr">bonjour</span>.</p>
```

### Consistent navigation (3.2.3)

Use consistent navigation across pages:

```html
<nav aria-label="Main">
  <ul>
    <li><a href="/" aria-current="page">Home</a></li>
    <li><a href="/products">Products</a></li>
    <li><a href="/about">About</a></li>
  </ul>
</nav>
```

### Consistent help (3.2.6) — new in 2.2

If a help mechanism (contact info, chat widget, FAQ link, self-help option) is repeated across multiple pages, it must appear in the **same relative order** each time. Users who rely on consistent placement shouldn't have to hunt for help on every page.

### Form labels (3.3.2)

Every input needs a programmatically associated label. See the [form labels pattern](references/A11Y-PATTERNS.md#form-labels) for explicit, implicit, and instructional examples.

### Error handling (3.3.1, 3.3.3)

Announce errors to screen readers with `role="alert"` or `aria-live`, set `aria-invalid="true"` on invalid fields, and focus the first error on submit. See the [error handling pattern](references/A11Y-PATTERNS.md#error-handling) for full markup and JS.

### Redundant entry (3.3.7) — new in 2.2

Don't force users to re-enter information they already provided in the same session. Auto-populate from earlier steps, or let users select from previously entered values. Exceptions: security re-confirmation and content that has expired.

Good — auto-fill the shipping address from billing:

```html
<fieldset>
  <legend>Shipping address</legend>
  <label>
    <input type="checkbox" id="same-as-billing" checked>
    Same as billing address
  </label>
  <label for="shipping-street">Street address</label>
  <input id="shipping-street" autocomplete="shipping street-address"
         value="123 Main Street">
</fieldset>
```

### Accessible authentication (3.3.8) — new in 2.2

Login flows must not rely on cognitive function tests (e.g., remembering a password, solving a puzzle) unless at least one of:
- A copy-paste or autofill mechanism is available
- An alternative method exists (e.g., passkey, SSO, email link)
- The test uses object recognition or personal content (AA only; AAA removes this exception)

Good — allow paste and autofill in password fields:

```html
<input type="password" id="password" autocomplete="current-password">
```

Good — offer passwordless alternatives:

```html
<button type="button">Sign in with passkey</button>
<button type="button">Email me a login link</button>
```

---

## Robust

### ARIA usage (4.1.2)

**Prefer native elements.**

Bad — ARIA role on a `div`:

```html
<div role="button" tabindex="0">Click me</div>
```

Good — native button:

```html
<button>Click me</button>
```

Bad — ARIA checkbox:

```html
<div role="checkbox" aria-checked="false">Option</div>
```

Good — native checkbox:

```html
<label><input type="checkbox"> Option</label>
```

**When ARIA is needed,** use the correct roles and states. See the [ARIA tabs pattern](references/A11Y-PATTERNS.md#aria-tabs) for a complete tablist example.

### Live regions (4.1.3)

Use `aria-live` regions to announce dynamic content changes without moving focus. See the [live regions pattern](references/A11Y-PATTERNS.md#live-regions-and-notifications) for markup and a `showNotification()` helper.

---

## Testing checklist

### Automated testing
```bash
# Lighthouse accessibility audit
npx --yes lighthouse@13.4.0 https://example.com --only-categories=accessibility

# axe-core
npx --yes @axe-core/cli@4.12.1 https://example.com
```

### Manual testing

- [ ] **Keyboard navigation:** Tab through entire page, use Enter/Space to activate
- [ ] **Screen reader:** Test with VoiceOver (Mac), NVDA (Windows), or TalkBack (Android)
- [ ] **Zoom:** Content usable at 200% zoom
- [ ] **High contrast:** Test with Windows High Contrast Mode
- [ ] **Reduced motion:** Test with `prefers-reduced-motion: reduce`
- [ ] **Focus order:** Logical and follows visual order
- [ ] **Target size:** Interactive elements meet 24×24px minimum

See the [screen reader commands reference](references/A11Y-PATTERNS.md#screen-reader-commands) for VoiceOver and NVDA shortcuts.

---

## Common issues by impact

### Critical (fix immediately)
1. Missing form labels
2. Missing image alt text
3. Insufficient color contrast
4. Keyboard traps
5. No focus indicators

### Serious (fix before launch)
1. Missing page language
2. Missing heading structure
3. Non-descriptive link text
4. Auto-playing media
5. Missing skip links

### Moderate (fix soon)
1. Missing ARIA labels on icons
2. Inconsistent navigation
3. Missing error identification
4. Timing without controls
5. Missing landmark regions

## References

- [WCAG 2.2 Quick Reference](https://www.w3.org/WAI/WCAG22/quickref/)
- [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [Deque axe Rules](https://dequeuniversity.com/rules/axe/)
- [Web Quality Audit](https://github.com/addyosmani/web-quality-skills/blob/95d6e255afe1596b557d7a8498517884438f5b3a/skills/web-quality-audit/SKILL.md)
- [WCAG criteria reference](references/WCAG.md)
- [Accessibility code patterns](references/A11Y-PATTERNS.md)
