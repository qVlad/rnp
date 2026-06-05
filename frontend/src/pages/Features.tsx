/**
 * Каталог функционала сервиса — рендерит FEATURES.md.
 *
 * Источник: backend `/api/features-doc`, который читает файл `FEATURES.md`
 * замаунченный read-only в контейнер из репозитория. Single source of truth —
 * один и тот же файл и для разработчика, и для пользователя в UI.
 *
 * Side-nav: автоматически собирается из h2-заголовков. Клик прокручивает к
 * якорю. Sticky на десктопе.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import MarkdownLite from "@/components/MarkdownLite";
import { Icon } from "@/components/Icon";

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-zа-яё0-9\s-]/gi, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 80);
}

interface Heading {
  level: number;
  text: string;
  id: string;
}

function extractH2(md: string): Heading[] {
  const out: Heading[] = [];
  for (const raw of md.split("\n")) {
    const m = raw.match(/^(##)\s+(.+?)\s*$/);
    if (m) {
      const text = m[2];
      out.push({ level: 2, text, id: slugify(text) });
    }
  }
  return out;
}

type CatalogMode = "user" | "dev";
const MODE_KEY = "features.mode.v1";

export default function Features() {
  // TASK-LEAD-075 — toggle user-facing (USER_GUIDE.md) vs dev-reference (FEATURES.md).
  // Default = "user" (бизнес-юзер по умолчанию).
  const [mode, setMode] = useState<CatalogMode>(() => {
    const saved = localStorage.getItem(MODE_KEY);
    return saved === "dev" ? "dev" : "user";
  });
  useEffect(() => {
    localStorage.setItem(MODE_KEY, mode);
  }, [mode]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["features-doc", mode],
    queryFn: () => (mode === "user" ? api.userGuideDoc() : api.featuresDoc()),
    staleTime: 60_000,
  });

  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string>("");

  const headings = useMemo(() => (data ? extractH2(data) : []), [data]);

  // Фильтрация: оставляем разделы (между ## заголовками) которые содержат query
  const filtered = useMemo(() => {
    if (!data) return null;
    if (!query.trim()) return data;
    const q = query.trim().toLowerCase();
    const lines = data.split("\n");
    // Собираем разделы: каждый блок начинается с h2 (##)
    const blocks: { header: string; body: string[] }[] = [];
    let current: { header: string; body: string[] } | null = { header: "__intro__", body: [] };
    blocks.push(current);
    for (const line of lines) {
      const m = line.match(/^##\s+/);
      if (m) {
        current = { header: line, body: [] };
        blocks.push(current);
      } else if (current) {
        current.body.push(line);
      }
    }
    const kept = blocks.filter((b) => {
      const all = (b.header + "\n" + b.body.join("\n")).toLowerCase();
      return all.includes(q);
    });
    if (kept.length === 0) return "Ничего не найдено по запросу: **" + query + "**";
    return kept.map((b) => (b.header === "__intro__" ? b.body.join("\n") : b.header + "\n" + b.body.join("\n"))).join("\n");
  }, [data, query]);

  // Scrollspy
  useEffect(() => {
    if (!headings.length) return;
    const onScroll = () => {
      const top = window.scrollY + 100;
      let current = headings[0]?.id ?? "";
      for (const h of headings) {
        const el = document.getElementById(h.id);
        if (el && el.offsetTop <= top) {
          current = h.id;
        }
      }
      setActiveId(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [headings]);

  // Deep-link: при загрузке (или смене hash) прокручиваем к якорю из URL —
  // чтобы ссылка /features#<раздел> вела прямо в нужную функцию.
  useEffect(() => {
    if (!data) return;
    const scrollToHash = () => {
      const hash = decodeURIComponent(window.location.hash.replace(/^#/, ""));
      if (!hash) return;
      const el = document.getElementById(hash);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        setActiveId(hash);
      }
    };
    const t = setTimeout(scrollToHash, 150);
    window.addEventListener("hashchange", scrollToHash);
    return () => {
      clearTimeout(t);
      window.removeEventListener("hashchange", scrollToHash);
    };
  }, [data]);

  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <aside className="lg:w-72 flex-shrink-0">
        <div className="card sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto">
          <div className="mb-3">
            {/* TASK-UI-011: h1 живёт внутри sticky-sidebar (не page-shell),
                PageHeader не подходит — оставлен inline. */}
            <h1 className="text-lg font-semibold">Каталог функций</h1>
            <div className="text-xs text-muted">
              {mode === "user"
                ? "Описание для пользователя — что делает, чем полезно"
                : "Технический реестр модулей сервиса"}
            </div>
          </div>

          {/* TASK-LEAD-075 — segmented control user / dev */}
          <div className="mb-3 inline-flex rounded-md border border-border overflow-hidden text-xs">
            <button
              type="button"
              className={`px-2 py-1 ${
                mode === "user"
                  ? "bg-accent text-fg-on-accent font-medium"
                  : "bg-surface-2 text-muted hover:text-fg"
              }`}
              onClick={() => setMode("user")}
            >
              Для пользователя
            </button>
            <button
              type="button"
              className={`px-2 py-1 ${
                mode === "dev"
                  ? "bg-accent text-fg-on-accent font-medium"
                  : "bg-surface-2 text-muted hover:text-fg"
              }`}
              onClick={() => setMode("dev")}
            >
              Для разработчика
            </button>
          </div>

          <div className="relative mb-3">
            <Icon name="search" size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              className="input w-full pl-7"
              placeholder="Поиск…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {!query && (
            <nav className="text-sm">
              {headings.map((h) => (
                <a
                  key={h.id}
                  href={`#${h.id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    const el = document.getElementById(h.id);
                    if (el) {
                      el.scrollIntoView({ behavior: "smooth", block: "start" });
                      setActiveId(h.id);
                    }
                  }}
                  className={`block py-1 px-2 rounded-md truncate ${
                    activeId === h.id ? "bg-accent/10 text-accent" : "hover:bg-surface-2/50 text-fg"
                  }`}
                  title={h.text}
                >
                  {h.text}
                </a>
              ))}
            </nav>
          )}

          {query && (
            <div className="text-xs text-muted">
              Поиск активен. Очисти поле — вернётся оглавление.
            </div>
          )}
        </div>
      </aside>

      <article className="card flex-1 min-w-0">
        {isLoading && <div className="text-muted">Загружаю каталог…</div>}
        {error && (
          <div className="text-danger">
            Ошибка загрузки FEATURES.md: {(error as Error).message}
          </div>
        )}
        {data && filtered && <MarkdownLite source={filtered} />}
      </article>
    </div>
  );
}
