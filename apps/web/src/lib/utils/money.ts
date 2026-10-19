const PAISE_PER_RUPEE = 100;

const RUPEE_INPUT = /^(\d{1,12})(?:\.(\d{1,2}))?$/;

export const RUPEE_INPUT_MESSAGE = "Enter an amount in rupees with at most two decimals.";

export const parseRupeesToPaise = (input: string): number | null => {
  const match = RUPEE_INPUT.exec(input.trim());
  const rupees = match?.[1];
  if (rupees === undefined) {
    return null;
  }
  const fraction = (match?.[2] ?? "").padEnd(2, "0");
  const paise = Number(rupees) * PAISE_PER_RUPEE + Number(fraction);
  return Number.isSafeInteger(paise) ? paise : null;
};

export const rupeesToPaise = (input: string): number => {
  const paise = parseRupeesToPaise(input);
  if (paise === null) {
    throw new RangeError(RUPEE_INPUT_MESSAGE);
  }
  return paise;
};
