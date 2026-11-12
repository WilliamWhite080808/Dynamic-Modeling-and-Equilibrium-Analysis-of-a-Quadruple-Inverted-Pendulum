export function simulationRate(value,fallback=1){const n=Number(value);return Number.isFinite(n)?Math.max(.1,Math.min(10,n)):fallback;}
export function timelineEnd(reference){const settled=reference?.verification?.settled_at;return Math.max(.5,(Number.isFinite(settled)?settled:reference?.duration||0)+.5);}
export const STABLE_HOLD_SECONDS=10;
