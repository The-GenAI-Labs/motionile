import { lotSourceLabels } from "@/features/credits/schemas/credits.schema";
import type { Wallet } from "@/features/credits/types/credits.types";
import { formatCredits, formatDate } from "@/lib/utils/format";

interface WalletSummaryProps {
  wallet: Wallet;
}

export function WalletSummary({ wallet }: WalletSummaryProps) {
  return (
    <section aria-labelledby="wallet-title" className="space-y-4 rounded-xl border bg-surface p-6">
      <h2 id="wallet-title" className="font-semibold">
        Your credits
      </h2>
      <dl className="grid gap-4 sm:grid-cols-3">
        <div>
          <dt className="text-sm text-muted-foreground">Available</dt>
          <dd className="font-mono text-3xl font-semibold">{formatCredits(wallet.available)}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Reserved</dt>
          <dd className="font-mono text-3xl font-semibold">{formatCredits(wallet.reserved)}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Total</dt>
          <dd className="font-mono text-3xl font-semibold">{formatCredits(wallet.balance)}</dd>
        </div>
      </dl>
      <p className="text-sm text-muted-foreground">
        Reserved credits are held for work in progress and returned if it is not completed.
      </p>
      <ExpiringCredits wallet={wallet} />
    </section>
  );
}

export function ExpiringCredits({ wallet }: WalletSummaryProps) {
  if (wallet.expiringSoon.length === 0) {
    return <p className="text-sm text-muted-foreground">No credits are expiring soon.</p>;
  }
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Expiring soon</h3>
      <ul className="space-y-1 text-sm text-subtle-foreground">
        {wallet.expiringSoon.map((lot) => (
          <li key={`${lot.source}-${lot.expiresAt}`}>
            <span className="font-mono">{formatCredits(lot.remaining)}</span> credits from{" "}
            {lotSourceLabels[lot.source].toLowerCase()} expire on {formatDate(lot.expiresAt)}
          </li>
        ))}
      </ul>
    </div>
  );
}
