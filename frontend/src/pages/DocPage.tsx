/**
 * Generic markdown-doc page — рендерит документ по slug'у.
 *
 * Route: `/docs/:slug` (см. App.tsx).
 * Backend: GET `/api/doc/:slug` отдаёт plain text markdown.
 * Whitelist slug'ов — в `backend/app/api/doc_pages.py:_SLUG_TO_FILE`.
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import MarkdownLite from "@/components/MarkdownLite";
import PageHeader from "@/components/PageHeader";

const TITLES: Record<string, string> = {
  "promo-calculator": "Методика калькулятора WB-акций",
  "unit-plan": "Методика плановой юнит-экономики (UNIT-план)",
  // TASK-LEAD-095
  "transit-calculator": "Методика калькулятора транзитной поставки",
  "supply-calculator": "Методика калькулятора прямой поставки",
  "reconciliation": "Методика сверки P&L с WB-кабинетом",
};

async function fetchDoc(slug: string): Promise<string> {
  const r = await fetch(`/api/doc/${encodeURIComponent(slug)}`, {
    credentials: "include",
  });
  if (!r.ok) {
    if (r.status === 404) {
      throw new Error("not_found");
    }
    throw new Error(`Failed to load doc: ${r.status}`);
  }
  return r.text();
}

export default function DocPage() {
  const { slug = "" } = useParams<{ slug: string }>();

  const { data, isLoading, error } = useQuery({
    queryKey: ["doc-page", slug],
    queryFn: () => fetchDoc(slug),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const title = TITLES[slug] ?? `Документация · ${slug}`;

  return (
    <div className="space-y-4">
      <PageHeader
        title={title}
        subtitle={
          <Link
            to="/docs"
            className="inline-flex items-center gap-1 text-muted hover:text-fg text-sm"
          >
            ← Назад к руководству
          </Link>
        }
      />

      <div className="card">
        {isLoading && <div className="text-muted text-sm">Загрузка…</div>}
        {error && (error as Error).message === "not_found" && (
          <div className="text-danger">
            Документ «{slug}» не найден. Проверь, что он замаунчен в docker
            (см. <code>docker-compose.yml</code>) и зарегистрирован в{" "}
            <code>backend/app/api/doc_pages.py</code>.
          </div>
        )}
        {error && (error as Error).message !== "not_found" && (
          <div className="text-danger">
            Ошибка загрузки: {(error as Error).message}
          </div>
        )}
        {data && <MarkdownLite source={data} />}
      </div>
    </div>
  );
}
