/**
 * Единая страница «Налоги» (TASK-LEAD-041).
 *
 * Объединяет 5 ранее раздельных страниц (`/tax-report`, `/tax-report-ausn`,
 * `/tax-report-usn`, `/tax-report-usn-vat5`, `/tax-report-usn-vat7`) в
 * табы. Активный режим определяется query-param `?mode=base|ausn|usn|usn-vat5|usn-vat7`
 * (default `ausn` — самый частый кейс по OWNER_GUIDE).
 *
 * Внутри каждого таба переиспользуем существующие страницы как монолитные
 * компоненты — не дублируем логику, не ломаем backend.
 */
import { useSearchParams } from "react-router-dom";
import TaxReport from "./TaxReport";
import TaxReportAusn from "./TaxReportAusn";
import TaxReportUsn, {
  TaxReportUsnVat5,
  TaxReportUsnVat7,
} from "./TaxReportUsn";
import PageHeader from "@/components/PageHeader";

type Mode = "base" | "ausn" | "usn" | "usn-vat5" | "usn-vat7";

const TABS: { mode: Mode; label: string; short: string }[] = [
  { mode: "base", label: "Метод 1С", short: "1С" },
  { mode: "ausn", label: "АУСН-Доходы 8%", short: "АУСН 8%" },
  { mode: "usn", label: "УСН-Доходы 6%", short: "УСН 6%" },
  { mode: "usn-vat5", label: "УСН 6% + НДС 5%", short: "УСН+НДС 5%" },
  { mode: "usn-vat7", label: "УСН 6% + НДС 7%", short: "УСН+НДС 7%" },
];

function isMode(value: string | null): value is Mode {
  return (
    value === "base" ||
    value === "ausn" ||
    value === "usn" ||
    value === "usn-vat5" ||
    value === "usn-vat7"
  );
}

export default function Taxes() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get("mode");
  const mode: Mode = isMode(raw) ? raw : "ausn";

  const setMode = (next: Mode) => {
    // preserveOther search-params — на случай, если когда-то прокинем
    // `from`/`to` снаружи.
    const params = new URLSearchParams(searchParams);
    params.set("mode", next);
    setSearchParams(params, { replace: true });
  };

  return (
    <div>
      <PageHeader
        title="Налоги"
        subtitle="Все налоговые отчёты в одном окне. Переключай режим вкладками — backend не меняется, под каждой вкладкой та же страница, что раньше жила на отдельном URL."
      />
      <div
        className="flex gap-1 border-b border-border mb-4 overflow-x-auto"
        role="tablist"
        aria-label="Налоговые режимы"
      >
        {TABS.map((t) => {
          const active = t.mode === mode;
          return (
            <button
              key={t.mode}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setMode(t.mode)}
              className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors ${
                active
                  ? "border-accent text-fg font-medium"
                  : "border-transparent text-muted hover:text-fg"
              }`}
              title={t.label}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel">
        {mode === "base" && <TaxReport />}
        {mode === "ausn" && <TaxReportAusn />}
        {mode === "usn" && <TaxReportUsn />}
        {mode === "usn-vat5" && <TaxReportUsnVat5 />}
        {mode === "usn-vat7" && <TaxReportUsnVat7 />}
      </div>
    </div>
  );
}
