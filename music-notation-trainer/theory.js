/**
 * theory.js
 * Music theory data for the notation trainer.
 * Covers C3–C6 (grand staff range), with correct ledger-line positioning.
 *
 * Staff position system:
 *   Each "step" = half a staff space.
 *   0 = first ledger line below treble staff (middle C / C4)
 *   Positive = higher, negative = lower.
 *
 * We track position relative to middle C so the SVG renderer
 * can place notes accurately across both clefs.
 */

'use strict';

/**
 * NOTE CATALOG
 * Each entry: { id, name, octave, clef, staffPos, midiNote }
 *
 * staffPos: integer steps above middle C (C4).
 *   C4 = 0, D4 = 1, E4 = 2, F4 = 3, G4 = 4, A4 = 5, B4 = 6,
 *   C5 = 7, ...
 *   B3 = -1, A3 = -2, G3 = -3, F3 = -4, E3 = -5, D3 = -6, C3 = -7
 *
 * clef: which clef the note naturally sits in.
 *   'treble' for C4 and above (up to C6),
 *   'bass'   for B3 and below (down to C3).
 *   Middle C (C4) goes on treble with ledger line below.
 */
const NOTE_CATALOG = [
  // ── Bass Clef notes (C3–B3) ──
  { id: 'C3', name: 'C', octave: 3, clef: 'bass',   staffPos: -7,  midiNote: 48 },
  { id: 'D3', name: 'D', octave: 3, clef: 'bass',   staffPos: -6,  midiNote: 50 },
  { id: 'E3', name: 'E', octave: 3, clef: 'bass',   staffPos: -5,  midiNote: 52 },
  { id: 'F3', name: 'F', octave: 3, clef: 'bass',   staffPos: -4,  midiNote: 53 },
  { id: 'G3', name: 'G', octave: 3, clef: 'bass',   staffPos: -3,  midiNote: 55 },
  { id: 'A3', name: 'A', octave: 3, clef: 'bass',   staffPos: -2,  midiNote: 57 },
  { id: 'B3', name: 'B', octave: 3, clef: 'bass',   staffPos: -1,  midiNote: 59 },

  // ── Middle C ──
  { id: 'C4', name: 'C', octave: 4, clef: 'treble', staffPos:  0,  midiNote: 60 },

  // ── Treble Clef notes (D4–C6) ──
  { id: 'D4', name: 'D', octave: 4, clef: 'treble', staffPos:  1,  midiNote: 62 },
  { id: 'E4', name: 'E', octave: 4, clef: 'treble', staffPos:  2,  midiNote: 64 },
  { id: 'F4', name: 'F', octave: 4, clef: 'treble', staffPos:  3,  midiNote: 65 },
  { id: 'G4', name: 'G', octave: 4, clef: 'treble', staffPos:  4,  midiNote: 67 },
  { id: 'A4', name: 'A', octave: 4, clef: 'treble', staffPos:  5,  midiNote: 69 },
  { id: 'B4', name: 'B', octave: 4, clef: 'treble', staffPos:  6,  midiNote: 71 },
  { id: 'C5', name: 'C', octave: 5, clef: 'treble', staffPos:  7,  midiNote: 72 },
  { id: 'D5', name: 'D', octave: 5, clef: 'treble', staffPos:  8,  midiNote: 74 },
  { id: 'E5', name: 'E', octave: 5, clef: 'treble', staffPos:  9,  midiNote: 76 },
  { id: 'F5', name: 'F', octave: 5, clef: 'treble', staffPos: 10,  midiNote: 77 },
  { id: 'G5', name: 'G', octave: 5, clef: 'treble', staffPos: 11,  midiNote: 79 },
  { id: 'A5', name: 'A', octave: 5, clef: 'treble', staffPos: 12,  midiNote: 81 },
  { id: 'B5', name: 'B', octave: 5, clef: 'treble', staffPos: 13,  midiNote: 83 },
  { id: 'C6', name: 'C', octave: 6, clef: 'treble', staffPos: 14,  midiNote: 84 },
];

/** Ranges the user can select in settings */
const NOTE_RANGES = {
  full:   NOTE_CATALOG,                                              // C3–C6
  treble: NOTE_CATALOG.filter(n => n.staffPos >= 0),               // C4–C6
  bass:   NOTE_CATALOG.filter(n => n.staffPos <= 0),               // C3–C4 (middle C included)
};

/**
 * Pick a random note from the given range, optionally excluding the last note
 * (to avoid immediate repeats).
 */
function randomNote(range = 'full', excludeId = null) {
  const pool = NOTE_RANGES[range].filter(n => n.id !== excludeId);
  return pool[Math.floor(Math.random() * pool.length)];
}

/**
 * Map from note id → piano key id (used to highlight the correct key).
 * Piano key ids are built in keyboard.js as `key-{midiNote}`.
 */
function pianoKeyId(note) {
  return `key-${note.midiNote}`;
}

// Expose to other modules (plain globals, no module system needed)
window.Theory = { NOTE_CATALOG, NOTE_RANGES, randomNote, pianoKeyId };
