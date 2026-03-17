# Логика решения 
import json
import traceback
from typing import Dict, List, Tuple, Optional, Any

# Глобальная переменная для хранения последнего отчёта
_last_report: str = ""

def _safe_get(data: Any, key: str, default: Any = None) -> Any:
    """Безопасное получение значения из словаря с проверкой типа."""
    if not isinstance(data, dict):
        return default
    return data.get(key, default)

def clean_data_keys(data: Any) -> Any:
    """
    Рекурсивная очистка ключей словаря от лишних пробелов.
    Обрабатывает вложенные словари и списки.
    """
    if data is None:
        return {}
    if not isinstance(data, (dict, list)):
        return data
    
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if not isinstance(key, str):
                continue  # Пропускаем нестроковые ключи
            clean_key = key.strip()
            cleaned[clean_key] = clean_data_keys(value)
        return cleaned
    elif isinstance(data, list):
        return [clean_data_keys(item) for item in data]
    return data

def _validate_number(value: Any, field_name: str, positive: bool = False) -> List[str]:
    """Валидация числового поля."""
    errors = []
    if value is None:
        errors.append(f"Поле '{field_name}' отсутствует.")
    elif not isinstance(value, (int, float)):
        errors.append(f"Поле '{field_name}' должно быть числом, получено: {type(value).__name__}")
    elif positive and value <= 0:
        errors.append(f"Поле '{field_name}' должно быть положительным, получено: {value}")
    return errors

def validate_data(data: Dict) -> Tuple[bool, List[str]]:
    """
    Комплексная валидация входных данных МДП.
    Возвращает (is_valid, list_of_errors).
    """
    errors = []
    
    # === Проверка типа корневых данных ===
    if not isinstance(data, dict):
        return False, ["Корневой элемент данных должен быть объектом JSON."]
    
    # === Обязательные поля ===
    N = _safe_get(data, 'N')
    M = _safe_get(data, 'M')
    
    errors.extend(_validate_number(N, 'N', positive=True))
    errors.extend(_validate_number(M, 'M', positive=True))
    
    if errors:
        return False, errors
    
    N, M = int(N), int(M)  # Приведение к целым после валидации
    
    # === Проверка массивов ===
    states = _safe_get(data, 'states', [])
    actions = _safe_get(data, 'actions', [])
    D = _safe_get(data, 'D', [])
    
    if not isinstance(states, list):
        errors.append("Поле 'states' должно быть массивом.")
    elif len(states) != N:
        errors.append(f"Количество состояний ({len(states)}) не совпадает с N ({N}).")
    
    if not isinstance(actions, list):
        errors.append("Поле 'actions' должно быть массивом.")
    elif len(actions) != M:
        errors.append(f"Количество действий ({len(actions)}) не совпадает с M ({M}).")
    
    if not isinstance(D, list):
        errors.append("Поле 'D' должно быть матрицей (массив массивов).")
    elif len(D) != N:
        errors.append(f"Количество строк в матрице D ({len(D)}) не совпадает с N ({N}).")
    else:
        for i, row in enumerate(D):
            if not isinstance(row, list):
                errors.append(f"Строка {i+1} матрицы D должна быть массивом.")
            elif len(row) != M:
                errors.append(f"Длина строки {i+1} матрицы D ({len(row)}) не равна M ({M}).")
            else:
                for j, val in enumerate(row):
                    if val not in (0, 1):
                        errors.append(f"Элемент D[{i+1}][{j+1}] должен быть 0 или 1, получено: {val}")
    
    # === Проверка chance_nodes ===
    chance_nodes = _safe_get(data, 'chance_nodes', [])
    if not isinstance(chance_nodes, list):
        errors.append("Поле 'chance_nodes' должно быть массивом.")
    else:
        nodes_map = {}
        for idx, node in enumerate(chance_nodes):
            prefix = f"Узел #{idx+1}"
            
            if not isinstance(node, dict):
                errors.append(f"{prefix}: должен быть объектом.")
                continue
            
            from_s = _safe_get(node, 'from S')
            action = _safe_get(node, 'action')
            
            # Валидация ключей узла
            if from_s is None:
                errors.append(f"{prefix}: отсутствует поле 'from S'.")
            elif not isinstance(from_s, int) or from_s < 1 or from_s > N:
                errors.append(f"{prefix}: 'from S' должен быть целым от 1 до N, получено: {from_s}")
            
            if action is None:
                errors.append(f"{prefix}: отсутствует поле 'action'.")
            elif not isinstance(action, int) or action < 1 or action > M:
                errors.append(f"{prefix}: 'action' должен быть целым от 1 до M, получено: {action}")
            
            if from_s is not None and action is not None:
                key = (int(from_s), int(action))
                if key in nodes_map:
                    errors.append(f"{prefix}: дублирование узла для состояния {key[0]} и действия {key[1]}.")
                nodes_map[key] = node
            
            # Валидация вероятностей и наград
            for field_name, field_key in [('вероятности', 'P'), ('награды', 'R'), ('след. состояния', 'to next S')]:
                values = _safe_get(node, field_key, [])
                if not isinstance(values, list):
                    errors.append(f"{prefix}: поле '{field_key}' должно быть массивом.")
            
            probs = _safe_get(node, 'P', [])
            rewards = _safe_get(node, 'R', [])
            next_states = _safe_get(node, 'to next S', [])
            
            if len(probs) != len(rewards) or len(rewards) != len(next_states):
                errors.append(f"{prefix}: массивы P, R и 'to next S' должны иметь одинаковую длину.")
            else:
                # Проверка сумм вероятностей
                if not all(isinstance(p, (int, float)) for p in probs):
                    errors.append(f"{prefix}: все вероятности в P должны быть числами.")
                elif probs and abs(sum(probs) - 1.0) > 0.001:
                    errors.append(f"{prefix}: сумма вероятностей = {sum(probs):.4f} (должно быть ~1.0)")
                
                # Проверка индексов следующих состояний
                for j in next_states:
                    if not isinstance(j, int) or j < 1 or j > N:
                        errors.append(f"{prefix}: некорректный индекс состояния {j} (должен быть 1..N).")
                
                # Проверка наград
                if not all(isinstance(r, (int, float)) for r in rewards):
                    errors.append(f"{prefix}: все награды в R должны быть числами.")
    
    return (len(errors) == 0), errors

class MDPSolver:
    """Решатель МДП методом обратной индукции для ациклических графов."""
    
    def __init__(self, data: Dict):
        self.data = data
        self.N = int(data['N'])
        self.M = int(data['M'])
        self.states = data.get('states', [f"s{i+1}" for i in range(self.N)])
        self.actions = data.get('actions', [f"a{i+1}" for i in range(self.M)])
        self.D = data['D']
        self.gamma = float(_safe_get(data, 'gamma', 1.0))
        self.K = int(_safe_get(data, 'K', self.N - 1))
        self.annotation = _safe_get(data, 'annotation', 'Задача МДП')
        
        # Индексация узлов: (state, action) -> node_data
        self.nodes: Dict[Tuple[int, int], Dict] = {}
        for n in _safe_get(data, 'chance_nodes', []):
            key = (int(n['from S']), int(n['action']))
            self.nodes[key] = n
        
        # Терминальные состояния: где все действия недоступны (D[i][*] == 0)
        self.terminal_states = [
            i+1 for i in range(self.N) 
            if all(val == 0 for val in self.D[i])
        ]

    def is_terminal(self, s: int) -> bool:
        """Проверка, является ли состояние терминальным."""
        return s in self.terminal_states

    def get_available_actions(self, s: int) -> List[int]:
        """Возвращает список доступных действий для состояния (1-индексация)."""
        if not (1 <= s <= self.N):
            return []
        return [a+1 for a in range(self.M) if self.D[s-1][a] == 1]

    def get_action_name(self, a: int) -> str:
        """Получение имени действия по индексу (1-индексация)."""
        if 1 <= a <= len(self.actions):
            return str(self.actions[a-1])
        return f"a{a}"

    def get_state_name(self, s: int) -> str:
        """Получение имени состояния по индексу (1-индексация)."""
        if 1 <= s <= len(self.states):
            return str(self.states[s-1])
        return f"s{s}"

    def Q(self, s: int, a: int, V: List[float]) -> float:
        """
        Вычисление Q-значения для состояния и действия.
        Возвращает -inf если узел не найден.
        """
        node = self.nodes.get((s, a))
        if not node:
            return float('-inf')
        
        q_val = 0.0
        probs = node.get('P', [])
        rewards = node.get('R', [])
        next_states = node.get('to next S', [])
        
        for p, r, j in zip(probs, rewards, next_states):
            # Валидация индекса следующего состояния
            if 1 <= j <= self.N:
                v_next = V[j-1]
            else:
                v_next = 0.0  # fallback для некорректных индексов
            q_val += p * (r + self.gamma * v_next)
        
        return q_val

    def _format_q_expression(self, s: int, a: int, V: List[float]) -> Tuple[Optional[str], float]:
        """Форматирование выражения q(s,a) для отчёта."""
        node = self.nodes.get((s, a))
        if not node:
            return None, float('-inf')
        
        terms = []
        q_val = 0.0
        
        for p, r, j in zip(node['P'], node['R'], node['to next S']):
            v_next = V[j-1] if 1 <= j <= self.N else 0.0
            r_display = int(r) if isinstance(r, (int, float)) and r == int(r) else r
            v_display = f"{v_next:.2f}"
            terms.append(f"{p}·({r_display}+{self.gamma}·{v_display})")
            q_val += p * (r + self.gamma * v_next)
        
        expr = '+'.join(terms) if terms else "0"
        return expr, q_val

    def solve_backward_induction(self) -> Tuple[List[float], List[Optional[int]], List[str]]:
        """
        Основной алгоритм обратной индукции.
        Возвращает: (V, policy, log_lines)
        """
        V = [0.0] * self.N  # Ценности состояний
        policy = [None] * self.N  # Оптимальные действия
        lines = []
        
        # Шаг 0: терминальные состояния
        lines.append("  ")
        lines.append("Шаг 0. Терминальные состояния")
        for s in self.terminal_states:
            lines.append(f"  v({self.get_state_name(s)}) = 0")
        lines.append("  ")
        
        # Обратная индукция по нетерминальным состояниям
        non_terminal = [s for s in range(1, self.N + 1) if not self.is_terminal(s)]
        
        for step, s in enumerate(reversed(non_terminal), 1):
            actions = self.get_available_actions(s)
            if not actions:
                continue  # Пропускаем состояния без действий
            
            state_name = self.get_state_name(s)
            q_values = {}
            
            lines.append(f"Шаг {step}. Состояние {state_name}")
            
            for a in actions:
                expr, q_val = self._format_q_expression(s, a, V)
                action_name = self.get_action_name(a)
                q_values[a] = q_val
                lines.append(f"  q({state_name}, {action_name}) = {expr} = {q_val:.4f}")
            
            # Выбор оптимального действия
            if q_values:
                best_action = max(q_values, key=q_values.get)
                V[s-1] = q_values[best_action]
                policy[s-1] = best_action
                
                lines.append(f"  v*({state_name}) = max = {V[s-1]:.4f}")
                lines.append(f"  π*({state_name}) = {self.get_action_name(best_action)}")
            lines.append("  ")
            
        return V, policy, lines

    def generate_report(self, V: List[float], policy: List[Optional[int]], 
                       calc_lines: List[str], filename: str = "data.json") -> str:
        """Генерация текстового отчёта с результатами."""
        lines = []
        
        # === ИСХОДНЫЕ ДАННЫЕ ===
        lines.append("=" * 80)
        lines.append("ИСХОДНЫЕ ДАННЫЕ")
        lines.append("=" * 80)
        lines.append(f"Источник: {filename}")
        lines.append("")
        lines.append("Параметры:")
        gamma_display = int(self.gamma) if self.gamma == int(self.gamma) else self.gamma
        lines.append(f"  Коэффициент дисконтирования: γ = {gamma_display}")
        lines.append(f"  Горизонт планирования: K = {self.K}")
        lines.append(f"  Количество состояний: N = {self.N}")
        lines.append(f"  Количество действий: M = {self.M}")
        lines.append(" ")
        
        # Состояния
        states_parts = [f"{i+1} - {self.get_state_name(i+1)}" for i in range(self.N)]
        lines.append(f"Состояния: {', '.join(states_parts)}")
        
        # Терминальные состояния
        if self.terminal_states:
            terminal_parts = [f"{s} - {self.get_state_name(s)}" for s in self.terminal_states]
            lines.append(f"Терминальные состояния: {', '.join(terminal_parts)}")
        else:
            lines.append("Терминальные состояния: —")
        lines.append(" ")
        
        # Действия
        actions_parts = [f"{i+1} - {self.get_action_name(i+1).capitalize()}" for i in range(self.M)]
        lines.append(f"Действия: {', '.join(actions_parts)}")
        lines.append(" ")
        
        # Матрица доступности действий
        lines.append("Матрица доступности действий:")
        for i in range(self.N):
            state_name = self.get_state_name(i+1)
            available = [self.get_action_name(j+1) for j, val in enumerate(self.D[i]) if val == 1]
            actions_str = ', '.join(available) if available else '—'
            lines.append(f"  {state_name}: [{actions_str}]")
        lines.append(" ")
        
        # Узлы переходов
        lines.append("Узлы переходов:")
        for idx, node in enumerate(_safe_get(self.data, 'chance_nodes', []), 1):
            from_s = node.get('from S')
            action = node.get('action')
            if from_s is None or action is None:
                continue
            state_name = self.get_state_name(from_s)
            action_name = self.get_action_name(action)
            next_names = [self.get_state_name(s) for s in node.get('to next S', [])]
            lines.append(f"  l={idx}: {state_name} + {action_name} → {{{', '.join(next_names)}}}")
            
            for k in range(len(node.get('P', []))):
                p = node['P'][k]
                r = node['R'][k]
                next_s = node['to next S'][k]
                r_display = int(r) if isinstance(r, (int, float)) and r == int(r) else r
                lines.append(f"      {p} | {r_display} → {self.get_state_name(next_s)}")
        lines.append(" ")
        
        # === РЕШЕНИЕ ===
        lines.append("=" * 80)
        lines.append("РЕШЕНИЕ МЕТОДОМ ОБРАТНОЙ ИНДУКЦИИ")
        lines.append("=" * 80)
        lines.extend(calc_lines)
        
        # === ОПТИМАЛЬНАЯ ПОЛИТИКА ===
        lines.append("=" * 80)
        lines.append("ОПТИМАЛЬНАЯ ПОЛИТИКА")
        lines.append("=" * 80)
        lines.append("-" * 60)
        lines.append(f"{'Состояние':<20} {'Действие':<20} {'Ценность':<15}")
        lines.append("-" * 60)
        
        for i in range(self.N):
            s = i + 1
            state_name = self.get_state_name(s)
            action_name = self.get_action_name(policy[i]) if policy[i] else "—"
            value = V[i]
            lines.append(f"{state_name:<20} {action_name:<20} {value:<15.4f}")
        
        lines.append("-" * 60)
        lines.append("=" * 80)
        lines.append(f"Значение ожидаемой ценности: V* = {V[0]:.4f}")
        lines.append("=" * 80)
        
        return '\n'.join(lines)

def run_calculation(file_content: str, filename: str = "data.json") -> str:
    """
    Точка входа для расчёта.
    Обрабатывает все ошибки и возвращает человекочитаемый результат.
    """
    global _last_report
    
    try:
        # 1. Парсинг JSON
        if not file_content or not isinstance(file_content, str):
            return "❌ ОШИБКА: Пустое или некорректное содержимое файла."
        
        raw_data = json.loads(file_content)
        
        # 2. Очистка и нормализация данных
        data = clean_data_keys(raw_data)
        
        # 3. Валидация
        is_valid, errors = validate_data(data)
        if not is_valid:
            return "❌ ОШИБКА В ДАННЫХ:\n" + "\n".join([f"  • {e}" for e in errors])
        
        # 4. Решение
        solver = MDPSolver(data)
        V, policy, calc_lines = solver.solve_backward_induction()
        
        # 5. Генерация отчёта
        report = solver.generate_report(V, policy, calc_lines, filename)
        _last_report = report
        return report
        
    except json.JSONDecodeError as e:
        return f"❌ ОШИБКА ПАРСИНГА JSON:\n  Строка {e.lineno}, колонка {e.colno}\n  {e.msg}"
    except KeyError as e:
        return f"❌ ОТСУТСТВУЕТ ОБЯЗАТЕЛЬНОЕ ПОЛЕ:\n  {e}"
    except (TypeError, ValueError) as e:
        return f"❌ ОШИБКА ТИПА ДАННЫХ:\n  {str(e)}"
    except Exception as e:
        # Ловим все непредвиденные ошибки с трассировкой
        tb = traceback.format_exc()
        return f"❌ НЕПРЕДВИДЕННАЯ ОШИБКА:\n{str(e)}\n\nТрассировка:\n{tb}"

def get_last_report() -> str:
    """Возвращает последний сгенерированный отчёт."""
    return _last_report
