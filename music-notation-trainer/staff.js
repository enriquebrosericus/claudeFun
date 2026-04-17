/**
 * staff.js
 * Renders a grand staff (treble + bass clef) with a single note using inline SVG.
 * No external libraries — hand-drawn SVG shapes only.
 *
 * ── Coordinate system (SVG user units) ────────────────────────────────────
 * viewBox: 0 0 680 210
 * LINE_GAP = 12px between adjacent staff lines
 * HALF_STEP = 6px per diatonic step (one "step" = one white-key interval)
 *
 * Treble staff lines (top → bottom): y = 40, 52, 64, 76, 88
 *   = staffPos 10(F5), 8(D5), 6(B4), 4(G4), 2(E4)
 *
 * Middle C (staffPos 0) → y = 100  (one space below treble bottom line)
 *
 * Bass staff lines (top → bottom): y = 112, 124, 136, 148, 160
 *   = staffPos -2(A3), -4(F3), -6(D3), -8(B2), -10(G2)
 *
 * Formula: y = MIDDLE_C_Y - staffPos * HALF_STEP
 *   = 100 - staffPos * 6
 *
 * ── Verified positions ─────────────────────────────────────────────────────
 * C3(-7)=142  D3(-6)=136✓  E3(-5)=130  F3(-4)=124✓  G3(-3)=118
 * A3(-2)=112✓ B3(-1)=106   C4(0)=100   D4(1)=94    E4(2)=88✓
 * F4(3)=82    G4(4)=76✓    A4(5)=70    B4(6)=64✓   C5(7)=58
 * D5(8)=52✓  E5(9)=46    F5(10)=40✓  G5(11)=34   A5(12)=28
 * B5(13)=22   C6(14)=16
 */

'use strict';

(function () {

  // ── Layout constants ───────────────────────────────────────────────────────
  const VB_W       = 680;
  const VB_H       = 210;
  const STAFF_LEFT  = 110;
  const STAFF_RIGHT = 640;
  const LINE_GAP    = 12;
  const HALF_STEP   = LINE_GAP / 2;   // 6

  const TREBLE_TOP  = 40;
  const BASS_TOP    = 112;
  const MIDDLE_C_Y  = 100;            // staffPos 0

  // Note head dimensions and horizontal position
  const NOTE_X  = 380;
  const NOTE_RX = 7.5;   // horizontal radius of ellipse
  const NOTE_RY = 5.2;   // vertical radius
  const STEM_LEN = 38;

  // ── y from staffPos ────────────────────────────────────────────────────────
  function posToY(staffPos) {
    return MIDDLE_C_Y - staffPos * HALF_STEP;
  }

  // ── Five staff lines ───────────────────────────────────────────────────────
  function staffLines(topY) {
    let s = '';
    for (let i = 0; i < 5; i++) {
      const y = topY + i * LINE_GAP;
      s += `<line x1="${STAFF_LEFT}" y1="${y}" x2="${STAFF_RIGHT}" y2="${y}"
                  stroke="#1a1a2e" stroke-width="1.4"/>`;
    }
    return s;
  }

  // ── Ledger lines ───────────────────────────────────────────────────────────
  // Treble staff covers staffPos 2–10 (E4–F5). Lines at even pos within that.
  // Bass staff covers staffPos -2 to -10. Our range is -7 to -1, all within bass staff.
  //
  // Ledger lines needed:
  //   staffPos 0 (middle C): one ledger line at y=100
  //   staffPos 12 (A5): one ledger at y=28
  //   staffPos 14 (C6): ledger at y=28 AND y=16
  //   Below treble but above bass (staffPos -1, 1): NO ledger; they float between staves
  //   C3 (staffPos -7): sits between D3(-6=bass line) and B2(-8=bass line) — no ledger needed
  function ledgerLines(staffPos) {
    const lines = [];
    const lx1 = NOTE_X - NOTE_RX - 5;
    const lx2 = NOTE_X + NOTE_RX + 5;

    if (staffPos === 0) {
      // Middle C ledger line
      lines.push(posToY(0));
    }

    // Above treble top (F5 = staffPos 10, y=40)
    // A5 = staffPos 12, C6 = staffPos 14
    if (staffPos >= 12) {
      for (let p = 12; p <= staffPos; p += 2) {
        lines.push(posToY(p));
      }
    }

    // Below bass bottom (G2 = staffPos -10, y=160) — not in our range so skipped

    return lines.map(y =>
      `<line x1="${lx1}" y1="${y}" x2="${lx2}" y2="${y}"
             stroke="#1a1a2e" stroke-width="1.6"/>`
    ).join('');
  }

  // ── Note head + stem ───────────────────────────────────────────────────────
  function noteShape(staffPos) {
    const y = posToY(staffPos);

    // Stem direction:
    //   Treble clef convention: stem down when note is on/above B4 (staffPos 6), up below.
    //   Bass clef convention: stem up when note is on/below D3 (staffPos -6), down above.
    //   Simple rule for grand staff: stem up when staffPos < 6, stem down otherwise.
    const stemUp = staffPos < 6;

    const stemX  = stemUp ? NOTE_X + NOTE_RX - 1.5 : NOTE_X - NOTE_RX + 1.5;
    const stemY1 = y + (stemUp ? -NOTE_RY + 1 : NOTE_RY - 1);
    const stemY2 = stemUp ? y - STEM_LEN : y + STEM_LEN;

    // Filled note head, rotated slightly (standard engraving style)
    return `
      <g class="note" role="presentation">
        <ellipse
          cx="${NOTE_X}" cy="${y}"
          rx="${NOTE_RX}" ry="${NOTE_RY}"
          fill="#1a1a2e"
          transform="rotate(-15,${NOTE_X},${y})"/>
        <line
          x1="${stemX}" y1="${stemY1}"
          x2="${stemX}" y2="${stemY2}"
          stroke="#1a1a2e" stroke-width="1.8" stroke-linecap="round"/>
      </g>`;
  }

  // ── Treble clef (G clef) ───────────────────────────────────────────────────
  // Rendered using Bravura music font (SMuFL U+E050).
  // The gClef glyph's origin in SMuFL is at the G line (staff line 2).
  function trebleClef() {
    const x = STAFF_LEFT + 4;
    // SMuFL gClef origin = G4 line (second line from bottom of treble staff)
    // G4 line = TREBLE_TOP + 3 * LINE_GAP = 76
    const y = TREBLE_TOP + 3 * LINE_GAP;
    // font-size scales to staff: 4 * LINE_GAP = 48px spans the staff height
    return `
      <text x="${x}" y="${y}"
            font-family="Bravura" font-size="32" fill="#1a1a2e"
            text-anchor="start">&#xE050;</text>`;
  }

  // ── Bass clef (F clef) ────────────────────────────────────────────────────
  // Rendered using Bravura music font (SMuFL U+E062).
  // The fClef glyph's origin in SMuFL is at the F line (staff line 4).
  function bassClef() {
    const x = STAFF_LEFT + 4;
    // SMuFL fClef origin = F3 line (second line from top of bass staff)
    // F3 line = BASS_TOP + LINE_GAP = 124
    const y = BASS_TOP + LINE_GAP;
    return `
      <text x="${x}" y="${y}"
            font-family="Bravura" font-size="32" fill="#1a1a2e"
            text-anchor="start">&#xE062;</text>`;
  }

  // ── Grand staff brace ──────────────────────────────────────────────────────
  function brace() {
    const top    = TREBLE_TOP;
    const bottom = BASS_TOP + 4 * LINE_GAP; // y=160
    const mid    = (top + bottom) / 2;
    const bx     = STAFF_LEFT;

    return `
      <!-- Vertical barline connecting both staves -->
      <line x1="${bx}" y1="${top}" x2="${bx}" y2="${bottom}"
            stroke="#1a1a2e" stroke-width="2"/>

      <!-- Brace: a pair of bezier curves forming a bracket -->
      <path d="
        M ${bx - 2} ${top}
        C ${bx - 24} ${top + 18},
          ${bx - 20} ${mid - 16},
          ${bx - 2}  ${mid}
        C ${bx - 20} ${mid + 16},
          ${bx - 24} ${bottom - 18},
          ${bx - 2}  ${bottom}
      "
      fill="none" stroke="#1a1a2e" stroke-width="7"
      stroke-linecap="round"/>`;
  }

  // ── Main render ────────────────────────────────────────────────────────────
  function renderStaff(note) {
    const { staffPos, name, octave } = note;

    const svg = `
<svg id="grand-staff"
     xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 ${VB_W} ${VB_H}"
     role="img"
     aria-label="Grand staff with the note ${name}${octave}">

  <!-- Grand staff brace + barline -->
  ${brace()}

  <!-- Treble staff (5 lines) -->
  ${staffLines(TREBLE_TOP)}

  <!-- Bass staff (5 lines) -->
  ${staffLines(BASS_TOP)}

  <!-- Treble clef -->
  ${trebleClef()}

  <!-- Bass clef -->
  ${bassClef()}

  <!-- Ledger lines (if needed) -->
  ${ledgerLines(staffPos)}

  <!-- The note -->
  ${noteShape(staffPos)}

</svg>`;

    return svg;
  }

  // Expose
  window.Staff = { renderStaff };

})();
