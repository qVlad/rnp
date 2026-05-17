/**
 * Создание нового A/B теста — простая форма.
 * После создания → редирект на /abtest/:id (детали — там загружаем фото).
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  abtestApi,
  TrafficSource,
  TestMode,
  TriggerMode,
} from "@/api/abtest";

export default function AbTestNew() {
  const nav = useNavigate();
  const [form, setForm] = useState({
    name: "",
    nm_id: "",
    trigger_mode: "VIEWS" as TriggerMode,
    trigger_value: 1500,
    traffic_source: "ANY" as TrafficSource,
    test_mode: "PHOTO" as TestMode,
    campaign_id: "",
    min_sample_size: 1500,
    confidence_level: 0.95,
    keep_leaders_after_24h: false,
    budget_auto_topup: false,
    budget_min_threshold: 500,
    budget_topup_amount: 1000,
    budget_daily_limit: 10000,
    variant_labels: "A,B",
  });

  const createMut = useMutation({
    mutationFn: () =>
      abtestApi.create({
        name: form.name,
        nm_id: Number(form.nm_id),
        trigger_mode: form.trigger_mode,
        trigger_value: Number(form.trigger_value),
        traffic_source: form.traffic_source,
        test_mode: form.test_mode,
        campaign_id: form.campaign_id ? Number(form.campaign_id) : null,
        min_sample_size: Number(form.min_sample_size),
        confidence_level: Number(form.confidence_level),
        keep_leaders_after_24h: form.keep_leaders_after_24h,
        budget_auto_topup: form.budget_auto_topup,
        budget_min_threshold: Number(form.budget_min_threshold),
        budget_topup_amount: Number(form.budget_topup_amount),
        budget_daily_limit: Number(form.budget_daily_limit),
        variant_labels: form.variant_labels
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    onSuccess: (data) => nav(`/abtest/${data.id}`),
  });

  const needsAdvert =
    form.traffic_source === "ADV_ONLY" || form.traffic_source === "BOTH";

  return (
    <div className="space-y-4 max-w-3xl">
      <h1 className="text-2xl font-semibold">Новый A/B тест</h1>

      <div className="card space-y-3">
        <div>
          <label className="block text-sm text-muted mb-1">Название</label>
          <input
            className="input w-full"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Например: фото инфографика для X-100500"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-muted mb-1">nm_id WB</label>
            <input
              type="number"
              className="input w-full"
              value={form.nm_id}
              onChange={(e) => setForm({ ...form, nm_id: e.target.value })}
              placeholder="123456789"
            />
            <div className="text-xs text-muted mt-1">
              Карточка должна быть синхронизирована в products (через WB Content
              API sync).
            </div>
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Лейблы вариантов</label>
            <input
              className="input w-full font-mono"
              value={form.variant_labels}
              onChange={(e) =>
                setForm({ ...form, variant_labels: e.target.value })
              }
              placeholder="A,B"
            />
            <div className="text-xs text-muted mt-1">
              Через запятую, 2-8 шт. Фото загрузишь на странице теста.
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-sm text-muted mb-1">Триггер</label>
            <select
              className="input w-full"
              value={form.trigger_mode}
              onChange={(e) =>
                setForm({ ...form, trigger_mode: e.target.value as TriggerMode })
              }
            >
              <option value="VIEWS">VIEWS (показы)</option>
              <option value="TIME">TIME (минуты)</option>
              <option value="BUDGET">BUDGET (₽ потрачено)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Значение триггера</label>
            <input
              type="number"
              className="input w-full"
              value={form.trigger_value}
              onChange={(e) =>
                setForm({ ...form, trigger_value: Number(e.target.value) })
              }
            />
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Источник трафика</label>
            <select
              className="input w-full"
              value={form.traffic_source}
              onChange={(e) =>
                setForm({ ...form, traffic_source: e.target.value as TrafficSource })
              }
            >
              <option value="ANY">ANY (вся карточка)</option>
              <option value="ADV_ONLY">ADV_ONLY (только РК)</option>
              <option value="BOTH">BOTH (оба источника)</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-sm text-muted mb-1">Режим теста</label>
            <select
              className="input w-full"
              value={form.test_mode}
              onChange={(e) =>
                setForm({ ...form, test_mode: e.target.value as TestMode })
              }
            >
              <option value="PHOTO">PHOTO (только главное фото)</option>
              <option value="FUNNEL">FUNNEL (вся фото-воронка)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Мин. выборка</label>
            <input
              type="number"
              className="input w-full"
              value={form.min_sample_size}
              onChange={(e) =>
                setForm({ ...form, min_sample_size: Number(e.target.value) })
              }
            />
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Confidence</label>
            <input
              type="number"
              step={0.01}
              min={0.5}
              max={0.999}
              className="input w-full"
              value={form.confidence_level}
              onChange={(e) =>
                setForm({ ...form, confidence_level: Number(e.target.value) })
              }
            />
          </div>
        </div>

        {needsAdvert && (
          <div className="grid grid-cols-2 gap-3 border-t border-border-1 pt-3">
            <div>
              <label className="block text-sm text-muted mb-1">campaign_id WB</label>
              <input
                type="number"
                className="input w-full"
                value={form.campaign_id}
                onChange={(e) =>
                  setForm({ ...form, campaign_id: e.target.value })
                }
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
            {form.budget_auto_topup && (
              <>
                <div>
                  <label className="block text-sm text-muted mb-1">
                    Min остаток (₽)
                  </label>
                  <input
                    type="number"
                    className="input w-full"
                    value={form.budget_min_threshold}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        budget_min_threshold: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div>
                  <label className="block text-sm text-muted mb-1">
                    Сумма пополнения (₽)
                  </label>
                  <input
                    type="number"
                    className="input w-full"
                    value={form.budget_topup_amount}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        budget_topup_amount: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm text-muted mb-1">
                    Дневной лимит пополнений (₽)
                  </label>
                  <input
                    type="number"
                    className="input w-full"
                    value={form.budget_daily_limit}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        budget_daily_limit: Number(e.target.value),
                      })
                    }
                  />
                </div>
              </>
            )}
          </div>
        )}

        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.keep_leaders_after_24h}
              onChange={(e) =>
                setForm({ ...form, keep_leaders_after_24h: e.target.checked })
              }
            />
            Оставить топ-2 лидеров через 24 ч (для 3+ вариантов)
          </label>
        </div>

        {createMut.error && (
          <div className="text-warn text-sm">
            {(createMut.error as Error).message}
          </div>
        )}
        <div className="flex gap-2 justify-end">
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
            disabled={
              createMut.isPending ||
              !form.name ||
              !form.nm_id ||
              !form.variant_labels
            }
          >
            {createMut.isPending ? "Создаём…" : "Создать черновик"}
          </button>
        </div>
        <div className="text-xs text-muted">
          После создания: загрузите фото для каждого варианта на странице теста,
          затем нажмите «Запустить» — фото варианта A будет применено к карточке
          на WB.
        </div>
      </div>
    </div>
  );
}
