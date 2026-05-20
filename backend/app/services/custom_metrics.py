"""Custom metric templates — пользовательские формулы для KPI (TASK-DEV-011).

Юзер пишет формулу вроде `(revenue_net - ad_cost) / orders` с whitelisted
переменными из KPI Dashboard. Эвалюатор — чистый Python `ast` (без зависимостей)
с whitelist узлов:

    Number / Constant       — литералы (5, 3.14)
    Name                    — переменная из контекста
    BinOp                   — +, -, *, /, //, %, **
    UnaryOp                 — -x, +x
    Call                    — только abs, min, max, round, int, float (по whitelist)

Защита:
    * нет `eval`, нет `exec`, нет `__import__`
    * нет атрибут-доступа (a.b блокируется)
    * нет subscript (a[b] блокируется)
    * нет comprehension (для безопасности)

Это покрывает все типовые формулы юнит-экономики. Если потребуется условная
логика (ROI если COGS > 0 else 0), можно добавить IfExp узел отдельно.
"""
from __future__ import annotations

import ast
from typing import Any

# Безопасные функции — whitelist, всё остальное → SafeEvalError.
_SAFE_FUNCS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
}

# Разрешённые узлы AST. Всё что вне — SafeEvalError.
_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd,
    ast.Call,
)


class SafeEvalError(Exception):
    """Raised when formula contains disallowed constructs or unknown names."""


def safe_eval(formula: str, context: dict[str, Any]) -> float:
    """Безопасно эвалюировать формулу с подстановкой переменных из контекста.

    Возвращает float. Если формула некорректна или содержит запрещённые
    конструкции — SafeEvalError с человеческим сообщением.

    Деление на ноль возвращает 0.0 (а не Inf/NaN) — так в дашбордах
    меньше нулей и удобнее показывать «нет данных» вместо «∞».
    """
    if not formula or not formula.strip():
        raise SafeEvalError("Формула пуста")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise SafeEvalError(f"Синтаксическая ошибка: {e.msg}")

    # Walk + проверка whitelist
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise SafeEvalError(
                f"Запрещённая конструкция: {type(node).__name__}. "
                f"Допустимы только арифметика и функции "
                f"{', '.join(_SAFE_FUNCS.keys())}"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise SafeEvalError(
                    "Вызовы функций допустимы только по имени (без a.b())"
                )
            if node.func.id not in _SAFE_FUNCS:
                raise SafeEvalError(
                    f"Неизвестная функция: {node.func.id}. "
                    f"Доступны: {', '.join(_SAFE_FUNCS.keys())}"
                )

    # Найдём все имена переменных в формуле — проверим что есть в context
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in _SAFE_FUNCS:
            used_names.add(node.id)
    missing = used_names - set(context.keys())
    if missing:
        raise SafeEvalError(
            f"Неизвестные переменные: {', '.join(sorted(missing))}. "
            f"Доступные: {', '.join(sorted(context.keys()))}"
        )

    # Эвалюация — рекурсивный обход с подстановкой
    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise SafeEvalError("Допустимы только числовые литералы")
        if isinstance(node, ast.Name):
            if node.id in _SAFE_FUNCS:
                return _SAFE_FUNCS[node.id]
            return float(context.get(node.id) or 0)
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            try:
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0:
                        return 0.0
                    return left / right
                if isinstance(node.op, ast.FloorDiv):
                    if right == 0:
                        return 0.0
                    return left // right
                if isinstance(node.op, ast.Mod):
                    if right == 0:
                        return 0.0
                    return left % right
                if isinstance(node.op, ast.Pow):
                    return left ** right
            except (TypeError, ZeroDivisionError, OverflowError) as e:
                raise SafeEvalError(f"Ошибка арифметики: {e}")
        if isinstance(node, ast.Call):
            func = _SAFE_FUNCS[node.func.id]  # type: ignore[union-attr]
            args = [_eval(a) for a in node.args]
            try:
                return func(*args)
            except (TypeError, ValueError) as e:
                raise SafeEvalError(
                    f"Ошибка вызова {node.func.id}(...): {e}"  # type: ignore[union-attr]
                )
        raise SafeEvalError(f"Внутренняя ошибка: неизвестный узел {type(node).__name__}")

    result = _eval(tree)
    try:
        return float(result)
    except (TypeError, ValueError):
        raise SafeEvalError(f"Результат не число: {result!r}")


# Whitelist KPI keys которые доступны в формулах. Соответствуют ключам
# `metrics.compute_dashboard().kpis[i].key` — если фронт показывает KPI
# на Dashboard, юзер может на него ссылаться.
AVAILABLE_VARIABLES: dict[str, str] = {
    "revenue_gross": "Выручка gross (₽) — сумма заказов до возвратов",
    "revenue_net": "Поступления от WB (₽) — после WB-комиссии",
    "orders": "Заказы (шт) — активные за период",
    "returns": "Возвраты (шт)",
    "buyout_pct": "Выкуп (%)",
    "ad_cost": "Реклама (₽) — WB + внешний маркетинг",
    "drr_pct": "ДРР от заказов (%)",
    "drr_sales_pct": "ДРР от выкупов (%)",
    "margin": "Маржинальная прибыль (₽)",
    "margin_pct": "Маржа (%)",
    "roi_pct": "Рентабельность (%)",
    "commission_wb": "Комиссия WB (₽)",
    "logistics_wb": "Логистика WB (₽)",
    "storage_wb": "Хранение WB (₽)",
    "payout_to_account": "Выплата на р/с (₽)",
    "net_profit": "Чистая прибыль (₽)",
}


def extract_kpi_context(kpis: list[dict[str, Any]]) -> dict[str, float]:
    """Из массива KPI dashboard → плоский dict для safe_eval."""
    return {k.get("key"): float(k.get("value") or 0) for k in kpis if k.get("key")}
