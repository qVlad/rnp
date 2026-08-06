/**
 * WMS «Свой склад» — адресное хранение (TASK-DEV-098, Фаза 1).
 *
 * Складов несколько и каждый работает независимо, поэтому склад выбирается в
 * шапке и прокидывается во все табы. Адресуется только зона отбора — товар
 * «на хранении» живёт без адреса.
 */
import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  WhCellEntry,
  WhStockGroupBy,
  WhWarehousePayload,
} from "../api/client";
import { DateRangePicker } from "../components/DateRangePicker";
import type { DateRange } from "../components/DateRangePicker";

type Tab =
  | "warehouses"
  | "map"
  | "receive"
  | "stock"
  | "barcodes"
  | "movements"
  | "cabinets";

const TABS: { key: Tab; label: string }[] = [
  { key: "warehouses", label: "Склады" },
  { key: "map", label: "Карта склада" },
  { key: "receive", label: "Приёмка" },
  { key: "stock", label: "Остатки и поиск" },
  { key: "barcodes", label: "Справочник ШК" },
  { key: "movements", label: "Движения" },
  { key: "cabinets", label: "Кабинеты WB" },
];

const GROUP_BY_LABELS: Record<WhStockGroupBy, string> = {
  barcode: "По баркоду",
  nm_id: "По артикулу (nmID)",
  cell: "По ячейке",
  box: "По коробу",
  brand: "По бренду",
  warehouse: "По складу",
};

function num(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("ru-RU");
}

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function Warehouse() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("warehouses");
  const [warehouseId, setWarehouseId] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const flash = (text: string) => {
    setErr(null);
    setMsg(text);
    setTimeout(() => setMsg(null), 6000);
  };
  const fail = (e: unknown) => {
    setMsg(null);
    setErr(e instanceof Error ? e.message : String(e));
  };

  const warehouses = useQuery({
    queryKey: ["wh-warehouses"],
    queryFn: () => api.whWarehouses(),
  });
  const status = useQuery({
    queryKey: ["wh-status"],
    queryFn: () => api.whStatus(),
  });

  // Первый склад выбирается автоматически — иначе все табы пустые
  const effectiveWarehouseId = useMemo(() => {
    if (warehouseId !== null) return warehouseId;
    return warehouses.data?.items[0]?.id ?? null;
  }, [warehouseId, warehouses.data]);

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["wh-status"] });
    qc.invalidateQueries({ queryKey: ["wh-warehouses"] });
    qc.invalidateQueries({ queryKey: ["wh-cells"] });
    qc.invalidateQueries({ queryKey: ["wh-stock"] });
    qc.invalidateQueries({ queryKey: ["wh-boxes"] });
    qc.invalidateQueries({ queryKey: ["wh-movements"] });
    qc.invalidateQueries({ queryKey: ["wh-barcode-ref"] });
  };

  const currentStatus = status.data?.warehouses.find(
    (w) => w.warehouse_id === effectiveWarehouseId,
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Свой склад (WMS)</h1>
          <p className="text-sm text-muted">
            Адресное хранение: ячейка = короб 60×40×40. Адресуется зона отбора,
            остальное — на хранении без адреса.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-muted">Склад</label>
          <select
            className="input"
            value={effectiveWarehouseId ?? ""}
            onChange={(e) =>
              setWarehouseId(e.target.value ? Number(e.target.value) : null)
            }
          >
            {(warehouses.data?.items ?? []).map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
                {w.is_active ? "" : " (неактивен)"}
              </option>
            ))}
            {!warehouses.data?.items.length && <option value="">— нет складов —</option>}
          </select>
        </div>
      </div>

      {/* Сводка по выбранному складу */}
      {currentStatus && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Tile label="Ячеек всего" value={num(currentStatus.cells_total)} />
          <Tile label="Свободно" value={num(currentStatus.cells_free)} />
          <Tile label="Занято" value={num(currentStatus.cells_occupied)} />
          <Tile
            label="Коробов"
            value={num(
              Object.values(currentStatus.boxes_by_status).reduce(
                (a, b) => a + b,
                0,
              ),
            )}
            hint={Object.entries(currentStatus.boxes_by_status)
              .map(([k, v]) => `${k}: ${v}`)
              .join(", ")}
          />
          <Tile label="Товара, шт" value={num(currentStatus.total_qty)} />
        </div>
      )}

      {msg && <div className="card border-success text-success text-sm">{msg}</div>}
      {err && <div className="card border-danger text-danger text-sm">{err}</div>}

      <div className="flex flex-wrap gap-1 border-b border-muted/30">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`px-3 py-2 text-sm ${
              tab === t.key
                ? "border-b-2 border-accent font-medium text-accent"
                : "text-muted"
            }`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "warehouses" && (
        <WarehousesTab onDone={(t) => (flash(t), refreshAll())} onError={fail} />
      )}
      {tab === "map" && effectiveWarehouseId && (
        <MapTab
          warehouseId={effectiveWarehouseId}
          onDone={(t) => (flash(t), refreshAll())}
          onError={fail}
        />
      )}
      {tab === "receive" && (
        <ReceiveTab
          warehouseId={effectiveWarehouseId}
          onDone={(t) => (flash(t), refreshAll())}
          onError={fail}
        />
      )}
      {tab === "stock" && <StockTab warehouseId={effectiveWarehouseId} />}
      {tab === "barcodes" && (
        <BarcodesTab onDone={(t) => (flash(t), refreshAll())} onError={fail} />
      )}
      {tab === "movements" && <MovementsTab warehouseId={effectiveWarehouseId} />}
      {tab === "cabinets" && (
        <CabinetsTab
          warehouseId={effectiveWarehouseId}
          onDone={(t) => (flash(t), refreshAll())}
          onError={fail}
        />
      )}

      {tab !== "warehouses" && !effectiveWarehouseId && (
        <div className="card text-sm text-muted">
          Сначала создайте склад на вкладке «Склады».
        </div>
      )}
    </div>
  );
}

function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card" title={hint}>
      <div className="text-xs text-muted">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

type Cb = { onDone: (text: string) => void; onError: (e: unknown) => void };

// ─────────────────────────────────────────────────────── Склады
function WarehousesTab({ onDone, onError }: Cb) {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["wh-warehouses"],
    queryFn: () => api.whWarehouses(),
  });
  const [form, setForm] = useState<WhWarehousePayload>({ name: "" });

  const create = useMutation({
    mutationFn: () => api.whCreateWarehouse(form),
    onSuccess: () => {
      setForm({ name: "" });
      qc.invalidateQueries({ queryKey: ["wh-warehouses"] });
      onDone("Склад создан");
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.whDeleteWarehouse(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wh-warehouses"] });
      onDone("Склад удалён");
    },
    onError,
  });

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="font-medium">Новый склад</div>
        <div className="grid gap-2 md:grid-cols-4">
          <input
            className="input"
            placeholder="Название (напр. Основной)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            className="input"
            placeholder="Код (напр. MSK)"
            value={form.code ?? ""}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
          />
          <input
            className="input md:col-span-2"
            placeholder="Адрес"
            value={form.address ?? ""}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
          />
        </div>
        <button
          className="btn btn-primary"
          disabled={!form.name.trim() || create.isPending}
          onClick={() => create.mutate()}
        >
          Создать склад
        </button>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1">Название</th>
              <th>Код</th>
              <th>Адрес</th>
              <th>Активен</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(list.data?.items ?? []).map((w) => (
              <tr key={w.id} className="border-t border-muted/20">
                <td className="py-1 font-medium">{w.name}</td>
                <td>{w.code ?? "—"}</td>
                <td>{w.address ?? "—"}</td>
                <td>{w.is_active ? "да" : "нет"}</td>
                <td className="text-right">
                  <button
                    className="btn text-danger"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Удалить склад «${w.name}»? Разрешено только если на нём нет коробов.`,
                        )
                      )
                        remove.mutate(w.id);
                    }}
                  >
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
            {!list.data?.items.length && (
              <tr>
                <td colSpan={5} className="py-3 text-muted">
                  Складов пока нет.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────── Карта склада
function MapTab({
  warehouseId,
  onDone,
  onError,
}: Cb & { warehouseId: number }) {
  const qc = useQueryClient();
  const [zone, setZone] = useState<string>("");
  const [occupied, setOccupied] = useState<"" | "yes" | "no">("");
  const [gen, setGen] = useState({ zone: "A", racks: 5, levels: 4, positions: 10 });
  const fileRef = useRef<HTMLInputElement>(null);

  const map = useQuery({
    queryKey: ["wh-cells", warehouseId, zone, occupied],
    queryFn: () =>
      api.whCells(warehouseId, {
        zone: zone || undefined,
        occupied: occupied === "" ? undefined : occupied === "yes",
      }),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["wh-cells"] });

  const generate = useMutation({
    mutationFn: () => api.whGenerateCells({ warehouse_id: warehouseId, ...gen }),
    onSuccess: (r) => {
      invalidate();
      onDone(
        `Создано ячеек: ${r.created} (уже было: ${r.skipped_existing} из ${r.total})`,
      );
    },
    onError,
  });
  const upload = useMutation({
    mutationFn: (file: File) => api.whUploadCells(file, warehouseId),
    onSuccess: (r) => {
      invalidate();
      onDone(
        `Ячейки загружены: создано ${r.created}, обновлено ${r.updated}` +
          (r.warnings.length ? ` · ${r.warnings.join("; ")}` : ""),
      );
    },
    onError,
  });
  const toStorage = useMutation({
    mutationFn: (boxCode: string) =>
      api.whToStorage({ box_code: boxCode, warehouse_id: warehouseId }),
    onSuccess: () => {
      invalidate();
      onDone("Короб убран на хранение, ячейка свободна");
    },
    onError,
  });

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="font-medium">Сетка ячеек</div>
        <p className="text-sm text-muted">
          Генератор избавляет от ручной набивки: 5 стеллажей × 4 яруса × 10
          позиций = 200 ячеек вида <code>A-01-01-01</code>. Либо загрузите файл
          формата «Склад | Код ячейки | Зона | Активна | Примечание».
        </p>
        <div className="grid gap-2 md:grid-cols-5">
          <input
            className="input"
            placeholder="Зона"
            value={gen.zone}
            onChange={(e) => setGen({ ...gen, zone: e.target.value })}
          />
          {(["racks", "levels", "positions"] as const).map((k) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <span className="text-muted">
                {k === "racks" ? "Стеллажей" : k === "levels" ? "Ярусов" : "Позиций"}
              </span>
              <input
                type="number"
                className="input"
                min={1}
                value={gen[k]}
                onChange={(e) => setGen({ ...gen, [k]: Number(e.target.value) })}
              />
            </label>
          ))}
          <button
            className="btn btn-primary"
            disabled={generate.isPending}
            onClick={() => generate.mutate()}
          >
            Сгенерировать
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload.mutate(f);
              e.target.value = "";
            }}
          />
          <button className="btn" onClick={() => fileRef.current?.click()}>
            Загрузить сетку из Excel
          </button>
          <a className="btn" href={api.whCellsExportUrl(warehouseId)}>
            ⬇ Выгрузить сетку
          </a>
        </div>
      </div>

      <div className="card space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="font-medium">
            Карта: {map.data?.stats.occupied ?? 0} занято /{" "}
            {map.data?.stats.free ?? 0} свободно из {map.data?.stats.cells_total ?? 0}
          </div>
          <select
            className="input"
            value={zone}
            onChange={(e) => setZone(e.target.value)}
          >
            <option value="">Все зоны</option>
            {(map.data?.stats.zones ?? []).map((z) => (
              <option key={z} value={z}>
                Зона {z}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={occupied}
            onChange={(e) => setOccupied(e.target.value as "" | "yes" | "no")}
          >
            <option value="">Все ячейки</option>
            <option value="yes">Только занятые</option>
            <option value="no">Только свободные</option>
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="py-1">Ячейка</th>
                <th>Зона</th>
                <th>Короб</th>
                <th>Тип</th>
                <th className="text-right">Шт</th>
                <th>Содержимое</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(map.data?.cells ?? []).map((c: WhCellEntry) => (
                <tr key={c.cell_id} className="border-t border-muted/20 align-top">
                  <td className="py-1 font-mono">{c.cell_code}</td>
                  <td>{c.zone ?? "—"}</td>
                  <td className="font-mono">{c.box?.box_code ?? "—"}</td>
                  <td>
                    {c.box ? (c.box.is_mono ? "моно" : "сборный") : "свободна"}
                  </td>
                  <td className="text-right">{num(c.box?.total_qty)}</td>
                  <td className="text-xs text-muted">
                    {c.box?.items
                      .map(
                        (i) =>
                          `${i.barcode}${i.size ? ` (${i.size})` : ""} × ${i.qty}`,
                      )
                      .join(", ") ?? ""}
                  </td>
                  <td className="text-right">
                    {c.box && (
                      <button
                        className="btn"
                        onClick={() => toStorage.mutate(c.box!.box_code)}
                      >
                        На хранение
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {!map.data?.cells.length && (
                <tr>
                  <td colSpan={7} className="py-3 text-muted">
                    Ячеек нет — сгенерируйте сетку выше.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────── Приёмка
function ReceiveTab({
  warehouseId,
  onDone,
  onError,
}: Cb & { warehouseId: number | null }) {
  const qc = useQueryClient();
  const [supplyRef, setSupplyRef] = useState("");
  const [result, setResult] = useState<Awaited<
    ReturnType<typeof api.whReceive>
  > | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [boxQuery, setBoxQuery] = useState("");

  const receive = useMutation({
    mutationFn: (file: File) =>
      api.whReceive(file, {
        warehouseId: warehouseId ?? undefined,
        supplyRef: supplyRef || undefined,
      }),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["wh-status"] });
      qc.invalidateQueries({ queryKey: ["wh-boxes"] });
      qc.invalidateQueries({ queryKey: ["wh-cells"] });
      onDone(
        `Принято: создано ${r.boxes_created}, обновлено ${r.boxes_updated}, ` +
          `размещено ${r.boxes_placed}, товара ${num(r.stats.total_qty)} шт`,
      );
    },
    onError,
  });

  const resetSupply = useMutation({
    mutationFn: () => api.whResetSupply(warehouseId!, supplyRef.trim()),
    onSuccess: (r) => {
      setResult(null);
      qc.invalidateQueries({ queryKey: ["wh-boxes"] });
      qc.invalidateQueries({ queryKey: ["wh-cells"] });
      qc.invalidateQueries({ queryKey: ["wh-status"] });
      onDone(`Поставка откатана: удалено коробов ${r.boxes_removed}`);
    },
    onError,
  });

  const deleteBox = useMutation({
    mutationFn: (boxCode: string) => api.whDeleteBox(boxCode, warehouseId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wh-boxes"] });
      qc.invalidateQueries({ queryKey: ["wh-cells"] });
      qc.invalidateQueries({ queryKey: ["wh-status"] });
      onDone("Короб удалён");
    },
    onError,
  });

  const boxes = useQuery({
    queryKey: ["wh-boxes", warehouseId, boxQuery],
    queryFn: () =>
      api.whBoxes({
        warehouseId: warehouseId ?? undefined,
        q: boxQuery || undefined,
        limit: 300,
      }),
    enabled: !!warehouseId,
  });

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="font-medium">Приёмка коробов из PackingList</div>
        <p className="text-sm text-muted">
          Файл поставщика загружается как есть — все коробы уйдут на хранение.
          Чтобы сразу расставить по ячейкам, добавьте в тот же файл две колонки
          слева: <b>Склад</b> и <b>Код ячейки</b> (код указывается в первой
          строке короба). Строка только с кодом ячейки создаёт пустую ячейку.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="input"
            placeholder="Номер / имя поставки (по умолчанию — имя файла)"
            value={supplyRef}
            onChange={(e) => setSupplyRef(e.target.value)}
          />
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) receive.mutate(f);
              e.target.value = "";
            }}
          />
          <button
            className="btn btn-primary"
            disabled={receive.isPending || !warehouseId}
            onClick={() => fileRef.current?.click()}
          >
            {receive.isPending ? "Загружаю…" : "Загрузить PackingList"}
          </button>
          <button
            className="btn text-danger"
            disabled={!warehouseId || !supplyRef.trim() || resetSupply.isPending}
            title="Удалить все коробы указанной поставки — если залили ошибочный файл"
            onClick={() => {
              if (
                window.confirm(
                  `Откатить приёмку «${supplyRef.trim()}» целиком? Коробы этой поставки будут удалены (журнал движений сохранится).`,
                )
              )
                resetSupply.mutate();
            }}
          >
            Откатить поставку
          </button>
        </div>
      </div>

      {result && (
        <div className="card space-y-2 text-sm">
          <div className="font-medium">Результат разбора файла</div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Tile label="Коробов" value={num(result.stats.boxes_total)} />
            <Tile
              label="Моно / сборных"
              value={`${num(result.stats.boxes_mono)} / ${num(result.stats.boxes_mixed)}`}
            />
            <Tile label="Уник. баркодов" value={num(result.stats.barcodes_unique)} />
            <Tile label="Товара, шт" value={num(result.stats.total_qty)} />
          </div>
          {result.stats.boxes_without_code > 0 && (
            <div className="text-warn">
              Коробов без ШК: {result.stats.boxes_without_code} — им присвоены
              коды <code>NOCODE-*</code>, нужно переклеить этикетки.
            </div>
          )}
          {result.stats.rows_dropped > 0 && (
            <div className="text-muted">
              Пропущено строк без баркода / с нулевым количеством:{" "}
              {result.stats.rows_dropped}
            </div>
          )}
          {result.cell_conflicts.length > 0 && (
            <div className="text-danger">
              Конфликты ячеек (уже заняты другим коробом):{" "}
              {result.cell_conflicts
                .map(
                  (c) => `${c.cell_code} занята ${c.occupied_by} → ${c.box_code}`,
                )
                .join("; ")}
            </div>
          )}
          {result.skipped_no_warehouse.length > 0 && (
            <div className="text-danger">
              Не удалось определить склад для {result.skipped_no_warehouse.length}{" "}
              коробов — выберите склад в шапке или добавьте колонку «Склад».
            </div>
          )}
          {result.warnings.map((w) => (
            <div key={w} className="text-warn">
              {w}
            </div>
          ))}
        </div>
      )}

      <div className="card space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="font-medium">Коробы на складе</div>
          <input
            className="input"
            placeholder="Поиск по ШК короба"
            value={boxQuery}
            onChange={(e) => setBoxQuery(e.target.value)}
          />
        </div>
        <div className="max-h-[28rem] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-bg">
              <tr className="text-left text-muted">
                <th className="py-1">№</th>
                <th>ШК короба</th>
                <th>Статус</th>
                <th>Ячейка</th>
                <th>Тип</th>
                <th className="text-right">Позиций</th>
                <th className="text-right">Шт</th>
                <th>Поставка</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(boxes.data?.items ?? []).map((b) => (
                <tr key={b.box_id} className="border-t border-muted/20">
                  <td className="py-1">{b.src_no ?? "—"}</td>
                  <td className="font-mono">{b.box_code}</td>
                  <td>{b.status_label}</td>
                  <td className="font-mono">{b.cell_code ?? "—"}</td>
                  <td>{b.is_mono ? "моно" : "сборный"}</td>
                  <td className="text-right">{num(b.positions)}</td>
                  <td className="text-right">{num(b.qty)}</td>
                  <td className="text-xs text-muted">{b.supply_ref ?? "—"}</td>
                  <td className="text-right">
                    <button
                      className="btn text-danger"
                      title="Удалить короб со склада"
                      onClick={() => {
                        if (window.confirm(`Удалить короб ${b.box_code}?`))
                          deleteBox.mutate(b.box_code);
                      }}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
              {!boxes.data?.items.length && (
                <tr>
                  <td colSpan={9} className="py-3 text-muted">
                    Коробов нет — загрузите PackingList.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────── Остатки и поиск
function StockTab({ warehouseId }: { warehouseId: number | null }) {
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [groupBy, setGroupBy] = useState<WhStockGroupBy>("barcode");

  const search = useQuery({
    queryKey: ["wh-search", submitted, warehouseId],
    queryFn: () => api.whSearch(submitted, warehouseId ?? undefined),
    enabled: submitted.length > 0,
  });
  const stock = useQuery({
    queryKey: ["wh-stock", warehouseId, groupBy],
    queryFn: () =>
      api.whStock({ warehouseId: warehouseId ?? undefined, groupBy }),
  });

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="font-medium">Быстрый поиск «где лежит»</div>
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(q.trim());
          }}
        >
          <input
            className="input flex-1"
            placeholder="Ячейка A-01-02-01 / ШК короба / баркод / nmID / артикул / название"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="btn btn-primary" type="submit">
            Найти
          </button>
        </form>
        {search.data && (
          <div className="space-y-2 text-sm">
            <div className="text-muted">
              Найдено строк: {search.data.items.length} · всего{" "}
              {num(search.data.total_qty)} шт
              {search.data.matched_as
                ? ` · распознано как: ${search.data.matched_as.join(", ")}`
                : ""}
              {search.data.truncated ? " · показаны первые 200" : ""}
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-bg">
                  <tr className="text-left text-muted">
                    <th className="py-1">Склад</th>
                    <th>Ячейка</th>
                    <th>Короб</th>
                    <th>Баркод</th>
                    <th>Размер</th>
                    <th>Артикул</th>
                    <th className="text-right">Шт</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {search.data.items.map((r, i) => (
                    <tr key={i} className="border-t border-muted/20">
                      <td className="py-1">{r.warehouse_name}</td>
                      <td className="font-mono">{r.cell_code ?? "хранение"}</td>
                      <td className="font-mono">{r.box_code}</td>
                      <td className="font-mono">{r.barcode}</td>
                      <td>{r.size ?? "—"}</td>
                      <td className="text-xs">
                        {r.vendor_code ?? r.name ?? (r.nm_id ? String(r.nm_id) : "—")}
                      </td>
                      <td className="text-right">{num(r.qty)}</td>
                      <td>{r.status_label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="card space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="font-medium">Остатки</div>
          <select
            className="input"
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as WhStockGroupBy)}
          >
            {(Object.keys(GROUP_BY_LABELS) as WhStockGroupBy[]).map((k) => (
              <option key={k} value={k}>
                {GROUP_BY_LABELS[k]}
              </option>
            ))}
          </select>
          <a
            className="btn"
            href={api.whStockExportUrl(warehouseId ?? undefined)}
          >
            ⬇ Выгрузить состояние (xlsx)
          </a>
          {stock.data && (
            <span className="text-sm text-muted">
              Итого {num(stock.data.totals.qty)} шт ·{" "}
              {num(stock.data.totals.barcodes)} баркодов ·{" "}
              {num(stock.data.totals.boxes)} коробов
            </span>
          )}
        </div>

        {stock.data && stock.data.by_warehouse.length > 1 && (
          <div className="flex flex-wrap gap-2 text-sm">
            {stock.data.by_warehouse.map((w) => (
              <span key={w.warehouse_id} className="card">
                {w.warehouse_name}: {num(w.qty)} шт / {num(w.boxes_count)} кор.
              </span>
            ))}
          </div>
        )}

        <div className="max-h-[32rem] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-bg">
              <tr className="text-left text-muted">
                {stock.data?.items[0] &&
                  Object.keys(stock.data.items[0]).map((k) => (
                    <th key={k} className="py-1">
                      {k}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {(stock.data?.items ?? []).map((row, i) => (
                <tr key={i} className="border-t border-muted/20">
                  {Object.values(row).map((v, j) => (
                    <td key={j} className="py-1">
                      {v === null || v === undefined
                        ? "—"
                        : typeof v === "boolean"
                          ? v
                            ? "да"
                            : "нет"
                          : typeof v === "number"
                            ? num(v)
                            : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
              {!stock.data?.items.length && (
                <tr>
                  <td className="py-3 text-muted">Остатков нет.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────── Справочник ШК
function BarcodesTab({ onDone, onError }: Cb) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [onlyUnresolved, setOnlyUnresolved] = useState(false);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  const list = useQuery({
    queryKey: ["wh-barcode-ref", q, onlyUnresolved],
    queryFn: () =>
      api.whBarcodeRef({ q: q || undefined, onlyUnresolved, limit: 300 }),
  });
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["wh-barcode-ref"] });

  const sync = useMutation({
    mutationFn: () => api.whSyncBarcodeRef(),
    onSuccess: (r) => {
      invalidate();
      onDone(
        `Из WB-данных: баркодов ${r.barcodes}, добавлено ${r.inserted}, обновлено ${r.updated}, пропущено ${r.skipped}`,
      );
    },
    onError,
  });
  const importOrder = useMutation({
    mutationFn: (f: File) => api.whImportOrderFile(f),
    onSuccess: (r) => {
      invalidate();
      onDone(
        `Из файла заказа: баркодов ${r.stats.barcodes} (с nmID ${r.stats.with_nm_id}), добавлено ${r.inserted}, обновлено ${r.updated}`,
      );
    },
    onError,
  });
  const save = useMutation({
    mutationFn: (barcode: string) =>
      api.whSaveBarcodeRef({
        barcode,
        nm_id: edit[`${barcode}:nm_id`]
          ? Number(edit[`${barcode}:nm_id`])
          : undefined,
        vendor_code: edit[`${barcode}:vendor_code`] || undefined,
        name: edit[`${barcode}:name`] || undefined,
      }),
    onSuccess: () => {
      invalidate();
      onDone("Справочник обновлён (ручная правка — высший приоритет)");
    },
    onError,
  });

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="font-medium">Справочник баркодов</div>
        <p className="text-sm text-muted">
          PackingList не содержит артикул и nmID — только баркод и размер.
          Справочник связывает их: приоритет источников{" "}
          <code>ручная правка → файл заказа → WB-данные → PackingList</code>,
          менее достоверный источник не затирает более достоверный.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="btn"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            Подтянуть из WB-данных
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importOrder.mutate(f);
              e.target.value = "";
            }}
          />
          <button className="btn" onClick={() => fileRef.current?.click()}>
            Импорт файла ЗАКАЗ
          </button>
          <input
            className="input"
            placeholder="Поиск: баркод / артикул / название"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={onlyUnresolved}
              onChange={(e) => setOnlyUnresolved(e.target.checked)}
            />
            только без nmID
          </label>
          {list.data && (
            <span className="text-sm text-muted">всего: {num(list.data.total)}</span>
          )}
        </div>
      </div>

      <div className="card max-h-[32rem] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-bg">
            <tr className="text-left text-muted">
              <th className="py-1">Баркод</th>
              <th>Размер</th>
              <th>nmID</th>
              <th>Артикул</th>
              <th>Название</th>
              <th>Источник</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(list.data?.items ?? []).map((r) => (
              <tr key={r.barcode} className="border-t border-muted/20">
                <td className="py-1 font-mono">{r.barcode}</td>
                <td>{r.size ?? "—"}</td>
                <td>
                  <input
                    className="input w-28"
                    defaultValue={r.nm_id ?? ""}
                    onChange={(e) =>
                      setEdit({ ...edit, [`${r.barcode}:nm_id`]: e.target.value })
                    }
                  />
                </td>
                <td>
                  <input
                    className="input w-32"
                    defaultValue={r.vendor_code ?? ""}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        [`${r.barcode}:vendor_code`]: e.target.value,
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    className="input w-48"
                    defaultValue={r.name ?? ""}
                    onChange={(e) =>
                      setEdit({ ...edit, [`${r.barcode}:name`]: e.target.value })
                    }
                  />
                </td>
                <td className="text-xs text-muted">{r.source}</td>
                <td className="text-right">
                  <button className="btn" onClick={() => save.mutate(r.barcode)}>
                    Сохранить
                  </button>
                </td>
              </tr>
            ))}
            {!list.data?.items.length && (
              <tr>
                <td colSpan={7} className="py-3 text-muted">
                  Справочник пуст — примите поставку или подтяните из WB.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────── Движения
function MovementsTab({ warehouseId }: { warehouseId: number | null }) {
  const [range, setRange] = useState({ from: isoDaysAgo(29), to: isoToday() });
  const [kind, setKind] = useState("");

  const data = useQuery({
    queryKey: ["wh-movements", warehouseId, range, kind],
    queryFn: () =>
      api.whMovements({
        warehouseId: warehouseId ?? undefined,
        from: range.from,
        to: range.to,
        kind: kind || undefined,
        limit: 500,
      }),
  });

  return (
    <div className="card space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="font-medium">Журнал движений</div>
        <DateRangePicker
          from={range.from}
          to={range.to}
          onChange={(r: DateRange) => setRange({ from: r.from, to: r.to })}
        />
        <select
          className="input"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="">Все операции</option>
          {(data.data?.kinds ?? []).map((k) => (
            <option key={k} value={k}>
              {data.data?.kind_labels[k] ?? k}
            </option>
          ))}
        </select>
        {data.data && (
          <span className="text-sm text-muted">всего: {num(data.data.total)}</span>
        )}
      </div>

      <div className="max-h-[32rem] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-bg">
            <tr className="text-left text-muted">
              <th className="py-1">Дата</th>
              <th>Операция</th>
              <th>Склад</th>
              <th>Короб</th>
              <th>Баркод</th>
              <th className="text-right">Шт</th>
              <th>Из ячейки</th>
              <th>В ячейку</th>
              <th>Кто</th>
            </tr>
          </thead>
          <tbody>
            {(data.data?.items ?? []).map((m) => (
              <tr key={m.id} className="border-t border-muted/20">
                <td className="py-1 whitespace-nowrap">
                  {m.dt ? m.dt.slice(0, 16).replace("T", " ") : "—"}
                </td>
                <td>{m.kind_label}</td>
                <td>{m.warehouse_name}</td>
                <td className="font-mono">{m.box_code ?? "—"}</td>
                <td className="font-mono">{m.barcode ?? "—"}</td>
                <td
                  className={`text-right ${
                    m.signed_qty < 0
                      ? "text-danger"
                      : m.signed_qty > 0
                        ? "text-success"
                        : "text-muted"
                  }`}
                >
                  {m.signed_qty === 0 ? "—" : num(m.signed_qty)}
                </td>
                <td className="font-mono">{m.cell_from ?? "—"}</td>
                <td className="font-mono">{m.cell_to ?? "—"}</td>
                <td className="text-xs text-muted">{m.actor ?? "—"}</td>
              </tr>
            ))}
            {!data.data?.items.length && (
              <tr>
                <td colSpan={9} className="py-3 text-muted">
                  Движений за период нет.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────── Кабинеты WB
function CabinetsTab({
  warehouseId,
  onDone,
  onError,
}: Cb & { warehouseId: number | null }) {
  const qc = useQueryClient();
  const links = useQuery({
    queryKey: ["wh-wb-links", warehouseId],
    queryFn: () => api.whWbLinks(warehouseId ?? undefined),
  });
  const cabinets = useQuery({
    queryKey: ["available-tenants"],
    queryFn: () => api.availableTenants(),
  });
  const [form, setForm] = useState({
    cabinet_tenant_id: 0,
    wb_warehouse_id: 0,
    wb_warehouse_name: "",
  });

  const create = useMutation({
    mutationFn: () =>
      api.whCreateWbLink({
        warehouse_id: warehouseId!,
        cabinet_tenant_id: form.cabinet_tenant_id,
        wb_warehouse_id: form.wb_warehouse_id,
        wb_warehouse_name: form.wb_warehouse_name || undefined,
      }),
    onSuccess: () => {
      setForm({ cabinet_tenant_id: 0, wb_warehouse_id: 0, wb_warehouse_name: "" });
      qc.invalidateQueries({ queryKey: ["wh-wb-links"] });
      onDone("Связка добавлена");
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.whDeleteWbLink(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wh-wb-links"] });
      onDone("Связка удалена");
    },
    onError,
  });

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="font-medium">Склад в кабинетах WB</div>
        <p className="text-sm text-muted">
          Один физический склад заведён в каждом кабинете как отдельный «склад
          продавца» со своим <code>warehouseId</code>. Эти связки нужны, чтобы
          отбор понимал, на какой ваш склад пришло FBS-задание (в{" "}
          <code>/api/v3/orders/new</code> приходит именно{" "}
          <code>warehouseId</code>). Отбор по FBS — следующий этап.
        </p>
        <div className="grid gap-2 md:grid-cols-4">
          <select
            className="input"
            value={form.cabinet_tenant_id || ""}
            onChange={(e) =>
              setForm({ ...form, cabinet_tenant_id: Number(e.target.value) })
            }
          >
            <option value="">— кабинет —</option>
            {(cabinets.data ?? []).map((t) => (
              <option key={t.tenant_id} value={t.tenant_id}>
                {t.name}
              </option>
            ))}
          </select>
          <input
            className="input"
            type="number"
            placeholder="warehouseId в WB"
            value={form.wb_warehouse_id || ""}
            onChange={(e) =>
              setForm({ ...form, wb_warehouse_id: Number(e.target.value) })
            }
          />
          <input
            className="input"
            placeholder="Название склада в WB"
            value={form.wb_warehouse_name}
            onChange={(e) =>
              setForm({ ...form, wb_warehouse_name: e.target.value })
            }
          />
          <button
            className="btn btn-primary"
            disabled={
              !warehouseId ||
              !form.cabinet_tenant_id ||
              !form.wb_warehouse_id ||
              create.isPending
            }
            onClick={() => create.mutate()}
          >
            Связать
          </button>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1">Наш склад</th>
              <th>Кабинет</th>
              <th>warehouseId в WB</th>
              <th>Название в WB</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(links.data?.items ?? []).map((l) => (
              <tr key={l.id} className="border-t border-muted/20">
                <td className="py-1">{l.warehouse_name}</td>
                <td>{l.cabinet_name ?? l.cabinet_tenant_id}</td>
                <td className="font-mono">{l.wb_warehouse_id}</td>
                <td>{l.wb_warehouse_name ?? "—"}</td>
                <td className="text-right">
                  <button
                    className="btn text-danger"
                    onClick={() => remove.mutate(l.id)}
                  >
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
            {!links.data?.items.length && (
              <tr>
                <td colSpan={5} className="py-3 text-muted">
                  Связок нет.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
