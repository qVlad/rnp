/**
 * TASK-LEAD-042 — Hero-line «Прибыль за прошлую закрытую неделю».
 *
 * Один большой KPI наверху Dashboard'а: net_profit за последнюю закрытую
 * неделю (пн-вс) в final mode + WoW сравнение. Закрывает daily-сценарий
 * собственника «сколько заработал?» одним взглядом.
 *
 * «Закрытая неделя» = today - 14 дней, округлённое назад к ближайшему
 * воскресенью (грубое приближение для WB final-отчётов, лаг ~14 дней).
 * Если final-данных нет (новый кабинет) — показываем no-data state.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";

type Week = { from: string; to: string };

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function lastClosedWeek(today: Date = new Date()): Week {
  // Сдвигаем на 14 дней назад для уверенности что final-данные есть
  const cutoff = new Date(today);
  cutoff.setDate(cutoff.getDate() - 14);
  // Откатываем к ближайшему воскресенью в прошлом (включая сегодня если вс)
  const dow = cutoff.getDay(); // 0=вс, 1=пн, ... 6=сб
  // Если сегодня вс (dow=0) — это уже воскресенье. Иначе откатываем dow дней.
  cutoff.setDate(cutoff.getDate() - dow);
  const sun = new Date(cutoff);
  const mon = new Date(sun);
  mon.setDate(mon.getDate() - 6);
  return { from: isoDate(mon), to: isoDate(sun) };
}

function previousWeek(week: Week): Week {
  const mon = new Date(week.from);
  mon.setDate(mon.getDate() - 7);
  const sun = new Date(week.to);
  sun.setDate(sun.getDate() - 7);
  return { from: isoDate(mon), to: isoDate(sun) };
}

function getKpi(kpis: any[], key: string): number | null {
  if (!Array.isArray(kpis)) return null;
  const k = kpis.find((x) => x.key === key);
  if (!k) return null;
  const v = typeof k.value === "number" ? k.value : Number(k.value);
  return Number.isFinite(v) ? v : null;
}

function fmtPeriod(w: Week): string {
  // 2026-05-12 → 12 мая
  const months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const a = new Date(w.from);
  const b = new Date(w.to);
  const sameMonth = a.getMonth() === b.getMonth();
  if (sameMonth) {
    return `${a.getDate()}-${b.getDate()} ${months[a.getMonth()]}`;
  }
  return `${a.getDate()} ${months[a.getMonth()]} – ${b.getDate()} ${months[b.getMonth()]}`;
}

export default function WeekProfitHero() {
  const current = lastClosedWeek();
  const previous = previousWeek(current);

  const curQ = useQuery<any>({
    queryKey: ["week-profit-hero", "current", current.from, current.to],
    queryFn: () => api.dashboard({ start: current.from, end: current.to }, "final"),
  });
  const prevQ = useQuery<any>({
    queryKey: ["week-profit-hero", "previous", previous.from, previous.to],
    queryFn: () => api.dashboard({ start: previous.from, end: previous.to }, "final"),
  });

  if (curQ.isLoading || prevQ.isLoading) {
    return (
      <div className="card">
        <div className="text-xs text-muted uppercase mb-1">Прибыль вчера (за прошлую закрытую неделю)</div>
        <div className="text-3xl font-mono font-medium opacity-30">— ₽</div>
      </div>
    );
  }

  const curProfit = getKpi(curQ.data?.kpis ?? [], "net_profit");
  const prevProfit = getKpi(prevQ.data?.kpis ?? [], "net_profit");

  if (curProfit == null) {
    return null; // нет final-данных — не мешаем, не показываем строку
  }

  const wow =
    prevProfit != null && prevProfit !== 0
      ? ((curProfit - prevProfit) / Math.abs(prevProfit)) * 100
      : null;

  const arrow = wow == null ? "" : wow > 0 ? "▲" : wow < 0 ? "▼" : "→";
  const wowCls =
    wow == null
      ? "text-muted"
      : wow > 0
        ? "text-success"
        : wow < 0
          ? "text-danger"
          : "text-muted";

  const cur = curQ.data?.kpis ?? [];
  const revenue = getKpi(cur, "revenue_net");
  const cogs = getKpi(cur, "cogs_total");
  const adCost = getKpi(cur, "ad_cost");
  const commission = getKpi(cur, "commission_wb");
  const logistics = getKpi(cur, "logistics_wb");
  const storage = getKpi(cur, "storage_wb");

  const tooltip =
    `Прибыль = Выручка − COGS − Реклама − Удержания WB (комиссия + логистика + хранение)\n` +
    `Период: ${current.from} → ${current.to} (последняя закрытая WB-неделя)\n` +
    (revenue != null ? `Выручка net: ${fmtRub(revenue)}\n` : "") +
    (cogs != null ? `COGS: ${fmtRub(cogs)}\n` : "") +
    (adCost != null ? `Реклама: ${fmtRub(adCost)}\n` : "") +
    (commission != null ? `Комиссия WB: ${fmtRub(commission)}\n` : "") +
    (logistics != null ? `Логистика WB: ${fmtRub(logistics)}\n` : "") +
    (storage != null ? `Хранение WB: ${fmtRub(storage)}\n` : "") +
    (wow != null && prevProfit != null
      ? `\nWoW: предыдущая неделя ${fmtRub(prevProfit)} → текущая ${fmtRub(curProfit)} (${wow >= 0 ? "+" : ""}${fmtPct(wow, 1)})`
      : "");

  return (
    <div className="card" title={tooltip}>
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="flex items-baseline gap-3 flex-wrap">
          <div className="text-xs text-muted uppercase">Прибыль за прошлую закрытую неделю</div>
          <div className="text-xs text-muted font-mono">{fmtPeriod(current)} · final</div>
        </div>
        {wow != null && (
          <div className={`text-xs font-mono ${wowCls}`}>
            {arrow} {wow >= 0 ? "+" : ""}{fmtPct(wow, 1)} WoW
          </div>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-4 flex-wrap">
        <div className="text-3xl md:text-4xl font-mono font-semibold tabular-nums">
          {fmtRub(curProfit)}
        </div>
        {prevProfit != null && (
          <div className="text-sm text-muted font-mono">
            пред. {fmtRub(prevProfit)}
          </div>
        )}
      </div>
    </div>
  );
}
