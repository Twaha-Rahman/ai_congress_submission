import { test } from "node:test";
import assert from "node:assert/strict";
import { addDays, monthDays, pickerValue, shiftMonth, timeValid, todayKey, validDate } from "./datePicker.ts";

test("calendar navigation handles leap days, month lengths and supported year boundaries", () => {
  assert.equal(addDays("2024-02-28", 1), "2024-02-29");
  assert.equal(addDays("2026-02-28", 1), "2026-03-01");
  assert.equal(shiftMonth("2024-01-31", 1), "2024-02-29");
  assert.equal(shiftMonth("2024-02-29", 12), "2025-02-28");
  assert.equal(shiftMonth("2026-12-31", 1), "2027-01-31");
  assert.equal(addDays("0001-01-01", -1), "0001-01-01");
  assert.equal(addDays("9999-12-31", 1), "9999-12-31");
  assert.equal(shiftMonth("0001-01-31", -1), "0001-01-31");
  assert.equal(shiftMonth("9999-12-31", 1), "9999-12-31");
});

test("calendar rows start on Monday, preserve adjacent dates and do not invent unsupported years", () => {
  const february = monthDays("2025-02-21");
  assert.equal(february.length, 42);
  assert.equal(february[0], "2025-01-27");
  assert.equal(february[41], "2025-03-09");
  assert.equal(new Set(february).size, 42);
  assert.ok(monthDays("9999-12-01").every(value => !value || validDate(value)));
  assert.equal(todayKey(new Date("2026-10-21T23:59:00Z")), "2026-10-21");
});

test("picker values retain exact UTC-cutoff precision and reject impossible dates/times", () => {
  assert.equal(pickerValue("2026-10-21", "12:34:56.789", true), "2026-10-21T12:34:56.789");
  assert.equal(pickerValue("2026-10-21", "", false), "2026-10-21");
  assert.equal(pickerValue("2026-02-29", "10:00", true), "");
  for (const invalid of ["2026-02-30", "2026-13-01", "0000-01-01", "2026-1-1"])
    assert.equal(validDate(invalid), false);
  for (const invalid of ["24:00", "12:60", "9:00", "12:30:60", "12:30:20.1234", ""])
    assert.equal(timeValid(invalid), false);
});
