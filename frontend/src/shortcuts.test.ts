import { test } from "node:test";
import assert from "node:assert/strict";
import { shortcutForKey } from "./shortcuts.ts";

const key = (value: string, extra = {}) => ({
  key: value,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  ...extra,
});
test("single-key shortcuts can be disabled while F1 stays available", () => {
  for (const character of ["a", "r", "d", "/", "j", "k", "s", "o", "?", "T"])
    assert.equal(shortcutForKey(key(character), false), null);
  assert.equal(shortcutForKey(key("F1"), false), "help");
});
test("theme shortcut does not conflict with chronology or browser modifiers", () => {
  assert.equal(shortcutForKey(key("T"), true), "theme");
  assert.equal(shortcutForKey(key("t"), true), "timeline");
  assert.equal(shortcutForKey(key("T", { ctrlKey: true }), true), null);
});
test("browser and assistive modifier combinations are not intercepted", () => {
  assert.equal(shortcutForKey(key("r", { ctrlKey: true }), true), null);
  assert.equal(shortcutForKey(key("k", { metaKey: true }), true), null);
  assert.equal(shortcutForKey(key("a", { altKey: true }), true), null);
});
