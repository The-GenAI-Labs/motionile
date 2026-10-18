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
