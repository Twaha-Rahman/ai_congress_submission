import { test } from "node:test";
import assert from "node:assert/strict";
import { amountRange, money } from "./presentation.ts";

test("money uses cents without dropping boundary precision", () => {
  assert.equal(money(2500000), "$25,000");
  assert.equal(money(2500001), "$25,000.01");
});
test("scope descriptions preserve open and closed amount boundaries", () => {
  assert.equal(
    amountRange({
      lower: 2500000,
      lower_inclusive: false,
      upper: 5000000,
      upper_inclusive: true,
    }),
    "Above $25,000 and up to $50,000",
  );
  assert.equal(
    amountRange({
      lower: 0,
      lower_inclusive: true,
      upper: 2500000,
      upper_inclusive: false,
    }),
    "From $0 to below $25,000",
  );
  assert.equal(
    amountRange({
      lower: 0,
      lower_inclusive: false,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "Above $0 and up to $25,000",
  );
  assert.equal(
    amountRange({
      lower: 0,
      lower_inclusive: true,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "From $0 up to $25,000",
  );
  assert.equal(
    amountRange({
      lower: null,
      lower_inclusive: false,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "up to $25,000",
  );
  assert.equal(
    amountRange({
      lower: 2500000,
      lower_inclusive: true,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "Exactly $25,000",
  );
});
