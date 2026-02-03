/**
 * ARIA Snapshot Library for Safari Browser Automation
 *
 * Extracts an accessibility tree from the DOM and generates numbered refs
 * that can be used to interact with elements.
 *
 * Output format:
 *   [e1] button "Search"
 *   [e2] textbox "Email" value="user@example.com"
 *   [e3] link "Sign up"
 *
 * Usage (in Safari via AppleScript):
 *   const result = window.__ariaSnapshot();
 *   // result.snapshot - human-readable text
 *   // result.refs - mapping of ref IDs to element info
 */

(function() {
  'use strict';

  // ARIA roles considered interactive (user can act on them)
  const INTERACTIVE_ROLES = new Set([
    'button', 'link', 'textbox', 'checkbox', 'radio', 'combobox',
    'listbox', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
    'option', 'searchbox', 'slider', 'spinbutton', 'switch',
    'tab', 'treeitem'
  ]);

  // ARIA roles for content/structure
  const CONTENT_ROLES = new Set([
    'heading', 'img', 'article', 'main', 'navigation', 'region',
    'banner', 'contentinfo', 'complementary', 'form', 'search'
  ]);

  // Elements that are inherently interactive
  const INTERACTIVE_TAGS = new Set([
    'a', 'button', 'input', 'select', 'textarea', 'details', 'summary'
  ]);

  // Input types that are interactive
  const INTERACTIVE_INPUT_TYPES = new Set([
    'text', 'password', 'email', 'tel', 'url', 'search', 'number',
    'date', 'time', 'datetime-local', 'month', 'week', 'color',
    'file', 'checkbox', 'radio', 'submit', 'reset', 'button'
  ]);

  /**
   * Get the ARIA role of an element
   */
  function getRole(el) {
    // Explicit role attribute takes precedence
    const explicitRole = el.getAttribute('role');
    if (explicitRole) {
      return explicitRole.split(' ')[0]; // Take first role if multiple
    }

    // Implicit roles based on tag
    const tag = el.tagName.toLowerCase();

    switch (tag) {
      case 'a':
        return el.hasAttribute('href') ? 'link' : null;
      case 'button':
        return 'button';
      case 'input': {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        switch (type) {
          case 'checkbox': return 'checkbox';
          case 'radio': return 'radio';
          case 'submit':
          case 'reset':
          case 'button': return 'button';
          case 'range': return 'slider';
          case 'search': return 'searchbox';
          default: return 'textbox';
        }
      }
      case 'select':
        return el.hasAttribute('multiple') ? 'listbox' : 'combobox';
      case 'textarea':
        return 'textbox';
      case 'img':
        return 'img';
      case 'h1': case 'h2': case 'h3': case 'h4': case 'h5': case 'h6':
        return 'heading';
      case 'nav':
        return 'navigation';
      case 'main':
        return 'main';
      case 'header':
        return 'banner';
      case 'footer':
        return 'contentinfo';
      case 'aside':
        return 'complementary';
      case 'form':
        return 'form';
      case 'article':
        return 'article';
      case 'section':
        return el.hasAttribute('aria-label') || el.hasAttribute('aria-labelledby')
          ? 'region' : null;
      case 'ul': case 'ol':
        return 'list';
      case 'li':
        return 'listitem';
      case 'table':
        return 'table';
      case 'tr':
        return 'row';
      case 'td':
        return 'cell';
      case 'th':
        return 'columnheader';
      case 'option':
        return 'option';
      default:
        return null;
    }
  }

  /**
   * Get the accessible name of an element
   */
  function getAccessibleName(el) {
    // aria-label takes precedence
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) {
      return ariaLabel.trim();
    }

    // aria-labelledby
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const labels = labelledBy.split(' ')
        .map(id => document.getElementById(id))
        .filter(Boolean)
        .map(labelEl => labelEl.textContent)
        .join(' ');
      if (labels.trim()) {
        return labels.trim();
      }
    }

    const tag = el.tagName.toLowerCase();

    // For inputs, check associated label
    if (tag === 'input' || tag === 'select' || tag === 'textarea') {
      const id = el.getAttribute('id');
      if (id) {
        const label = document.querySelector(`label[for="${id}"]`);
        if (label) {
          return label.textContent.trim();
        }
      }
      // Check placeholder
      const placeholder = el.getAttribute('placeholder');
      if (placeholder) {
        return placeholder.trim();
      }
      // Check name attribute as fallback
      const name = el.getAttribute('name');
      if (name) {
        return name;
      }
    }

    // For images
    if (tag === 'img') {
      return el.getAttribute('alt') || '';
    }

    // For buttons and links, use text content
    if (tag === 'button' || tag === 'a') {
      // Check for aria-label first (already done above)
      // Then use text content
      const text = el.textContent.trim();
      if (text) {
        return text.substring(0, 100); // Limit length
      }
      // For links, use title or href as fallback
      if (tag === 'a') {
        return el.getAttribute('title') || '';
      }
    }

    // For headings, use text content
    if (/^h[1-6]$/.test(tag)) {
      return el.textContent.trim().substring(0, 100);
    }

    return '';
  }

  /**
   * Get the current value of an element (for inputs)
   */
  function getValue(el) {
    const tag = el.tagName.toLowerCase();

    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'checkbox' || type === 'radio') {
        return el.checked ? 'checked' : 'unchecked';
      }
      if (type === 'password') {
        return el.value ? '••••••' : '';
      }
      return el.value || '';
    }

    if (tag === 'textarea') {
      return el.value || '';
    }

    if (tag === 'select') {
      const selected = el.options[el.selectedIndex];
      return selected ? selected.text : '';
    }

    return null;
  }

  /**
   * Check if element is visible
   */
  function isVisible(el) {
    if (!el.offsetParent && el.tagName.toLowerCase() !== 'body') {
      return false;
    }
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') {
      return false;
    }
    if (parseFloat(style.opacity) === 0) {
      return false;
    }
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
      return false;
    }
    return true;
  }

  /**
   * Check if element is interactive
   */
  function isInteractive(el, role) {
    if (INTERACTIVE_ROLES.has(role)) {
      return true;
    }

    const tag = el.tagName.toLowerCase();
    if (INTERACTIVE_TAGS.has(tag)) {
      return true;
    }

    // Check for click handlers or tabindex
    if (el.hasAttribute('onclick') || el.hasAttribute('tabindex')) {
      return true;
    }

    // Check for contenteditable
    if (el.getAttribute('contenteditable') === 'true') {
      return true;
    }

    return false;
  }

  /**
   * Get CSS selector for element (for debugging/fallback)
   */
  function getSelector(el) {
    if (el.id) {
      return `#${el.id}`;
    }

    const tag = el.tagName.toLowerCase();
    const classes = Array.from(el.classList).slice(0, 2).join('.');

    let selector = tag;
    if (classes) {
      selector += '.' + classes;
    }

    return selector;
  }

  /**
   * Store element reference for later interaction
   */
  const elementRefs = new Map();

  /**
   * Main function: Generate ARIA snapshot
   */
  function generateSnapshot(options = {}) {
    const {
      interactiveOnly = true,  // Only include interactive elements
      maxDepth = 10,           // Maximum nesting depth
      maxElements = 200,       // Maximum elements to include
      includeValues = true     // Include current values
    } = options;

    // Clear previous refs
    elementRefs.clear();

    const lines = [];
    const refs = {};
    let refCounter = 1;
    let elementCount = 0;

    function processElement(el, depth = 0) {
      if (elementCount >= maxElements) return;
      if (depth > maxDepth) return;
      if (!isVisible(el)) return;

      const role = getRole(el);
      const interactive = isInteractive(el, role);

      // Skip if interactiveOnly and not interactive
      if (interactiveOnly && !interactive && !CONTENT_ROLES.has(role)) {
        // Still process children
        for (const child of el.children) {
          processElement(child, depth);
        }
        return;
      }

      // Skip elements without meaningful role
      if (!role && !interactive) {
        for (const child of el.children) {
          processElement(child, depth);
        }
        return;
      }

      const name = getAccessibleName(el);
      const value = includeValues ? getValue(el) : null;

      // Generate ref ID
      const ref = `e${refCounter++}`;
      elementCount++;

      // Store element for later interaction
      elementRefs.set(ref, el);

      // Build line
      const indent = '  '.repeat(depth);
      let line = `${indent}[${ref}] ${role || 'element'}`;

      if (name) {
        line += ` "${name.substring(0, 60)}${name.length > 60 ? '...' : ''}"`;
      }

      if (value !== null && value !== '') {
        const displayValue = value.substring(0, 40);
        line += ` value="${displayValue}${value.length > 40 ? '...' : ''}"`;
      }

      // Add additional attributes for context
      const tag = el.tagName.toLowerCase();
      if (tag === 'input') {
        const type = el.getAttribute('type') || 'text';
        if (!['text', 'submit', 'button'].includes(type)) {
          line += ` [${type}]`;
        }
      }

      if (el.disabled) {
        line += ' [disabled]';
      }

      if (el.required) {
        line += ' [required]';
      }

      lines.push(line);

      // Store ref info
      refs[ref] = {
        role: role || 'element',
        name: name || null,
        value: value,
        tag: tag,
        selector: getSelector(el),
        interactive: interactive,
        rect: el.getBoundingClientRect()
      };

      // Process children (for structural elements)
      if (!interactiveOnly || CONTENT_ROLES.has(role)) {
        for (const child of el.children) {
          processElement(child, depth + 1);
        }
      }
    }

    // Start from body
    processElement(document.body);

    return {
      snapshot: lines.join('\n'),
      refs: refs,
      url: window.location.href,
      title: document.title,
      timestamp: new Date().toISOString(),
      stats: {
        totalElements: elementCount,
        interactiveElements: Object.values(refs).filter(r => r.interactive).length
      }
    };
  }

  /**
   * Get element by ref ID
   */
  function getElementByRef(ref) {
    return elementRefs.get(ref) || null;
  }

  /**
   * Random delay helper (returns a promise)
   */
  function randomDelay(minMs = 50, maxMs = 150) {
    const delay = Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
    return new Promise(resolve => setTimeout(resolve, delay));
  }

  /**
   * Simulate realistic mouse events on an element
   */
  function simulateMouseEvents(el, x, y) {
    const eventOptions = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
      button: 0
    };

    el.dispatchEvent(new MouseEvent('mouseover', eventOptions));
    el.dispatchEvent(new MouseEvent('mouseenter', { ...eventOptions, bubbles: false }));
    el.dispatchEvent(new MouseEvent('mousemove', eventOptions));
    el.dispatchEvent(new MouseEvent('mousedown', eventOptions));
    el.dispatchEvent(new MouseEvent('mouseup', eventOptions));
    el.dispatchEvent(new MouseEvent('click', eventOptions));
  }

  /**
   * Click element by ref (with human-like behavior)
   */
  function clickByRef(ref) {
    const el = getElementByRef(ref);
    if (!el) {
      return { success: false, error: `Element ${ref} not found. Run snapshot again.` };
    }

    try {
      // Scroll into view with smooth behavior
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // Get element position for realistic mouse events
      const rect = el.getBoundingClientRect();
      const x = rect.left + rect.width / 2 + (Math.random() * 10 - 5);
      const y = rect.top + rect.height / 2 + (Math.random() * 10 - 5);

      // Focus if focusable
      if (typeof el.focus === 'function') {
        el.focus();
      }

      // Simulate realistic mouse events
      simulateMouseEvents(el, x, y);

      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Simulate keyboard event for a single character
   */
  function simulateKeyPress(el, char) {
    const keyEventOptions = {
      key: char,
      code: char.length === 1 ? `Key${char.toUpperCase()}` : char,
      charCode: char.charCodeAt(0),
      keyCode: char.charCodeAt(0),
      which: char.charCodeAt(0),
      bubbles: true,
      cancelable: true
    };

    el.dispatchEvent(new KeyboardEvent('keydown', keyEventOptions));
    el.dispatchEvent(new KeyboardEvent('keypress', keyEventOptions));

    // Update value
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      el.value += char;
    } else if (el.getAttribute('contenteditable') === 'true') {
      el.textContent += char;
    }

    el.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      cancelable: true,
      inputType: 'insertText',
      data: char
    }));

    el.dispatchEvent(new KeyboardEvent('keyup', keyEventOptions));
  }

  /**
   * Type text into element by ref (with human-like character-by-character input)
   */
  function typeByRef(ref, text, options = {}) {
    const { clear = true, submit = false } = options;
    const el = getElementByRef(ref);

    if (!el) {
      return { success: false, error: `Element ${ref} not found. Run snapshot again.` };
    }

    try {
      // Scroll into view smoothly
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // Click to focus (more realistic than just focus())
      const rect = el.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;
      simulateMouseEvents(el, x, y);

      // Focus
      el.focus();

      // Clear if requested (simulate Ctrl+A then Delete)
      if (clear && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
        el.value = '';
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }

      // Type character by character (simulates real typing)
      for (let i = 0; i < text.length; i++) {
        simulateKeyPress(el, text[i]);
      }

      // Final change event
      el.dispatchEvent(new Event('change', { bubbles: true }));

      // Submit if requested
      if (submit) {
        const form = el.closest('form');
        if (form) {
          // Simulate Enter key before submit
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
          el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
          form.submit();
        } else {
          // Simulate Enter key
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
          el.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', bubbles: true }));
          el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
        }
      }

      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Select option by ref
   */
  function selectByRef(ref, value) {
    const el = getElementByRef(ref);

    if (!el) {
      return { success: false, error: `Element ${ref} not found. Run snapshot again.` };
    }

    try {
      if (el.tagName !== 'SELECT') {
        return { success: false, error: `Element ${ref} is not a select element` };
      }

      // Find option by value or text
      let found = false;
      for (const option of el.options) {
        if (option.value === value || option.text === value) {
          el.value = option.value;
          found = true;
          break;
        }
      }

      if (!found) {
        return { success: false, error: `Option "${value}" not found in select` };
      }

      // Trigger change event
      el.dispatchEvent(new Event('change', { bubbles: true }));

      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Get text content by ref
   */
  function getTextByRef(ref) {
    const el = getElementByRef(ref);

    if (!el) {
      return { success: false, error: `Element ${ref} not found. Run snapshot again.` };
    }

    return { success: true, text: el.textContent.trim() };
  }

  /**
   * Scroll element into view by ref
   */
  function scrollToRef(ref) {
    const el = getElementByRef(ref);

    if (!el) {
      return { success: false, error: `Element ${ref} not found. Run snapshot again.` };
    }

    try {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Detect and dismiss cookie consent banners
   * Returns true if a consent banner was found and dismissed
   */
  function dismissCookieConsent() {
    // Common cookie consent button patterns
    const consentPatterns = [
      // Text patterns for accept buttons
      /accept all/i, /accept cookies/i, /agree/i, /got it/i, /i agree/i,
      /allow all/i, /allow cookies/i, /ok/i, /consent/i, /continue/i,
      /akzeptieren/i, /alle akzeptieren/i, /einverstanden/i,  // German
      /accepter/i, /tout accepter/i, /j'accepte/i  // French
    ];

    // Common selectors for consent buttons
    const consentSelectors = [
      '[data-testid*="accept"]', '[data-testid*="consent"]',
      '[id*="accept"]', '[id*="consent"]', '[id*="cookie"]',
      '[class*="accept"]', '[class*="consent"]',
      '.cookie-accept', '.cookie-consent-accept',
      '#onetrust-accept-btn-handler',  // OneTrust
      '.cc-accept', '.cc-allow',  // Cookie Consent
      '[data-action="accept"]'
    ];

    let dismissed = false;

    // Try selectors first
    for (const selector of consentSelectors) {
      try {
        const buttons = document.querySelectorAll(selector);
        for (const btn of buttons) {
          if (btn.offsetParent && btn.tagName === 'BUTTON' || btn.getAttribute('role') === 'button') {
            btn.click();
            dismissed = true;
            break;
          }
        }
        if (dismissed) break;
      } catch (e) {
        // Ignore selector errors
      }
    }

    // Try text pattern matching on buttons
    if (!dismissed) {
      const allButtons = document.querySelectorAll('button, [role="button"], a[class*="button"]');
      for (const btn of allButtons) {
        if (!btn.offsetParent) continue;  // Skip hidden
        const text = btn.textContent.trim();
        for (const pattern of consentPatterns) {
          if (pattern.test(text) && text.length < 50) {
            btn.click();
            dismissed = true;
            break;
          }
        }
        if (dismissed) break;
      }
    }

    return { success: true, dismissed: dismissed };
  }

  /**
   * Wait for page to be stable (no ongoing network requests or DOM changes)
   */
  function waitForPageStable(timeoutMs = 3000) {
    return new Promise((resolve) => {
      let lastMutationTime = Date.now();
      let resolved = false;

      const observer = new MutationObserver(() => {
        lastMutationTime = Date.now();
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true
      });

      const checkStable = () => {
        if (resolved) return;

        const timeSinceLastMutation = Date.now() - lastMutationTime;
        if (timeSinceLastMutation > 500) {
          // Page has been stable for 500ms
          resolved = true;
          observer.disconnect();
          resolve({ success: true, stable: true });
        } else if (Date.now() - lastMutationTime > timeoutMs) {
          // Timeout reached
          resolved = true;
          observer.disconnect();
          resolve({ success: true, stable: false, timeout: true });
        } else {
          setTimeout(checkStable, 100);
        }
      };

      setTimeout(checkStable, 100);

      // Safety timeout
      setTimeout(() => {
        if (!resolved) {
          resolved = true;
          observer.disconnect();
          resolve({ success: true, stable: false, timeout: true });
        }
      }, timeoutMs);
    });
  }

  /**
   * Scroll the page naturally (like a human would)
   */
  function humanScroll(direction = 'down', amount = 300) {
    const scrollAmount = amount + Math.random() * 100 - 50;  // Add some randomness
    window.scrollBy({
      top: direction === 'down' ? scrollAmount : -scrollAmount,
      behavior: 'smooth'
    });
    return { success: true };
  }

  /**
   * Press a key (Escape, Enter, Tab, etc.)
   */
  function pressKey(key) {
    const keyMap = {
      'escape': { key: 'Escape', code: 'Escape', keyCode: 27 },
      'enter': { key: 'Enter', code: 'Enter', keyCode: 13 },
      'tab': { key: 'Tab', code: 'Tab', keyCode: 9 },
      'space': { key: ' ', code: 'Space', keyCode: 32 },
      'backspace': { key: 'Backspace', code: 'Backspace', keyCode: 8 },
      'arrowdown': { key: 'ArrowDown', code: 'ArrowDown', keyCode: 40 },
      'arrowup': { key: 'ArrowUp', code: 'ArrowUp', keyCode: 38 },
      'arrowleft': { key: 'ArrowLeft', code: 'ArrowLeft', keyCode: 37 },
      'arrowright': { key: 'ArrowRight', code: 'ArrowRight', keyCode: 39 }
    };

    const keyInfo = keyMap[key.toLowerCase()] || { key: key, code: key, keyCode: key.charCodeAt(0) };
    const target = document.activeElement || document.body;

    target.dispatchEvent(new KeyboardEvent('keydown', { ...keyInfo, bubbles: true }));
    target.dispatchEvent(new KeyboardEvent('keyup', { ...keyInfo, bubbles: true }));

    return { success: true, key: key };
  }

  /**
   * Click at a specific position on the page (useful for dismissing overlays)
   */
  function clickAtPosition(x, y) {
    const el = document.elementFromPoint(x, y);
    if (el) {
      simulateMouseEvents(el, x, y);
      return { success: true, element: el.tagName };
    }
    return { success: false, error: 'No element at position' };
  }

  // Expose functions globally for AppleScript access
  window.__ariaSnapshot = generateSnapshot;
  window.__ariaClick = clickByRef;
  window.__ariaType = typeByRef;
  window.__ariaSelect = selectByRef;
  window.__ariaGetText = getTextByRef;
  window.__ariaScrollTo = scrollToRef;
  window.__ariaGetElement = getElementByRef;
  window.__ariaDismissCookies = dismissCookieConsent;
  window.__ariaWaitStable = waitForPageStable;
  window.__ariaHumanScroll = humanScroll;
  window.__ariaPressKey = pressKey;
  window.__ariaClickAt = clickAtPosition;

  /**
   * Overlay ref labels on interactive elements for visual identification
   * Returns the snapshot data so LLM knows what refs are available
   */
  function showRefLabels(options = {}) {
    const { interactive_only = true, max_elements = 100 } = options;

    // First generate a snapshot to get refs
    const snapshot = generateSnapshot({ interactiveOnly: interactive_only, maxElements: max_elements });

    // Remove any existing overlays
    const existing = document.querySelectorAll('.__aria_ref_label');
    existing.forEach(el => el.remove());

    // Create overlay container
    let container = document.getElementById('__aria_overlay_container');
    if (!container) {
      container = document.createElement('div');
      container.id = '__aria_overlay_container';
      container.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 999999;';
      document.body.appendChild(container);
    }

    // Add labels for each ref
    let labelCount = 0;
    for (const [ref, info] of Object.entries(snapshot.refs)) {
      const el = elementRefs.get(ref);
      if (!el) continue;

      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.top < 0 || rect.left < 0) continue;
      if (rect.top > window.innerHeight || rect.left > window.innerWidth) continue;

      // Create label
      const label = document.createElement('div');
      label.className = '__aria_ref_label';
      label.textContent = ref;
      label.style.cssText = `
        position: fixed;
        top: ${rect.top}px;
        left: ${rect.left}px;
        background: #ff0000;
        color: white;
        font-size: 10px;
        font-family: monospace;
        font-weight: bold;
        padding: 1px 3px;
        border-radius: 3px;
        z-index: 1000000;
        pointer-events: none;
        box-shadow: 0 1px 2px rgba(0,0,0,0.5);
      `;

      container.appendChild(label);
      labelCount++;
    }

    return {
      success: true,
      labels_added: labelCount,
      snapshot: snapshot.snapshot,
      refs: snapshot.refs
    };
  }

  /**
   * Remove ref label overlays
   */
  function hideRefLabels() {
    const container = document.getElementById('__aria_overlay_container');
    if (container) {
      container.remove();
    }
    const existing = document.querySelectorAll('.__aria_ref_label');
    existing.forEach(el => el.remove());
    return { success: true };
  }

  window.__ariaShowLabels = showRefLabels;
  window.__ariaHideLabels = hideRefLabels;

  // Return the API for direct use
  return {
    snapshot: generateSnapshot,
    click: clickByRef,
    type: typeByRef,
    select: selectByRef,
    getText: getTextByRef,
    scrollTo: scrollToRef,
    getElement: getElementByRef
  };
})();
