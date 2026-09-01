import "@testing-library/jest-dom/vitest";

Object.defineProperties(HTMLMediaElement.prototype, {
  load: { configurable: true, value: () => undefined },
  pause: { configurable: true, value: () => undefined },
  play: { configurable: true, value: () => Promise.resolve() },
});
