# Feedback review — TASK-DEV-062 «Глобальные фильтры» (2026-06-10)

**Owner:** Product Strategist + Lead + PM (синтез)
**Версия под review:** v0.64.26 → **v0.64.32** (Phase A фундамент + B провод на все аналит. страницы + C мульти-магазин «свод»)
**Деплой:** прод `rnp.sellerfriends.ru`, import-check ✅, build 58285ea.
**Источники feedback:**
- QA-review (correctness) — subagent, diff `1328db6..HEAD`, фокус на изоляции/RBAC/контрибуции.
- UX-review — subagent, фокус на discoverability/persistence/cascade/пустые состояния.
- Live-проверка (Claude-in-Chrome, аккаунт Talanov/Директор, кабинет ONYX): бар на Dashboard/PnL(3 вида)/ABC/Ads-heatmap, фильтр по бренду = parity, по артикулу = сужение 16.1M→2.46M, 0 console-errors.

---

## Сводка

- **Функционально корректно** для director/head + single-cabinet + brands/cat/grp/art фильтров (live-проверено + QA подтвердил пути изоляции/AppSetting/company_scope/empty-scope/threading).
- **2× P2-BUG (RBAC, проявляются у manager'а):** (1) кросс-tenant RBAC-leak в мульти-магазине; (2) ads-heatmap теряет brand-scope без активного фильтра.
- **2× P3-BUG:** COGS-map коллапс по nm_id в своде; неверный текст баннера P&L в своде для директора.
- **UX:** Группы не каскадятся; нет индикатора активного фильтра вне бара (Dashboard молча сужается); «Магазины·1» — silent no-op.
- **Phase C мульти-магазин рантаймом НЕ проверен** — тестовый аккаунт с одним кабинетом (дропдаун «Магазины» скрыт). Механизм валиден статически, но live-изоляция свода не воспроизведена.

---

## Классификация

### BUG (→ bugs-developer.md)

- **BUG-DEV-023 (P2, security):** кросс-tenant RBAC-leak в мульти-магазине. `resolve_store_scope` валидирует stores только по `user_tenant_access`, не пересекает с brand-RBAC. Эндпоинты `/dashboard`, `/units`, `/abc-analysis` — `current_brands_filter` (доступны manager'у). Manager с доступом к 2 кабинетам → `set_tenant_filter([A,B])` расширяет SELECT на оба, а `rbac_brands` взяты из brand_assignments **primary** tenant'а и матчатся по **имени бренда** в обоих → данные одноимённого бренда из tenant B, не назначенного manager'у в B, утекают в свод. **Фикс:** ограничить мульти-магазин ролью director/head ИЛИ пересекать store-scope с RBAC. (`filter_scope.py:resolve_store_scope`, `dashboard.py`/`units.py`/`analytics.py`.)
- **BUG-DEV-024 (P2):** `/ads/heatmap` теряет brand-RBAC без активного глоб-фильтра. `brands=Depends(current_brands_filter)` добавлен, но `nm_pred` строится только `if any([...])` → manager без фильтра видит ВСЕ кампании тенанта. **Фикс:** всегда резолвить nm-scope из `rbac_brands`, даже без выбранного измерения. (`ads.py:78-93`.)
- **BUG-DEV-025 (P3):** в своде `_latest_cogs_map` (и COGS-путь pnl_builder) дедупит по nm_id через `if nm in out: continue` — при `set_tenant_filter([A,B])` если nm_id есть в обоих кабинетах, COGS одного тенанта выигрывает недетерминированно, а выручка суммируется по обоим → неверная маржа/прибыль свода. Revenue/qty (`SUM GROUP BY nm_id`) сливаются корректно; ломается только COGS-map. Edge (нужен общий nm_id). (`metrics.py:_latest_cogs_map`.)
- **BUG-DEV-026 (P3):** баннер P&L в своде/brands-scope (`PnL.tsx:246`) пишет «P&L по своим брендам … попросите директора» — неверно/странно для директора, делающего мульти-магазин свод. **Фикс:** ветвить текст по multi-store vs manager-brands.

### TASK (→ tasks-developer.md, DEV-062 follow-ups)

- **TASK-DEV-063 (P2):** Группы не каскадятся по выбранным брендам. `/api/filters/options` строит групповой запрос без `sel_brands` (`filters.py:63-70`); `GlobalFilterBar` шлёт только `brands`. Категории/Артикулы сужаются, Группы — нет (полный org-wide список). Фикс: фильтровать группы через `ProductGroupAssignment→Product.brand`.
- **TASK-DEV-064 (P2):** Нет индикатора активного фильтра вне бара; persistence глобальный и молчаливый. На Dashboard вообще нет scope-баннера (в отличие от P&L) → KPI молча сужаются. Фикс: компактный чип «Фильтр активен: N брендов · M артикулов» рядом с баром / на Dashboard.
- **TASK-DEV-065 (P3):** «Магазины·1» — silent no-op (1 кабинет = fallback на активный, но кнопка accent-подсвечена как активный фильтр). Фикс: при 1 выбранном — либо переключать активный кабинет, либо inline-подсказка «выберите ≥2 для свода».
- **TASK-DEV-066 (P3):** Пустое состояние Ad-страниц при SKU-фильтре читается как «нет синка/периода», не «нет под фильтр». Фикс: при `active` добавлять «… по выбранному фильтру».
- **TASK-DEV-067 (P3):** by-brand хранит свой период (`localStorage pnl-by-brand.range.v1`) отдельно от глоб-периода → матрица может считаться за другой период, чем фильтр-бар наверху. Синхронизировать или подписать.

### Отброшено / не баг

- Изоляция writes, AppSetting (pitfall #16), company_scope→contribution-margin, empty-scope (`.in_(set())`→пусто), threading nm_ids/multi_store с defaults, RBAC-intersect в `get_pnl`, by-brand per-brand nm-intersect, `with_loader_criteria` closure — **проверены, корректны** (QA-subagent).
- Каскад категорий/артикулов по брендам — работает. Бар + refetch (filterKey в queryKey) на всех 8 страницах — работает.

---

## Решение по приоритетам

P2-BUG-023/024 — RBAC у manager'а (безопасность), фиксить в первую очередь. Остальные — плановые follow-up'ы. Phase C свод нужно проверить на реальном multi-cabinet аккаунте перед тем как считать его production-ready.
