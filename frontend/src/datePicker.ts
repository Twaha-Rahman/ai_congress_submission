export function dateKey(date: Date) {
  const year = date.getUTCFullYear();
  return year >= 1 && year <= 9999 ? date.toISOString().slice(0, 10) : "";
}
export function validDate(value: string) {
  if (!/^\d{4}-\d\d-\d\d$/.test(value) || Number(value.slice(0, 4)) < 1) return false;
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(date.getTime()) && dateKey(date) === value;
}
export function todayKey(now = new Date()) {
  return dateKey(now);
}
export function addDays(value: string, count: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + count);
  return dateKey(date) || (count < 0 ? "0001-01-01" : "9999-12-31");
}
export function shiftMonth(value: string, count: number) {
  const [year, month, day] = value.split("-").map(Number);
  const index = Math.max(12, Math.min(9999 * 12 + 11, year * 12 + month - 1 + count));
  const start = `${String(Math.floor(index / 12)).padStart(4, "0")}-${String(index % 12 + 1).padStart(2, "0")}-01`;
  const date = new Date(`${start}T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + 1, 0);
  return `${start.slice(0, 8)}${String(Math.min(day, date.getUTCDate())).padStart(2, "0")}`;
}
export function monthDays(value: string) {
  const first = `${value.slice(0, 7)}-01`;
  const weekday = (new Date(`${first}T12:00:00Z`).getUTCDay() + 6) % 7;
  // Keep six stable rows; dates outside the supported year range are blank.
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(`${first}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + index - weekday);
    return dateKey(date);
  });
}
export function timeValid(value: string) {
  return /^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,3})?)?$/.test(value);
}
export function pickerValue(day: string, time: string, timed: boolean) {
  return validDate(day) && (!timed || timeValid(time)) ? `${day}${timed ? `T${time}` : ""}` : "";
}
export function timeMinutes(value: string) {
  return Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5));
}
export const timeSlots = Array.from({ length: 48 }, (_, index) => `${String(Math.floor(index / 2)).padStart(2, "0")}:${index % 2 ? "30" : "00"}`);
export function calendarLabel(day: string, options: Intl.DateTimeFormatOptions = { dateStyle: "long" }) {
  return new Intl.DateTimeFormat("en-GB", { ...options, timeZone: "UTC" }).format(new Date(`${day}T12:00:00Z`));
}
