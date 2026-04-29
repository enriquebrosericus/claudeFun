/**
 * keyboard.js
 * Builds and manages the interactive piano keyboard (C2–C6, MIDI 36–84).
 *
 * Layout:
 *   36 white keys, 25 black keys over 5 octaves (C2–C6).
 *   All dimensions are expressed as percentages of total keyboard width
 *   so the layout is fully fluid and responsive.
 *
 * Matching is still by pitch class (note name), not exact MIDI, so clicking
 * any C is accepted whenever the answer is C. The full keyboard provides
 * visual context for where notes sit across octaves.
 *
 * Black key centering:
 *   Each black key has a "fractional white-key index" (blackFrac) representing
 *   where it sits between white keys. E.g., C# is 0.6 white keys from the left
 *   of its octave, meaning it's centered slightly right of C, left of D.
 *   The 0.6 offset (vs 0.5) gives the slightly asymmetric look of a real piano.
 */

'use strict';

(function () {

  // ── Constants ──────────────────────────────────────────────────────────────
  const MIDI_START  = 36;  // C2
  const MIDI_END    = 84;  // C6
  const TOTAL_WHITE = 29;  // 4 octaves × 7 + 1 (C6)

  // Per-semitone lookup tables (index 0–11 = C through B)
  const SEMITONE_NAMES     = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
  const SEMITONE_IS_BLACK  = [0,   1,   0,  1,   0,  0,  1,   0,  1,   0,  1,   0];
  // White-key index within the octave (C=0 … B=6); -1 for black keys
  const SEMITONE_WHITE_IDX = [0,  -1,   1, -1,   2,  3, -1,   4, -1,   5, -1,   6];
  // Black key fractional white-key position within octave; null for white keys
  const SEMITONE_BLACK_FRAC = [null, 0.6, null, 1.6, null, null, 3.6, null, 4.6, null, 5.6, null];

  // ── Build key list ─────────────────────────────────────────────────────────
  const ALL_KEYS = [];

  for (let midi = MIDI_START; midi <= MIDI_END; midi++) {
    const semitone  = (midi - MIDI_START) % 12;
    const octaveIdx = Math.floor((midi - MIDI_START) / 12); // 0–4 for C2–C6
    const octave    = octaveIdx + 2;
    const name      = SEMITONE_NAMES[semitone];
    const isBlack   = !!SEMITONE_IS_BLACK[semitone];

    if (!isBlack) {
      const whiteIndex = octaveIdx * 7 + SEMITONE_WHITE_IDX[semitone];
      ALL_KEYS.push({ midi, name, octave, isBlack: false, whiteIndex });
    } else {
      const blackFrac = octaveIdx * 7 + SEMITONE_BLACK_FRAC[semitone];
      ALL_KEYS.push({ midi, name, octave, isBlack: true, blackFrac });
    }
  }

  // ── Rendering ──────────────────────────────────────────────────────────────
  let _onKeyClick = null;

  /**
   * Build (or rebuild) the keyboard DOM inside `container`.
   * @param {HTMLElement} container
   * @param {function(number):void} clickCallback — receives midi note number
   */
  function buildKeyboard(container, clickCallback) {
    _onKeyClick = clickCallback;
    container.innerHTML = '';

    // Keyboard height: fill remaining viewport space, with min/max bounds
    const isMobile = window.innerWidth < 600;
    const keyHeight = isMobile ? 120 : 180;
    container.style.height = keyHeight + 'px';

    const whiteWidthPct = 100 / TOTAL_WHITE;          // % width per white key
    const blackWidthPct = whiteWidthPct * 0.60;       // slightly narrower
    const blackHeightPct = 62;                         // % of full key height

    // ── Render white keys first (z-index 1 via CSS) ──────────────────────
    ALL_KEYS.filter(k => !k.isBlack).forEach(key => {
      const el = createKeyEl('key-white', key);
      el.style.left   = (key.whiteIndex * whiteWidthPct) + '%';
      el.style.width  = whiteWidthPct + '%';
      el.style.top    = '0';
      el.style.bottom = '0';

      // Label C keys with octave number to mark octave boundaries
      if (key.name === 'C') {
        const label = document.createElement('span');
        label.className = 'key-label';
        label.textContent = 'C' + key.octave;
        label.setAttribute('aria-hidden', 'true');
        el.appendChild(label);
      }

      container.appendChild(el);
    });

    // ── Render black keys on top (z-index 2 via CSS) ─────────────────────
    ALL_KEYS.filter(k => k.isBlack).forEach(key => {
      const el = createKeyEl('key-black', key);

      // Center the black key: left edge = (blackFrac + 0.5) * whiteWidthPct - blackWidthPct/2
      const centerPct = (key.blackFrac + 0.5) * whiteWidthPct;
      el.style.left   = (centerPct - blackWidthPct / 2) + '%';
      el.style.width  = blackWidthPct + '%';
      el.style.top    = '0';
      el.style.height = blackHeightPct + '%';

      container.appendChild(el);
    });
  }

  /** Create a keyboard key element with shared event handlers */
  function createKeyEl(className, key) {
    const el = document.createElement('div');
    el.className = className;
    el.id = `key-${key.midi}`;
    el.dataset.midi = key.midi;
    el.style.position = 'absolute';
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', key.name + key.octave);
    el.setAttribute('tabindex', '0');

    el.addEventListener('click',   () => _onKeyClick(key.midi));
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        _onKeyClick(key.midi);
      }
    });
    el.addEventListener('touchend', e => {
      e.preventDefault();
      _onKeyClick(key.midi);
    });

    return el;
  }

  // ── Highlight helpers ──────────────────────────────────────────────────────

  /** Remove all correct/incorrect highlights from every key */
  function clearHighlights() {
    document.querySelectorAll('[id^="key-"].correct, [id^="key-"].incorrect').forEach(el => {
      el.classList.remove('correct', 'incorrect');
    });
  }

  /**
   * Add a highlight class to one key.
   * @param {number} midi
   * @param {'correct'|'incorrect'} state
   */
  function highlightKey(midi, state) {
    const el = document.getElementById(`key-${midi}`);
    if (el) el.classList.add(state);
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  // toKeyboardMidi: the keyboard now spans the full catalog (C2–C6) so every
  // catalog note maps directly to its own key.
  function toKeyboardMidi(midi) {
    return midi;
  }

  window.Keyboard = { buildKeyboard, clearHighlights, highlightKey, toKeyboardMidi, ALL_KEYS, MIDI_START, MIDI_END };

})();
