"""WMS «Свой склад» — адресное хранение (TASK-DEV-098).

Модули:
  - `packing_list.py` — парсер приёмки/размещения (формат B = PackingList + 2 колонки)
  - `cells.py`        — парсер сетки ячеек (формат A) + генератор + sort_order
  - `barcode_ref.py`  — справочник barcode → nm_id/размер/артикул
  - `stock.py`        — быстрый поиск «где лежит» + остатки
  - `movements.py`    — журнал движений (append-only)
  - `excel.py`        — выгрузки xlsx
"""
