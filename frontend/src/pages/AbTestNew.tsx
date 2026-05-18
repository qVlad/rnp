/**
 * Создание нового A/B теста — простая форма.
 * После создания → редирект на /abtest/:id (детали — там загружаем фото).
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  abtestApi,
  TrafficSource,
  TestMode,
  TriggerMode,
} from "@/api/abtest";
import { StagedFile, VariantPhotoGrid } from "@/components/abtest/VariantPhotoGrid";

interface ProductOption {
  nm_id: number;
  vendor_code: string | null;
  subject: string | null;
  brand: string | null;
  photo_url: string | null;
}

/**
 * Searchable combobox по products. /api/products?search=, debounce 200ms.
 * Показывает превью карточки (фото-прокси WB CDN).
 */
function ProductPicker({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (nmId: number | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(query), 200);
    return () => clearTimeout(id);
  }, [query]);

  const selectedQ = useQuery({
    queryKey: ["product-detail", value],
    queryFn: async (): Promise<ProductOption | null> => {
      if (!value) return null;
      const resp = await fetch(`/api/products?search=${value}`, {
        credentials: "include",
      });
      if (!resp.ok) return null;
      const data = (await resp.json()) as { items?: ProductOption[] };
      return data.items?.find((p) => p.nm_id === value) || null;
    },
    enabled: !!value,
  });

  const searchQ = useQuery({
    queryKey: ["product-search-abtest", debounced],
    queryFn: async (): Promise<ProductOption[]> => {
      // has_photo=true — отсекаем карточки без photo_url. Без этого picker
      // показывал бы SKU, для которых «Подгрузить текущее» вернёт 404
      // (~2% products по QA-аудиту, но именно они порождали жалобу).
      const base = "/api/products?has_photo=true";
      const url = debounced
        ? `${base}&search=${encodeURIComponent(debounced)}`
        : base;
      const resp = await fetch(url, { credentials: "include" });
      if (!resp.ok) throw new Error("Не удалось загрузить products");
      const data = (await resp.json()) as { items?: ProductOption[] };
      return (data.items || []).slice(0, 30);
    },
    enabled: open,
  });

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const selected = selectedQ.data;
  const items = searchQ.data || [];

  return (
    <div className="relative" ref={wrapRef}>
      {value ? (
        // Чип показываем сразу как value != null. selectedQ подтянет детали
        // (subject/brand) асинхронно; пока её нет, показываем хотя бы nm_id.
        // Раньше чип появлялся ТОЛЬКО когда selectedQ.data резолвилась —
        // если поиск не находил карточку (а он не находил по nm_id до
        // backend-фикса), чип не появлялся вообще, и dropdown тоже не
        // открывался (`!value` был false) → залипание.
        <div className="flex items-center gap-2 input">
          <img
            src={`/api/products/${value}/photo`}
            alt=""
            className="w-10 h-10 object-cover rounded"
            onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
          />
          <div className="flex-1 min-w-0">
            <div className="font-mono text-sm">{value}</div>
            <div className="text-xs text-muted truncate">
              {selected
                ? `${selected.subject || selected.vendor_code || "—"}${selected.brand ? ` · ${selected.brand}` : ""}`
                : selectedQ.isLoading
                  ? "Загрузка деталей…"
                  : "Карточка выбрана"}
            </div>
          </div>
          <button
            type="button"
            className="btn-link text-xs"
            onClick={() => {
              onChange(null);
              setQuery("");
              setOpen(true);
            }}
          >
            ✕ Сменить
          </button>
        </div>
      ) : (
        <input
          className="input w-full"
          placeholder="Найти карточку: nm_id, артикул, бренд…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          // onMouseDown а не onFocus: если input уже сфокусирован после
          // первой попытки выбрать товар — клик заново должен открыть
          // dropdown. onFocus в этом случае не сработает.
          onMouseDown={() => setOpen(true)}
        />
      )}

      {open && !value && (
        <div
          className="absolute top-full left-0 right-0 mt-1 bg-surface border border-border rounded shadow-xl max-h-80 overflow-y-auto z-50"
        >
          {searchQ.isLoading && (
            <div className="p-3 text-muted text-sm">Загрузка…</div>
          )}
          {searchQ.error && (
            <div className="p-3 text-warn text-sm">
              {(searchQ.error as Error).message}
            </div>
          )}
          {!searchQ.isLoading && items.length === 0 && (
            <div className="p-3 text-muted text-sm">
              {debounced
                ? "Ничего не нашлось. Засинкайте карточки в /settings → WB sync."
                : "Список products пуст. Засинкайте карточки в /settings → WB sync."}
            </div>
          )}
          {items.map((p) => (
            <div
              key={p.nm_id}
              role="button"
              tabIndex={0}
              // Селекция на mousedown (а НЕ click) с stopPropagation чтобы
              // document-listener не успел закрыть dropdown раньше.
              // preventDefault сохраняет фокус и предотвращает text-select.
              // Используем <div role=button> а не <button>, потому что
              // <button> внутри React-flow с document-mousedown-listener
              // регулярно теряет click (timing race).
              onMouseDown={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onChange(p.nm_id);
                setOpen(false);
                setQuery("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onChange(p.nm_id);
                  setOpen(false);
                  setQuery("");
                }
              }}
              className="flex items-center gap-2 w-full text-left p-2 hover:bg-surface-2 border-b border-border last:border-b-0 cursor-pointer select-none"
            >
              <img
                src={`/api/products/${p.nm_id}/photo`}
                alt=""
                className="w-8 h-8 object-cover rounded shrink-0 pointer-events-none"
                onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
              />
              <div className="flex-1 min-w-0 pointer-events-none">
                <div className="font-mono text-sm">{p.nm_id}</div>
                <div className="text-xs text-muted truncate">
                  {p.subject || p.vendor_code || "—"}
                  {p.brand ? ` · ${p.brand}` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------
// TrafficEstimateBanner — предупреждение о времени набора выборки.
// ----------------------------------------------------------------------

function TrafficEstimateBanner({
  nmId,
  variantCount,
  minSampleSize,
  triggerMode,
  triggerValue,
}: {
  nmId: number | null;
  variantCount: number;
  minSampleSize: number;
  triggerMode: TriggerMode;
  triggerValue: number;
}) {
  const q = useQuery({
    queryKey: ["traffic-estimate", nmId],
    queryFn: async () => {
      const r = await fetch(`/api/products/${nmId}/traffic-estimate`, {
        credentials: "include",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<{
        avg_daily_impressions: number | null;
        days_observed: number;
        source: string;
        http_status: number | null;
      }>;
    },
    enabled: nmId != null,
  });

  if (!nmId) return null;
  if (q.isLoading)
    return <div className="text-xs text-muted">Оценка трафика…</div>;
  const data = q.data;
  if (!data) return null;

  if (data.source === "no-token") {
    return (
      <div className="text-xs border border-info/30 bg-info-bg/30 rounded p-2 text-info">
        Сначала добавьте WB-токен в /settings — без него мы не оценим трафик
        карточки.
      </div>
    );
  }
  if (data.source === "wb-error") {
    return (
      <div className="text-xs border border-warn/30 bg-warn-bg/30 rounded p-2 text-warn">
        WB API вернул ошибку{data.http_status ? ` (${data.http_status})` : ""} —
        параметры можно выбрать без оценки.
      </div>
    );
  }
  const avg = data.avg_daily_impressions ?? 0;
  if (avg === 0) {
    return (
      <div className="text-xs border border-info/30 bg-info-bg/30 rounded p-2 text-info">
        У карточки нет показов за последние 7 дней. Тест запустится, но
        реалистичная оценка появится после первого дня.
      </div>
    );
  }
  const dailyPerVariant = Math.max(1, Math.floor(avg / Math.max(2, variantCount)));
  const daysToMin = Math.ceil(minSampleSize / dailyPerVariant);
  const warnings: string[] = [];
  if (triggerMode === "VIEWS") {
    const cycleDays = Math.ceil(triggerValue / dailyPerVariant);
    if (cycleDays > 3) {
      warnings.push(
        `Один цикл VIEWS-ротации займёт ~${cycleDays} дн. при ~${avg} показах/сутки. Это много — внешние факторы исказят сравнение. Лучше выбрать «Быстрая» или «Стандартная» (TIME).`,
      );
    }
  }
  if (daysToMin > 14) {
    warnings.push(
      `До набора минимальной выборки (${minSampleSize} показов на вариант) пройдёт ~${daysToMin} дн. при ~${avg} показах/сутки. Уменьшите «Мин. выборку» либо примите долгое ожидание.`,
    );
  }
  const ok = warnings.length === 0;
  return (
    <div
      className={`text-xs rounded p-2 border ${
        ok
          ? "border-success/30 bg-success-bg/30 text-success"
          : "border-warn/30 bg-warn-bg/30 text-warn"
      }`}
    >
      <div className="font-medium">
        {ok ? "✓ Параметры подходят" : "⚠ Внимание"}
        <span className="ml-2 opacity-80 font-normal">
          Трафик ~{avg} показов/сутки ({data.days_observed} дн. истории)
        </span>
      </div>
      {ok ? (
        <div className="mt-1 opacity-80">
          {triggerMode === "VIEWS"
            ? `Один цикл ~${Math.ceil(triggerValue / dailyPerVariant)} дн., до выборки ~${daysToMin} дн.`
            : `До набора выборки ~${daysToMin} дн.`}
        </div>
      ) : (
        <ul className="mt-1 list-disc pl-4 space-y-1">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------
// CampaignPicker — выбор активной РК (для ADV-сценариев).
// ----------------------------------------------------------------------

function CampaignPicker({
  nmId,
  value,
  onChange,
}: {
  nmId: number | null;
  value: string;
  onChange: (v: string) => void;
}) {
  const [filterByNm, setFilterByNm] = useState(true);
  const q = useQuery({
    queryKey: ["abtest-campaigns", filterByNm ? nmId : null],
    queryFn: () => abtestApi.listCampaigns(filterByNm ? nmId : null),
    enabled: nmId != null,
  });

  const STATUS_TXT: Record<number, string> = {
    4: "пауза",
    7: "активна",
    9: "готова",
    11: "приостановлена",
  };
  const TYPE_TXT: Record<number, string> = {
    4: "Каталог",
    5: "Поиск",
    8: "Поиск+Каталог",
    9: "Авто",
  };

  const items = q.data?.items || [];

  return (
    <div className="space-y-2">
      <div className="flex gap-2 items-center">
        <select
          className="input flex-1"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={q.isLoading || !nmId}
        >
          <option value="">
            {!nmId
              ? "Сначала выберите карточку"
              : q.isLoading
                ? "Загрузка кампаний…"
                : items.length === 0
                  ? filterByNm
                    ? "Нет РК для этой карточки"
                    : "Нет активных РК"
                  : "Выберите РК…"}
          </option>
          {items.map((c) => (
            <option key={c.advertId} value={String(c.advertId)}>
              [{c.advertId}] {c.name} ·{" "}
              {TYPE_TXT[c.type || 0] || `type=${c.type}`} ·{" "}
              {STATUS_TXT[c.status || 0] || `status=${c.status}`}
            </option>
          ))}
        </select>
        <input
          type="number"
          className="input w-32"
          placeholder="или ID вручную"
          value={items.find((c) => String(c.advertId) === value) ? "" : value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      {nmId && items.length === 0 && filterByNm && !q.isLoading && (
        <button
          type="button"
          className="btn-link text-xs"
          onClick={() => setFilterByNm(false)}
        >
          Показать все РК тенанта (без фильтра по nm_id)
        </button>
      )}
      {q.error && (
        <div className="text-warn text-xs">
          {(q.error as Error).message}
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------
// Preset triggers — соответствуют wbab «Быстрая / Стандартная / Точная».
// Цель: пользователь не задаёт VIEWS=1500 руками — кликает preset и идёт
// дальше. «Точная» включается только когда у карточки трафик ≥1000/день
// (мы это не оцениваем, поэтому показываем всегда но с подсказкой).
// ----------------------------------------------------------------------
type PresetId = "quick" | "standard" | "precise" | "custom";

const PRESETS: Record<PresetId, {
  label: string;
  description: string;
  trigger_mode: TriggerMode;
  trigger_value: number;
  min_sample_size: number;
}> = {
  quick: {
    label: "Быстрая проверка",
    description: "TIME-ротация 120 мин, выборка 500 показов на вариант",
    trigger_mode: "TIME",
    trigger_value: 120,
    min_sample_size: 500,
  },
  standard: {
    label: "Стандартная",
    description: "TIME-ротация 360 мин (6ч), выборка 1500 показов",
    trigger_mode: "TIME",
    trigger_value: 360,
    min_sample_size: 1500,
  },
  precise: {
    label: "Точная",
    description: "VIEWS-ротация 1500 на вариант (для трафика ≥1000/день)",
    trigger_mode: "VIEWS",
    trigger_value: 1500,
    min_sample_size: 1500,
  },
  custom: {
    label: "Свои настройки",
    description: "Ручная настройка триггера и выборки",
    trigger_mode: "TIME",
    trigger_value: 360,
    min_sample_size: 1500,
  },
};

// ----------------------------------------------------------------------
// Scenario — 4 готовых комбинации traffic_source × test_mode (как в wbab).
// Невалидные комбинации (ANY+PHOTO, BOTH+PHOTO) исключены: на органике нет
// «клика по обложке», мерять CTR без adv нельзя.
// ----------------------------------------------------------------------
type ScenarioId = "ADV_PHOTO" | "ADV_FUNNEL" | "ANY_FUNNEL" | "BOTH_FUNNEL";

const SCENARIOS: Array<{
  id: ScenarioId;
  emoji: string;
  title: string;
  description: string;
  trafficSource: TrafficSource;
  testMode: TestMode;
  needsAdv: boolean;
}> = [
  {
    id: "ADV_PHOTO",
    emoji: "📸",
    title: "Главное фото на рекламе",
    description:
      'Меняем только обложку (главное фото). Сравниваем варианты по «Показы рекламы → Клик» — это моментальная реакция на обложку в рекламной выдаче, без лагов. Требует рекламной кампании. Период 3-7 дней, выборка от 1500 показов на вариант.',
    trafficSource: "ADV_ONLY",
    testMode: "PHOTO",
    needsAdv: true,
  },
  {
    id: "ADV_FUNNEL",
    emoji: "📸📣",
    title: "Полная воронка через рекламу",
    description:
      'Меняем все фото варианта. Сравниваем по «Клик рекламы → В корзину, %» — Adv API отдаёт корзину (поле atbs) без лагов и с точной атрибуцией к варианту. Знаменатель — клики по рекламе (это «дошёл до карточки»). Самый чистый сценарий для воронки. Требует РК. Период 5-10 дней, выборка от 3000 показов на вариант.',
    trafficSource: "ADV_ONLY",
    testMode: "FUNNEL",
    needsAdv: true,
  },
  {
    id: "ANY_FUNNEL",
    emoji: "🎯",
    title: "Полная воронка на общем трафике",
    description:
      'Меняем все фото варианта (главное + доп.). Сравниваем по «Открытие карточки → В корзину, %» — единственная честная метрика на органике (есть точные данные WB nm-report). Заказы и выкупы показываем справочно. Без РК. Период 7-14 дней, выборка от 3000 показов на вариант.',
    trafficSource: "ANY",
    testMode: "FUNNEL",
    needsAdv: false,
  },
  {
    id: "BOTH_FUNNEL",
    emoji: "🎯📣",
    title: "Полная воронка + реклама",
    description:
      'То же что выше, но дополнительно собираем рекламную статистику отдельно. Победитель — по «Открытие → В корзину, %» из общего трафика (nm-report). Реклама и органика разделены в UI для анализа, но решение принимаем по корзине. Требует РК. Период 7-14 дней, выборка от 3000 показов на вариант.',
    trafficSource: "BOTH",
    testMode: "FUNNEL",
    needsAdv: true,
  },
];

export default function AbTestNew() {
  const nav = useNavigate();
  const [scenario, setScenario] = useState<ScenarioId>("ANY_FUNNEL");
  const currentScenario =
    SCENARIOS.find((s) => s.id === scenario) ?? SCENARIOS[2];
  const [form, setForm] = useState({
    name: "",
    nm_id: null as number | null,
    trigger_mode: "TIME" as TriggerMode,
    trigger_value: 360,
    campaign_id: "",
    min_sample_size: 3000,
    confidence_level: 0.95,
    keep_leaders_after_24h: false,
    budget_auto_topup: false,
    budget_min_threshold: 500,
    budget_topup_amount: 1000,
    budget_daily_limit: 10000,
    variant_count: 2,
  });
  const [preset, setPreset] = useState<PresetId>("standard");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // Текущие фото с WB для Варианта A (URL'ы, backend сам скачает при create).
  const [currentPhotosA, setCurrentPhotosA] = useState<{ order: number; url: string }[]>([]);
  // Staged-файлы локально для каждого варианта. После create — параллельный
  // batch-upload через `POST /abtest/{id}/variants/{vid}/photos`. Файлы для
  // Варианта A игнорируются если есть currentPhotosA (тогда A заполняется
  // на бэке скачиванием URL'ов).
  const [stagedPhotos, setStagedPhotos] = useState<Record<string, StagedFile[]>>(
    {},
  );
  const [uploadProgress, setUploadProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);

  const stageFile = (label: string, order: number, file: File) => {
    setStagedPhotos((prev) => {
      const existing = prev[label] || [];
      // Replace at same order if any (URL revoke).
      for (const s of existing) {
        if (s.order === order) URL.revokeObjectURL(s.previewUrl);
      }
      const next = existing.filter((s) => s.order !== order);
      next.push({ order, file, previewUrl: URL.createObjectURL(file) });
      next.sort((a, b) => a.order - b.order);
      return { ...prev, [label]: next };
    });
  };
  const unstageFile = (label: string, order: number) => {
    setStagedPhotos((prev) => {
      const existing = prev[label] || [];
      for (const s of existing) {
        if (s.order === order) URL.revokeObjectURL(s.previewUrl);
      }
      return { ...prev, [label]: existing.filter((s) => s.order !== order) };
    });
  };
  // Revoke all object URLs on unmount to avoid memory leak.
  useEffect(
    () => () => {
      for (const list of Object.values(stagedPhotos)) {
        for (const s of list) URL.revokeObjectURL(s.previewUrl);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const applyPreset = (id: PresetId) => {
    setPreset(id);
    const p = PRESETS[id];
    setForm((f) => ({
      ...f,
      trigger_mode: p.trigger_mode,
      trigger_value: p.trigger_value,
      min_sample_size: p.min_sample_size,
    }));
  };

  // Сброс current-photos при смене карточки или сценария — нужна другая воронка.
  useEffect(() => {
    setCurrentPhotosA([]);
  }, [form.nm_id, scenario]);

  // Подгрузка текущих фото WB-карточки.
  const loadCurrentMut = useMutation({
    mutationFn: async () => {
      if (form.nm_id == null) throw new Error("Сначала выберите карточку");
      const count = currentScenario.testMode === "PHOTO" ? 1 : 10;
      const r = await abtestApi.getWbCurrentPhotos(form.nm_id, count);
      return r.photos;
    },
    onSuccess: (photos) => setCurrentPhotosA(photos),
  });

  const createMut = useMutation({
    mutationFn: async () => {
      if (form.nm_id == null) throw new Error("Выберите карточку");
      const created = await abtestApi.create({
        name: form.name,
        nm_id: form.nm_id,
        trigger_mode: form.trigger_mode,
        trigger_value: Number(form.trigger_value),
        traffic_source: currentScenario.trafficSource,
        test_mode: currentScenario.testMode,
        campaign_id: form.campaign_id ? Number(form.campaign_id) : null,
        min_sample_size: Number(form.min_sample_size),
        confidence_level: Number(form.confidence_level),
        keep_leaders_after_24h: form.keep_leaders_after_24h,
        budget_auto_topup: form.budget_auto_topup,
        budget_min_threshold: Number(form.budget_min_threshold),
        budget_topup_amount: Number(form.budget_topup_amount),
        budget_daily_limit: Number(form.budget_daily_limit),
        variant_count: form.variant_count,
        current_photos_a: currentPhotosA.map((p) => p.url),
      });

      // Batch upload staged-файлов: для каждого варианта в response — найти
      // соответствующий staged-список и загрузить параллельно. Для Варианта A
      // если currentPhotosA непуст — staging игнорируется (бэк уже скачал URL'ы).
      const tasks: Array<{ vid: number; order: number; file: File }> = [];
      for (const v of created.variants) {
        const isA = v.label === "A";
        if (isA && currentPhotosA.length > 0) continue;
        const list = stagedPhotos[v.label] || [];
        for (const s of list) {
          tasks.push({ vid: v.id, order: s.order, file: s.file });
        }
      }
      if (tasks.length > 0) {
        setUploadProgress({ done: 0, total: tasks.length });
        let done = 0;
        // Параллелим, но не больше 4 одновременно — щадим nginx (3-MB файлы).
        const POOL = 4;
        const queue = [...tasks];
        const worker = async () => {
          while (queue.length > 0) {
            const t = queue.shift();
            if (!t) break;
            try {
              await abtestApi.uploadPhoto(created.id, t.vid, t.order, t.file);
            } catch (e) {
              console.warn("upload failed", t, e);
            } finally {
              done++;
              setUploadProgress({ done, total: tasks.length });
            }
          }
        };
        await Promise.all(
          Array.from({ length: Math.min(POOL, tasks.length) }, () => worker()),
        );
      }
      return created;
    },
    onSuccess: (data) => nav(`/abtest/${data.id}`),
  });

  const needsAdvert = currentScenario.needsAdv;
  const LABELS = ["A", "B", "C", "D"] as const;
  const variantLabels = LABELS.slice(0, form.variant_count);

  return (
    <div className="space-y-4 max-w-5xl">
      <h1 className="text-2xl font-semibold">Новый A/B тест</h1>
      <p className="text-muted text-sm">
        Создадим черновик. Фото вариантов B/{form.variant_count >= 3 ? "C/" : ""}
        {form.variant_count >= 4 ? "D" : "—"} загрузите на странице теста после
        создания. Запустить можно отдельной кнопкой.
      </p>

      {/* ---------- 1. Основные ---------- */}
      <div className="card space-y-3">
        <h2 className="font-semibold">1. Основные настройки</h2>
        <div>
          <label className="block text-sm text-muted mb-1">Название</label>
          <input
            className="input w-full"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Например: фото инфографика для X-100500"
          />
        </div>
        <div>
          <label className="block text-sm text-muted mb-1">Карточка WB</label>
          <ProductPicker
            value={form.nm_id}
            onChange={(nmId) => setForm({ ...form, nm_id: nmId })}
          />
          <div className="text-xs text-muted mt-1">
            Поиск по nm_id, артикулу или названию. Если списка нет — синхронизируйте
            карточки в /settings → WB sync.
          </div>
        </div>
      </div>

      {/* ---------- 2. Сценарий — 4 карточки как в wbab ---------- */}
      <div className="card space-y-3">
        <h2 className="font-semibold">2. Сценарий теста</h2>
        <p className="text-xs text-muted">
          Выберите готовый сценарий — он определяет методику сравнения
          (что считаем «победой») и тип трафика. Невалидные комбинации
          (общий трафик + только главное фото) исключены: на органике нет
          моментального «клика по обложке», результаты неинтерпретируемы.
        </p>
        <div className="space-y-2">
          {SCENARIOS.map((s) => {
            const active = scenario === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setScenario(s.id)}
                className={`w-full text-left rounded-lg border p-3 transition-colors ${
                  active
                    ? "border-accent bg-accent-subtle"
                    : "border-border hover:bg-surface-2"
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="text-xl shrink-0 leading-none mt-0.5">
                    {s.emoji}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">{s.title}</div>
                    <div className="text-xs text-muted mt-1 leading-relaxed">
                      {s.description}
                    </div>
                  </div>
                  {active && <span className="text-accent shrink-0">●</span>}
                </div>
              </button>
            );
          })}
        </div>

        {currentScenario.testMode === "FUNNEL" && (
          <div className="text-xs text-warn border border-warn/30 bg-warn-bg/30 rounded p-2">
            ⚠ Для воронки в каждый вариант загружайте полный комплект фото
            (главное + до 9 доп.) — иначе тест мало отличается от теста главного
            фото, и эффект новых фото не будет измерен.
          </div>
        )}

        {needsAdvert && (
          <div className="border-t border-border pt-3 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm text-muted mb-1">
                  Рекламная кампания
                </label>
                <CampaignPicker
                  nmId={form.nm_id}
                  value={form.campaign_id}
                  onChange={(v) => setForm({ ...form, campaign_id: v })}
                />
              </div>
              <div>
                <label className="flex items-center gap-2 text-sm mt-6">
                  <input
                    type="checkbox"
                    checked={form.budget_auto_topup}
                    onChange={(e) =>
                      setForm({ ...form, budget_auto_topup: e.target.checked })
                    }
                  />
                  Авто-пополнение РК
                </label>
              </div>
            </div>
            {form.budget_auto_topup && (
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm text-muted mb-1">Порог (₽)</label>
                  <input
                    type="number"
                    className="input w-full"
                    value={form.budget_min_threshold}
                    onChange={(e) =>
                      setForm({ ...form, budget_min_threshold: Number(e.target.value) })
                    }
                  />
                </div>
                <div>
                  <label className="block text-sm text-muted mb-1">Сумма (₽)</label>
                  <input
                    type="number"
                    className="input w-full"
                    value={form.budget_topup_amount}
                    onChange={(e) =>
                      setForm({ ...form, budget_topup_amount: Number(e.target.value) })
                    }
                  />
                </div>
                <div>
                  <label className="block text-sm text-muted mb-1">Лимит/сутки</label>
                  <input
                    type="number"
                    className="input w-full"
                    value={form.budget_daily_limit}
                    onChange={(e) =>
                      setForm({ ...form, budget_daily_limit: Number(e.target.value) })
                    }
                  />
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ---------- 3. Параметры (preset + расширенные) ---------- */}
      <div className="card space-y-3">
        <h2 className="font-semibold">3. Параметры ротации</h2>
        <div className="grid grid-cols-2 gap-2">
          {(["quick", "standard", "precise"] as const).map((id) => {
            const p = PRESETS[id];
            const active = preset === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => applyPreset(id)}
                className={`text-left p-3 rounded border ${
                  active
                    ? "border-accent bg-accent-subtle"
                    : "border-border hover:bg-surface-2"
                }`}
              >
                <div className="font-medium text-sm">{p.label}</div>
                <div className="text-xs text-muted mt-1">{p.description}</div>
              </button>
            );
          })}
        </div>

        <details
          open={advancedOpen || preset === "custom"}
          className="border-t border-border pt-3"
        >
          <summary
            className="cursor-pointer text-sm font-medium select-none"
            onClick={(e) => {
              e.preventDefault();
              setAdvancedOpen((v) => !v);
            }}
          >
            Расширенные настройки
          </summary>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm text-muted mb-1">Тип триггера</label>
              <select
                className="input w-full"
                value={form.trigger_mode}
                onChange={(e) => {
                  setForm({ ...form, trigger_mode: e.target.value as TriggerMode });
                  setPreset("custom");
                }}
              >
                <option value="VIEWS">VIEWS — показы на вариант</option>
                <option value="TIME">TIME — минуты</option>
                {needsAdvert && <option value="BUDGET">BUDGET — ₽ из РК</option>}
              </select>
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">Значение</label>
              <input
                type="number"
                className="input w-full"
                value={form.trigger_value}
                onChange={(e) => {
                  setForm({ ...form, trigger_value: Number(e.target.value) });
                  setPreset("custom");
                }}
              />
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">
                Мин. выборка
              </label>
              <input
                type="number"
                className="input w-full"
                value={form.min_sample_size}
                onChange={(e) => {
                  setForm({ ...form, min_sample_size: Number(e.target.value) });
                  setPreset("custom");
                }}
              />
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">Уровень доверия</label>
              <select
                className="input w-full"
                value={form.confidence_level}
                onChange={(e) =>
                  setForm({ ...form, confidence_level: Number(e.target.value) })
                }
              >
                <option value={0.9}>90%</option>
                <option value={0.95}>95% (стандарт)</option>
                <option value={0.99}>99%</option>
              </select>
            </div>
          </div>
        </details>

        <TrafficEstimateBanner
          nmId={form.nm_id}
          variantCount={form.variant_count}
          minSampleSize={form.min_sample_size}
          triggerMode={form.trigger_mode}
          triggerValue={form.trigger_value}
        />
      </div>

      {/* ---------- 4. Варианты + inline фото ---------- */}
      <div className="card space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">4. Варианты и фото</h2>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">Количество:</span>
            <div className="flex items-center gap-1">
              {[2, 3, 4].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setForm({ ...form, variant_count: n })}
                  className={`px-2 py-1 rounded text-xs ${
                    form.variant_count === n
                      ? "bg-accent text-white"
                      : "bg-surface-2 text-muted hover:text-fg"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* «Подгрузить текущее с WB как Вариант A» — отдельный banner */}
        {form.nm_id != null && currentPhotosA.length === 0 && (
          <div className="border border-dashed border-border rounded p-3 flex items-start gap-3">
            <div className="flex-1">
              <div className="text-sm font-medium">
                📥 Использовать текущее фото с WB как Вариант A
              </div>
              <div className="text-xs text-muted mt-1">
                Подгрузим{" "}
                {currentScenario.testMode === "PHOTO"
                  ? "главное фото"
                  : "всю воронку (до 10 фото)"}{" "}
                карточки прямо с WB — оно станет базой для сравнения.
                Альтернатива — загрузить файлы для A руками в сетке ниже.
              </div>
              {loadCurrentMut.error && (
                <div className="text-warn text-xs mt-1">
                  {(loadCurrentMut.error as Error).message}
                </div>
              )}
            </div>
            <button
              type="button"
              className="btn shrink-0"
              onClick={() => loadCurrentMut.mutate()}
              disabled={loadCurrentMut.isPending}
            >
              {loadCurrentMut.isPending ? "Загрузка…" : "Подгрузить"}
            </button>
          </div>
        )}

        {/* Сетки вариантов A / B / [C] / [D] */}
        <div
          className={`grid gap-4 ${
            form.variant_count <= 2
              ? "grid-cols-1 md:grid-cols-2"
              : form.variant_count === 3
                ? "grid-cols-1 md:grid-cols-3"
                : "grid-cols-1 md:grid-cols-2 lg:grid-cols-4"
          }`}
        >
          {variantLabels.map((label) => {
            const isA = label === "A";
            const useRemote = isA && currentPhotosA.length > 0;
            return (
              <div key={label} className="card bg-surface-2/30">
                <VariantPhotoGrid
                  label={label}
                  canEdit={true}
                  remotePhotos={useRemote ? currentPhotosA : undefined}
                  onRemoveRemote={
                    useRemote
                      ? (order) =>
                          order === "all"
                            ? setCurrentPhotosA([])
                            : setCurrentPhotosA((prev) =>
                                prev.filter((p) => p.order !== order),
                              )
                      : undefined
                  }
                  stagedFiles={useRemote ? [] : stagedPhotos[label] || []}
                  onStageFile={(o, f) => stageFile(label, o, f)}
                  onUnstageFile={(o) => unstageFile(label, o)}
                />
              </div>
            );
          })}
        </div>

        {/* Auto-elimination losers через 24 ч. Доступно только при 3+ вариантах
            (с 2-мя выкидывать некого). Показываем всегда чтобы фича была
            discoverable — при count=2 disabled + поясняем когда станет активно. */}
        <label
          className={`flex items-start gap-2 text-sm border rounded p-2 ${
            form.variant_count > 2
              ? "cursor-pointer border-border"
              : "opacity-60 cursor-not-allowed border-border"
          }`}
        >
          <input
            type="checkbox"
            checked={form.keep_leaders_after_24h && form.variant_count > 2}
            disabled={form.variant_count <= 2}
            onChange={(e) =>
              setForm({ ...form, keep_leaders_after_24h: e.target.checked })
            }
            className="mt-0.5"
          />
          <span>
            <span className="font-medium">
              ⏱ Авто-отсев через 24 ч — оставить топ-2 лидеров по CTR
            </span>
            <span className="block text-xs text-muted mt-0.5">
              {form.variant_count > 2
                ? `Через сутки после старта оставим 2 варианта с самым высоким CTR из ${form.variant_count}, остальные пометим «отсеян» и в ротации участвовать не будут. Tie-break: больше показов → буква вперёд.`
                : "Доступно при 3+ вариантах (нужно из чего отсевать). Увеличьте количество вариантов выше."}
            </span>
          </span>
        </label>
      </div>

      {createMut.error && (
        <div className="card text-warn text-sm">
          {(createMut.error as Error).message}
        </div>
      )}

      <div className="flex items-center gap-2 justify-end sticky bottom-0 bg-bg-1 py-2 -mx-4 px-4 border-t border-border">
        {uploadProgress && createMut.isPending && (
          <div className="text-xs text-muted mr-auto">
            Загрузка фото: {uploadProgress.done}/{uploadProgress.total}
          </div>
        )}
        {!uploadProgress && createMut.isPending && (
          <div className="text-xs text-muted mr-auto">Создание теста…</div>
        )}
        <button
          className="btn"
          onClick={() => history.back()}
          disabled={createMut.isPending}
        >
          Отмена
        </button>
        <button
          className="btn btn-primary"
          onClick={() => createMut.mutate()}
          disabled={createMut.isPending || !form.name || !form.nm_id}
        >
          {createMut.isPending ? "Создаём…" : "Создать черновик"}
        </button>
      </div>
    </div>
  );
}
