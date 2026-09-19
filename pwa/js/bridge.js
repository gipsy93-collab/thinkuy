/* Thinkuy — puente explícito entre módulos de la PWA.
 *
 * `app.js` publica aquí las funciones que otros módulos (radar, review, journal)
 * necesitan, en lugar de exponerlas en `window` o de crear importaciones circulares.
 * Es una dependencia declarada y en un solo lugar: si algo falta, se ve aquí.
 */
"use strict";

export const bridge = {};
