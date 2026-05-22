/**
 * UnitPlanDrillDrawer — drill-down drawer для `/unit-plan` (UNIT-PLAN-018).
 *
 * Открывается при клике на nm в таблице UnitPlan, тянет
 * `/api/unit-plan/{nm}/detail` и показывает 3 секции:
 *   1. История цены 90 дней (AreaChart).
 *   2. Разбивка себестоимости (BarChart + KV-таблица).
 *   3. План vs Факт за текущий месяц (3 KPI-плитки с дельтой).
 *
 * Закрытие: клик по overlay, ESC, кнопка ✕.
 * URL state: `?nm=12345` — shareable link (опционально, см. URL-sync ниже).
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type UnitPlanDetail } from "@/api/client";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { GRID_PROPS, AXIS_PROPS, TOOLTIP_STYLE, CHART_COLORS } from "@/lib/chartTheme";
import { Icon } from "./Icon";

interface Props {
  nm: number;
  vendorCode: string | null;
  brand?: string | null;
  subject?: string | null;
  warehouse?: string | null;
  onClose: () => void;
}

export function UnitPlanDrillDrawer({
  nm,
  vendorCode,
  brand,
  subject,
  warehouse,
  onClose,
}: Props) {
  const [, setSearchParams] = useSearchParams();

  // URL state: ?nm=12345
  useEffect(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("nm", String(nm));
        return next;
      },
      { replace: true },
    );
    return () => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("nm");
          return next;
        },
        { replace: true },
      );
    };
  }, [nm, setSearchParams]);

  // ESC закрывает
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const detail = useQuery({
    queryKey: ["unit-plan-detail", nm],
    queryFn: () => api.unitPlanDetail(nm),
    staleTime: 60_000,
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="flex-1 bg-black/40" />
      <aside
        className="w-[640px] max-w-full h-full bg-bg border-l border-border shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div>
            <div className="text-base font-semibold">
              #{nm}{" "}
              {vendorCode && (
                <span className="text-muted font-normal">{vendorCode}</span>
              )}
            </div>
            <div className="text-tiny text-muted">
              {[brand, subject, warehouse].filter(Boolean).join(" · ") || "—"}
            </div>
          </div>
          <button
            className="btn text-xs"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <Icon name="close" size={12} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5 text-sm">
          {detail.isLoading && (
            <div className="text-muted text-tiny">Загрузка…</div>
          )}
          {detail.isError && (
            <div className="rounded border border-danger bg-danger-subtle p-3 text-tiny text-danger">
              Ошибка загрузки: {(detail.error as Error)?.message || "unknown"}
            </div>
          )}
          {detail.data && <DetailBody data={detail.data} />}
        </div>

        <div className="border-t border-border p-3 flex gap-2">
          <Link
            to={`/units?nm=${nm}`}
            className="btn text-xs flex-1 text-center"
          >
            Открыть в Units →
          </Link>
          <Link
            to={`/calc?nm=${nm}`}
            className="btn text-xs flex-1 text-center"
          >
            Калькулятор →
          </Link>
        </div>
      </aside>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────

function DetailBody({ data }: { data: UnitPlanDetail }) {
  return (
    <>
      <PriceHistorySection points={data.price_history} />
      <CogsBreakdownSection cogs={data.cogs_breakdown} />
      <PlanVsFactSection pvf={data.plan_vs_fact} />
    </>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-tiny text-faint uppercase tracking-wide mb-2">
      {children}
    </div>
  );
}

function PriceHistorySection({
  points,
}: {
  points: UnitPlanDetail["price_history"];
}) {
  return (
    <section>
      <SectionTitle>История цены 90 дней</SectionTitle>
      {points.length === 0 ? (
        <div className="rounded border border-border bg-surface-2/30 p-3 text-tiny text-muted">
          Нет продаж за 90 дней — история цены недоступна.
        </div>
      ) : (
        <div className="rounded border border-border bg-surface-2/30 p-2 h-56">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={points}
              margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
            >
              <defs>
                <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis
                {...AXIS_PROPS}
                dataKey="date"
                tick={{ fontSize: 10, fill: AXIS_PROPS.tick.fill }}
                tickFormatter={(v: string) => v.slice(5)}
                minTickGap={20}
              />
              <YAxis
                {...AXIS_PROPS}
                tick={{ fontSize: 10, fill: AXIS_PROPS.tick.fill }}
                tickFormatter={(v: number) => fmtNum(v)}
                width={50}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(value: number, name: string) => {
                  if (name === "price_with_disc")
                    return [fmtRub(value), "Цена с СПП"];
                  return [fmtRub(value), name];
                }}
              />
              <Area
                type="monotone"
                dataKey="price_with_disc"
                stroke="#3b82f6"
                strokeWidth={2}
                fill="url(#priceFill)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function CogsBreakdownSection({
  cogs,
}: {
  cogs: UnitPlanDetail["cogs_breakdown"];
}) {
  if (!cogs) {
    return (
      <section>
        <SectionTitle>Себестоимость</SectionTitle>
        <div className="rounded border border-border bg-surface-2/30 p-3 text-tiny text-muted">
          Запись Cogs отсутствует. Добавьте через Excel-импорт или вручную.
        </div>
      </section>
    );
  }

  const bars = [
    { name: "Закуп", value: cogs.cost_rub, color: CHART_COLORS[2] },
    { name: "Упаковка", value: cogs.packaging_rub, color: CHART_COLORS[3] },
    { name: "Фулф.", value: cogs.fulfillment_rub, color: CHART_COLORS[0] },
  ].filter((b) => b.value > 0);

  return (
    <section>
      <SectionTitle>Разбивка себестоимости</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded border border-border bg-surface-2/30 p-2 h-44">
          {bars.length === 0 ? (
            <div className="flex h-full items-center justify-center text-tiny text-muted">
              нули — нет разбивки
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={bars}
                margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
              >
                <CartesianGrid {...GRID_PROPS} />
                <XAxis
                  {...AXIS_PROPS}
                  dataKey="name"
                  tick={{ fontSize: 10, fill: AXIS_PROPS.tick.fill }}
                />
                <YAxis
                  {...AXIS_PROPS}
                  tick={{ fontSize: 10, fill: AXIS_PROPS.tick.fill }}
                  tickFormatter={(v: number) => fmtNum(v)}
                  width={50}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [fmtRub(v), "Сумма"]}
                />
                <Bar dataKey="value">
                  {bars.map((b) => (
                    <Cell key={b.name} fill={b.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="rounded border border-border bg-surface-2/30 p-3 text-tiny space-y-1.5">
          <KvLine label="Закуп" value={fmtRub(cogs.cost_rub)} />
          <KvLine label="Упаковка" value={fmtRub(cogs.packaging_rub)} />
          <KvLine label="Фулфилмент" value={fmtRub(cogs.fulfillment_rub)} />
          <div className="border-t border-border pt-1.5 flex justify-between font-semibold">
            <span>Итого</span>
            <span className="font-mono">{fmtRub(cogs.total)}</span>
          </div>
          <div className="text-faint pt-2 leading-relaxed">
            Действует с{" "}
            <span className="text-fg">{cogs.valid_from || "—"}</span>
            {cogs.valid_to && (
              <>
                {" "}
                по <span className="text-fg">{cogs.valid_to}</span>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function PlanVsFactSection({
  pvf,
}: {
  pvf: UnitPlanDetail["plan_vs_fact"];
}) {
  return (
    <section>
      <SectionTitle>План vs Факт — {pvf.month}</SectionTitle>
      <div className="grid grid-cols-3 gap-2">
        <PvfTile
          label="Заказы"
          plan={fmtNum(pvf.orders.plan)}
          fact={fmtNum(pvf.orders.fact)}
          diff={pvf.orders.diff_pct}
          diffUnit="%"
        />
        <PvfTile
          label="Выручка"
          plan={fmtRub(pvf.revenue.plan)}
          fact={fmtRub(pvf.revenue.fact)}
          diff={pvf.revenue.diff_pct}
          diffUnit="%"
        />
        <PvfTile
          label="Маржа"
          plan={
            pvf.margin_pct.plan != null ? fmtPct(pvf.margin_pct.plan) : "—"
          }
          fact={
            pvf.margin_pct.fact != null ? fmtPct(pvf.margin_pct.fact) : "—"
          }
          diff={pvf.margin_pct.diff_pp}
          diffUnit="pp"
        />
      </div>
    </section>
  );
}

function PvfTile({
  label,
  plan,
  fact,
  diff,
  diffUnit,
}: {
  label: string;
  plan: string;
  fact: string;
  diff: number | null;
  diffUnit: "%" | "pp";
}) {
  const diffColor =
    diff == null
      ? "text-faint"
      : diff >= 0
      ? "text-success"
      : "text-danger";
  const diffSign = diff != null && diff > 0 ? "+" : "";
  return (
    <div className="rounded border border-border bg-surface-2/30 p-2.5">
      <div className="text-tiny text-faint uppercase tracking-wide">
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <div className="font-mono font-semibold text-base">{fact}</div>
        <div className={"text-tiny " + diffColor}>
          {diff == null
            ? "—"
            : `${diffSign}${diff.toFixed(1)}${diffUnit === "%" ? "%" : "пп"}`}
        </div>
      </div>
      <div className="text-tiny text-muted mt-0.5">план: {plan}</div>
    </div>
  );
}

function KvLine({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
