export type UsageView = "entries" | "daily";

export const creditsKeys = {
  all: ["credits"] as const,
  wallet: () => [...creditsKeys.all, "wallet"] as const,
  ledger: () => [...creditsKeys.all, "ledger"] as const,
  usage: (view: UsageView) => [...creditsKeys.all, "usage", view] as const,
};
