const PAISE_PER_RUPEE = 100;

const wholeRupeeFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const fractionalRupeeFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
});

const creditsFormat = new Intl.NumberFormat("en-IN");

const dateFormat = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" });

const dateTimeFormat = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
});

const assertPaise = (paise: number): void => {
  if (!Number.isSafeInteger(paise) || paise < 0) {
    throw new RangeError("Money must be a non-negative integer number of paise.");
  }
};

export const formatPaise = (paise: number): string => {
  assertPaise(paise);
  const format = paise % PAISE_PER_RUPEE === 0 ? wholeRupeeFormat : fractionalRupeeFormat;
  return format.format(paise / PAISE_PER_RUPEE);
};

export const formatSignedPaise = (paise: number): string =>
  paise < 0 ? `-${formatPaise(-paise)}` : formatPaise(paise);

export const paiseToDecimalString = (paise: number): string => {
  assertPaise(paise);
  const rupees = Math.floor(paise / PAISE_PER_RUPEE);
  const remainder = paise % PAISE_PER_RUPEE;
  return `${String(rupees)}.${String(remainder).padStart(2, "0")}`;
};

export const formatCredits = (credits: number): string => creditsFormat.format(credits);

export const formatSignedCredits = (credits: number): string =>
  credits > 0 ? `+${formatCredits(credits)}` : formatCredits(credits);

export const formatDate = (iso: string): string => dateFormat.format(new Date(iso));

export const formatDateTime = (iso: string): string => dateTimeFormat.format(new Date(iso));

export const titleCase = (value: string): string =>
  value
    .split(/[\s_-]+/)
    .filter((word) => word !== "")
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");

const SECONDS_PER_MINUTE = 60;
const MS_PER_SECOND = 1_000;

export const formatDurationMs = (milliseconds: number): string => {
  const totalSeconds = Math.max(0, Math.round(milliseconds / MS_PER_SECOND));
  const minutes = Math.floor(totalSeconds / SECONDS_PER_MINUTE);
  const seconds = totalSeconds % SECONDS_PER_MINUTE;
  return `${String(minutes)}:${String(seconds).padStart(2, "0")}`;
};

const MS_PER_MINUTE = 60_000;

export const formatClockMs = (milliseconds: number): string => {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / MS_PER_SECOND));
  const minutes = Math.floor(totalSeconds / SECONDS_PER_MINUTE);
  const seconds = totalSeconds % SECONDS_PER_MINUTE;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
};

export const formatTimestampMs = (milliseconds: number): string => {
  const total = Math.max(0, Math.round(milliseconds));
  const minutes = Math.floor(total / MS_PER_MINUTE);
  const seconds = Math.floor((total % MS_PER_MINUTE) / MS_PER_SECOND);
  const rest = total % MS_PER_SECOND;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(rest).padStart(3, "0")}`;
};
