/**
 * Единые threshold'ы сверки P&L с WB (BUG-DEV-017, round-14).
 *
 * Раньше `ReconciliationHeroWidget` и `StateOfBusinessCard` имели разные
 * границы «норма» для payout_to_gross_pct (95-100 vs 95-105). У собственника
 * с положительной разовой компенсацией от WB payout может быть >100%.
 * Унифицируем на 95-105 — capture положительную WB-компенсацию.
 */

export const PAYOUT_SHARE_NORM_MIN = 95;
export const PAYOUT_SHARE_NORM_MAX = 105;
export const PAYOUT_SHARE_DANGER_BELOW = 85;

export function payoutShareClass(payoutShare: number | null | undefined): string {
  if (payoutShare == null) return "text-muted";
  if (payoutShare >= PAYOUT_SHARE_NORM_MIN && payoutShare <= PAYOUT_SHARE_NORM_MAX) {
    return "text-success";
  }
  if (payoutShare < PAYOUT_SHARE_DANGER_BELOW) return "text-danger";
  return "text-warn";
}
