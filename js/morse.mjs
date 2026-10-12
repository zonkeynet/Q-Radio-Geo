// International Morse code for beacon identifiers (VOR, NDB…), as heard on the receiver.
const CODE = {
    A: '.-', B: '-...', C: '-.-.', D: '-..', E: '.', F: '..-.', G: '--.', H: '....', I: '..', J: '.---', K: '-.-', L: '.-..', M: '--',
    N: '-.', O: '---', P: '.--.', Q: '--.-', R: '.-.', S: '...', T: '-', U: '..-', V: '...-', W: '.--', X: '-..-', Y: '-.--', Z: '--..',
    0: '-----', 1: '.----', 2: '..---', 3: '...--', 4: '....-', 5: '.....', 6: '-....', 7: '--...', 8: '---..', 9: '----.'
};
export const morse = ident => {
    const letters = [...String(ident || '').toUpperCase()].map(c => CODE[c]);
    return letters.length && letters.every(Boolean) ? letters.join('  ').replace(/\./g, '·').replace(/-/g, '−') : null;
};
