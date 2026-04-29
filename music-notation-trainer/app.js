/**
 * app.js
 * Main application controller for the Music Notation Trainer.
 *
 * Wires together Theory, Staff, Keyboard modules and manages:
 *  - Game state (current note, score, streak)
 *  - User interaction (key clicks, reset, settings)
 *  - Feedback display
 *  - Audio feedback via Web Audio API
 *  - Settings persistence via localStorage
 */

'use strict';

(function () {

  // ── State ──────────────────────────────────────────────────────────────────
  let currentNote  = null;
  let answered     = false;   // prevent double-answering per note
  let score        = 0;
  let streak       = 0;
  let lastNoteId   = null;

  // Settings (loaded from localStorage)
  let settings = {
    range:     'full',
    showHint:  false,
    sound:     true,
  };

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const staffContainer = document.getElementById('staff-container');
  const feedbackBox    = document.getElementById('feedback-box');
  const feedbackText   = document.getElementById('feedback-text');
  const scoreEl        = document.getElementById('score-value');
  const streakEl       = document.getElementById('streak-value');
  const hintText       = document.getElementById('hint-text');
  const resetBtn       = document.getElementById('reset-btn');
  const settingsBtn    = document.getElementById('settings-btn');
  const settingsModal  = document.getElementById('settings-modal');
  const closeSettings  = document.getElementById('close-settings');
  const rangeSelect    = document.getElementById('range-select');
  const hintToggle     = document.getElementById('hint-toggle');
  const soundToggle    = document.getElementById('sound-toggle');
  const keyboard       = document.getElementById('keyboard');

  // ── Audio ──────────────────────────────────────────────────────────────────
  let audioCtx = null;

  function getAudioCtx() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return audioCtx;
  }

  /**
   * Play a simple sine-wave tone at the given MIDI note frequency.
   * @param {number} midiNote
   * @param {boolean} success - true = clean tone, false = buzz tone
   */
  function playTone(midiNote, success) {
    if (!settings.sound) return;
    try {
      const ctx = getAudioCtx();
      const freq = 440 * Math.pow(2, (midiNote - 69) / 12);

      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);

      if (success) {
        // Pleasant: sine wave, short attack, gentle release
        osc.type = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0, ctx.currentTime);
        gain.gain.linearRampToValueAtTime(0.35, ctx.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.7);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.75);
      } else {
        // Dissonant buzz: sawtooth + minor second above
        osc.type = 'sawtooth';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.2, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.4);
      }
    } catch (e) {
      // Audio not available — silent fallback
    }
  }

  // ── Settings persistence ───────────────────────────────────────────────────
  function loadSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem('noteTrainerSettings') || '{}');
      settings = { ...settings, ...saved };
    } catch (_) {}
    applySettingsToUI();
  }

  function saveSettings() {
    localStorage.setItem('noteTrainerSettings', JSON.stringify(settings));
  }

  function applySettingsToUI() {
    rangeSelect.value      = settings.range;
    hintToggle.checked     = settings.showHint;
    soundToggle.checked    = settings.sound;
  }

  // ── Score display ──────────────────────────────────────────────────────────
  function updateScoreDisplay() {
    scoreEl.textContent  = score;
    streakEl.textContent = streak;
  }

  // ── Feedback display ───────────────────────────────────────────────────────
  /**
   * @param {'neutral'|'correct'|'incorrect'} state
   * @param {string} message
   */
  function setFeedback(state, message) {
    feedbackBox.className = 'feedback-box ' + state;
    feedbackText.textContent = message;
  }

  // ── New note ───────────────────────────────────────────────────────────────
  function newNote() {
    answered   = false;
    currentNote = Theory.randomNote(settings.range, lastNoteId);
    lastNoteId  = currentNote.id;

    // Render staff
    staffContainer.innerHTML = Staff.renderStaff(currentNote);

    // Pop animation
    const svgEl = staffContainer.querySelector('svg');
    if (svgEl) {
      svgEl.classList.remove('staff-pop');
      // Force reflow to restart animation
      void svgEl.offsetWidth;
      svgEl.classList.add('staff-pop');
    }

    // Clear piano highlights
    Keyboard.clearHighlights();

    // Reset feedback
    setFeedback('neutral', 'Click a piano key to answer');

    // Hint
    if (settings.showHint) {
      hintText.textContent = currentNote.name + currentNote.octave;
      hintText.classList.remove('hidden');
    } else {
      hintText.classList.add('hidden');
    }
  }

  // ── Find the staff position of the wrong note ──────────────────────────────
  // Picks the catalog entry with the same note name and same clef as the correct
  // note, choosing the one closest in staffPos when multiple octaves exist.
  function findWrongNoteForStaff(clickedKey, correctNote) {
    if (!clickedKey) return null;
    const candidates = Theory.NOTE_CATALOG.filter(
      n => n.name === clickedKey.name && n.clef === correctNote.clef
    );
    if (candidates.length === 0) return null;
    return candidates.reduce((best, n) =>
      Math.abs(n.staffPos - correctNote.staffPos) < Math.abs(best.staffPos - correctNote.staffPos)
        ? n : best
    );
  }

  // ── Handle piano key click ─────────────────────────────────────────────────
  function handleKeyClick(clickedMidi) {
    if (answered || !currentNote) return;
    answered = true;

    const correctMidi        = currentNote.midiNote;
    // Match by pitch class so any octave of the correct note is accepted
    const isCorrect          = (clickedMidi % 12) === (correctMidi % 12);
    // MIDI of the correct note's key on the single-octave keyboard
    const keyboardCorrectMidi = Keyboard.toKeyboardMidi(correctMidi);

    if (isCorrect) {
      score++;
      streak++;
      setFeedback('correct', `Correct! That's ${currentNote.name}${currentNote.octave}.`);
      Keyboard.highlightKey(clickedMidi, 'correct');
      playTone(correctMidi, true);
    } else {
      streak = 0;
      const clickedKey  = Keyboard.ALL_KEYS.find(k => k.midi === clickedMidi);
      const clickedName = clickedKey ? clickedKey.name : '?';
      setFeedback(
        'incorrect',
        `Not quite. That was ${clickedName} — the note was ${currentNote.name}${currentNote.octave}.`
      );
      Keyboard.highlightKey(clickedMidi,        'incorrect');
      Keyboard.highlightKey(keyboardCorrectMidi, 'correct');
      playTone(clickedMidi, false);

      // Show where the wrong note falls on the staff (green)
      const wrongNoteForStaff = findWrongNoteForStaff(clickedKey, currentNote);
      staffContainer.innerHTML = Staff.renderStaff(currentNote, wrongNoteForStaff);
    }

    updateScoreDisplay();

    // Auto-advance after a short delay
    setTimeout(() => {
      newNote();
    }, isCorrect ? 1200 : 2200);
  }

  // ── Settings modal ─────────────────────────────────────────────────────────
  function openSettings() {
    settingsModal.classList.remove('hidden');
  }

  function closeSettingsModal() {
    settingsModal.classList.add('hidden');
    // Read values
    settings.range    = rangeSelect.value;
    settings.showHint = hintToggle.checked;
    settings.sound    = soundToggle.checked;
    saveSettings();
    // Refresh note in case range changed
    newNote();
  }

  settingsBtn.addEventListener('click', openSettings);
  closeSettings.addEventListener('click', closeSettingsModal);
  settingsModal.addEventListener('click', e => {
    // Click outside modal box
    if (e.target === settingsModal) closeSettingsModal();
  });

  // ── Reset button ───────────────────────────────────────────────────────────
  resetBtn.addEventListener('click', newNote);

  // ── Keyboard shortcuts ─────────────────────────────────────────────────────
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !settingsModal.classList.contains('hidden')) return;
    if (e.key === 'r' || e.key === 'R') newNote();
    if (e.key === 'Escape') {
      if (!settingsModal.classList.contains('hidden')) closeSettingsModal();
    }
  });

  // ── Show Notes (hold to reveal reference staff overlay) ─────────────────────
  const showNotesBtn = document.getElementById('show-notes-btn');
  const refOverlay = document.getElementById('reference-overlay');
  const refContainer = document.getElementById('reference-staff');

  let refVisible = false;

  function showReferenceStaff() {
    if (refVisible) return;
    refVisible = true;
    refContainer.innerHTML = Staff.renderReferenceStaff();
    refOverlay.classList.remove('hidden');
    showNotesBtn.classList.add('active');
  }

  function hideReferenceStaff() {
    if (!refVisible) return;
    refVisible = false;
    refOverlay.classList.add('hidden');
    showNotesBtn.classList.remove('active');
  }

  // Show on press
  showNotesBtn.addEventListener('mousedown', showReferenceStaff);
  showNotesBtn.addEventListener('touchstart', e => { e.preventDefault(); showReferenceStaff(); });

  // Hide on ANY mouseup/touchend (document-level so it works even if overlay covers the button)
  document.addEventListener('mouseup', hideReferenceStaff);
  document.addEventListener('touchend', hideReferenceStaff);
  document.addEventListener('touchcancel', hideReferenceStaff);

  // ── Keyboard resize handling ───────────────────────────────────────────────
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      Keyboard.buildKeyboard(keyboard, handleKeyClick);
    }, 150);
  });

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    loadSettings();
    updateScoreDisplay();
    Keyboard.buildKeyboard(keyboard, handleKeyClick);
    newNote();
  }

  // Wait for DOM to be fully ready (scripts are at end of body, so this fires immediately)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
