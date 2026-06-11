/**
 * TS ↔ РНП recon harness (TASK-DEV-075) — повторяемая ЖИВАЯ сверка.
 *
 * Принцип (memory `ts-live-verification`): сверять ТОЛЬКО против живого TS API,
 * НЕ против чисел из прошлых summary. Два источника независимы → не круговая
 * проверка. CORS: TS и наш прод — разные origin, поэтому два шага в разных вкладках
 * (через Claude-in-Chrome / DevTools-консоль).
 *
 * Кабинет Onyx = TS account 25143 = наш tenant 1 (financial-режим = rr_dt).
 *
 * ─── ШАГ 1: на вкладке mirror-app.truestats.ru (залогинен) ───────────────────
 *   Вставить tsStats('2026-05-18','2026-05-24') → вернёт TS-метрики.
 *
 * ─── ШАГ 2: на вкладке rnp.sellerfriends.ru (залогинен director/head) ────────
 *   Вставить rnpStats('2026-05-18','2026-05-24') → вернёт наши (financial).
 *
 * ─── ШАГ 3: diff(ts, ours) — список расхождений с Δ. ──────────────────────────
 */

// === ШАГ 1 (вставить на странице TS) ===
async function tsStats(dateFrom, dateTo) {
  const tok = localStorage.getItem('authToken'); // 120-hex, НЕ 'token'
  const r = await fetch('https://api2.truestats.ru/reporting/main/stats', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-auth-token': tok },
    body: JSON.stringify({ dateFrom, dateTo, filters: { accounts: [25143] } }),
  });
  const j = await r.json();
  const s = j.stats || {};
  // нормализуем в общие ключи для diff
  return {
    realisation: s.realisation, sales: s.sales, toTransfer: s.toTransfer,
    logistics: s.logistics, storage: s.storage, acquiring: s.acquiring,
    commission: s.commission, nominalCommission: s.nominalCommission,
    spp: s.wbCompensationAmount, returns: s.returns, cogs: s.costOfSales,
    otherDeduction: s.otherDeduction, fines: s.fines, tax: s.tax,
    ad: s.advertisingExpense, profit: s.profit, totalPaid: s.totalPaid,
    salesCount: s.salesCount, ordersCount: s.ordersCount, ordersSum: s.orders,
    capByCost: s.capitalizationByCost,
  };
}

// === ШАГ 2 (вставить на странице РНП) ===
async function rnpStats(dateFrom, dateTo) {
  const j = async (u) => (await fetch(u, { credentials: 'include' })).json();
  const sr = (await j(`/api/summary-report?start_date=${dateFrom}&end_date=${dateTo}&reporting_mode=financial`)).totals;
  return {
    realisation: sr.realisation, sales: sr.sales, toTransfer: sr.to_transfer,
    logistics: sr.logistics, storage: sr.storage, acquiring: sr.acquiring,
    commission: sr.commission, nominalCommission: null /* см. /pnl commission */,
    spp: (sr.realisation - sr.sales), returns: sr.returns_rub, cogs: sr.cogs,
    otherDeduction: sr.deductions, fines: sr.fines, tax: sr.tax,
    ad: sr.ad, profit: sr.profit, totalPaid: null, salesCount: sr.sold,
    ordersCount: sr.orders_count, ordersSum: sr.orders_sum, capByCost: sr.cap_by_cost,
  };
}

// === ШАГ 3 (где угодно) ===
function diff(ts, ours, tol = 0.05) {
  const rows = [];
  for (const k of Object.keys(ts)) {
    const a = ts[k], b = ours[k];
    if (a == null || b == null) { rows.push([k, a, b, '— (нет в одном источнике)']); continue; }
    const d = +(b - a).toFixed(2);
    rows.push([k, a, b, Math.abs(d) <= tol ? '✅ 0' : (d > 0 ? `Δ +${d}` : `Δ ${d}`)]);
  }
  console.table(rows.map(([metric, ts, ours, delta]) => ({ metric, ts, ours, delta })));
  return rows;
}

// Пример полного прогона (через Claude-in-Chrome, две вкладки):
//   const ts   = await tsStats('2026-05-18','2026-05-24');   // на вкладке TS
//   const ours = await rnpStats('2026-05-18','2026-05-24');  // на вкладке РНП
//   diff(ts, ours);
//
// Прецедент 18-24.05.2026: база (realisation/sales/toTransfer/logistics/acquiring/
// commission/nominalCommission/spp/cogs/otherDeduction/salesCount) = ✅ 0.
// Расхождения: ad (Onyx-синк стоит, TASK-DEV-069), tax 0.26% (осознанно),
// orders (рассрочка, by-design), capByCost (снапшот).
