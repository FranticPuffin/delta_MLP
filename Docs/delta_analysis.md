# Delta-MILP 调度算法 — 完整分析报告

> 基于 `Scripts/delta.py`（第 1–518 行），自底向上逐模块分析。

---

## 1. 系统总览

### 1.1 功能

在有限天线资源（40 台，利用率 70%）和时间窗口约束下，为多航天器任务（100 个）生成一周（168 小时，15 分钟粒度）的调度计划。算法来自论文 Δ-MILP（Delta Mixed-Integer Linear Programming）。

### 1.2 输入 / 输出

| 方向 | 格式 | 路径 | 说明 |
|------|------|------|------|
| 输入 | JSONL | `Data/dsn_data.jsonl` | 每行一个任务 JSON，含活动列表和视图窗口 |
| 输出(1) | TXT | `Outputs/optimization_log.txt` | 完整优化日志（stdout 重定向） |
| 输出(2) | CSV | `dsn_schedule.csv` | 调度表：Mission, Activity, Antenna, Start, End, Setup, Teardown, ViewEnd, Coverage |
| 输出(3) | PNG | `dsn_gantt_chart.png` | 甘特图：纵轴=任务，颜色=天线 |

---

## 2. 模块架构

```
delta.py (518 行)
├── 全局常量: PRIORITY_LEVELS (1-5)
├── 工具函数: set_ch_font()
├── 核心类: DeltaMILPScheduler
│   ├── __init__()          — 加载数据，设时间帧
│   ├── _load_data()        — 解析 JSONL
│   ├── _get_priority_at_time()     — 时间点优先级查询（旧版 priority_schedule 兼容）
│   ├── _get_activity_priority()    — 活动优先级读取/计算
│   ├── _resolve_conflicts()        — 冲突解决 & 天线选择
│   └── solve()             — MILP 建模求解
├── 可视化: visualize_and_save()
├── 日志类: Logger          — stdout 双写（终端 + 文件）
├── 主循环: run_dynamic_optimization()  — Algorithm 2 迭代
└── 入口: set_ch_font() → run_dynamic_optimization()
```

---

## 3. 模块详解

### 3.1 `DeltaMILPScheduler.__init__()`

```python
def __init__(self, data_path, total_horizon_hr=168, granularity_min=15):
```

- **T**：离散时间帧数 = `168 × 60 / 15 = 672`
- **gran**：粒度 = 15 分钟（当前代码中未实际用于 MILP 约束，仅作为预留参数）
- 调用 `_load_data()` 加载 JSONL

### 3.2 `_load_data()`（第 44–49 行）

逐行读取 JSONL，每行 `json.loads()` 解析为一个 dict，存入 `self.missions_data` 列表。

一个 mission 的数据结构：
```
{
  mission_id, total_requested_hr, base_priority,
  activities: [{
    activity_id, d_min, d_max, prior, setup_min, teardown_min, can_split,
    view_periods: [{antenna, start_hr, end_hr}, ...]
  }]
}
```

### 3.3 `_get_priority_at_time()`（第 51–57 行）

新版 `datapreprocess.py` 不再生成 `priority_schedule` 时段优先级；若旧数据仍包含 schedule，可按时间段兼容读取，否则返回 `base_priority`。

### 3.4 `_get_activity_priority()`（第 59–87 行）

新版数据在每个 activity 上直接提供活动优先级 `prior`，与 `d_min`、`d_max` 同级。调度时可优先读取 `activity["prior"]`；若旧数据缺少该字段，则回退到 `base_priority`。

**用途**：在 MILP 目标函数中作为 `priority²` 的基数，使高优先级活动获得更大的优化系数。

### 3.5 `solve()` — MILP 建模（第 196–298 行）

#### 步骤 1：定义变量（第 203–233 行）

对每个 activity 创建：
- **基础变量** `x[a_id]`：Binary，该活动是否调度
- **XOR 拆分子变量**（若 `can_split=True`）：`x[a_prime]`、`x[a_dprime]`，Binary
  - 约束 6k/6l：`x[a_prime] == x[a_dprime]`（成对）
  - 约束 6m：`x[a_id] + x[a_prime] <= 1`（互斥）

#### 步骤 2：目标函数 6a（第 235–246 行）

```
max Σ( iter_weight × priority² × (0.5 if split else 1.0) × x )
```

- `iter_weight`：来自外层动态权重迭代（Algorithm 2）
- `priority²`：1, 4, 9, 16, 25，使高优先级优势指数放大
- 拆分任务系数 ×0.5：防止拆分后权重翻倍

#### 步骤 3：资源容量约束 6i（第 248–256 行）

```
Σ( d_max × x ) ≤ 40 × 168 × 0.7 = 4704 小时
```

仅有一个全局容量约束。**简化点**：未在 MILP 中显式建模单天线时间互斥（6h）和任务不重叠（6j），这些改为后处理阶段由 `_resolve_conflicts()` 处理。

#### 步骤 4：求解（第 258–260 行）

使用 GLPK 命令行求解器，限时 60 秒：
```python
solver = pulp.GLPK_CMD(msg=1, options=['--tmlim', '60'])
```

#### 步骤 5：候选生成（第 262–286 行）

对 MILP 选中的每个 activity，为其每个 view_period 生成一个候选调度项，计算 `Coverage`（实际可追踪时长）：

```python
coverage = max(min(vp_end, vp_start + d_max) - vp_start, 0)
```

候选结构：`{Mission, Activity, Antenna, Start, End, ViewEnd, Coverage, Setup, Teardown}`

#### 步骤 6：冲突解决（第 288–289 行）

调用 `_resolve_conflicts(raw_candidates)`，详见 3.6。

#### 步骤 7：满意度计算（第 291–298 行）

```python
satisfaction[mission_id] = scheduled_hr / total_requested_hr
```

返回 `(satisfaction_dict, schedule_list)`。

### 3.6 `_resolve_conflicts()` — 冲突解决与天线选择（第 89–194 行）

这是 2024-06-15 最新优化的版本，核心变更：

#### 天线选择策略（新）

**旧逻辑**：按 (优先级 desc, 开始时间 asc) 排序所有候选，同一活动的第一个遇见的候选胜出 → 开始时间早但覆盖不全的天线可能胜出。

**新逻辑**：
1. **按活动分组**：同一活动的所有天线候选集中评估
2. **组内排序**（第 118–121 行）：
   - 主排序：`Coverage` 降序（覆盖更全面的天线优先）
   - 次排序：若天线已被同任务其他活动使用 → 优先复用（减少天线数）
3. **逐个尝试**：按排序依次尝试，首个无冲突的胜出；若全部冲突则舍弃该活动

#### 双冲突检查（第 148–160 行）

- **天线级冲突（6h）**：同一天线在同一时段只能服务一个活动（含 Setup/Teardown）
- **任务级冲突（6j）**：同一航天器不能同时占用两根天线

#### 输出统计（第 177–192 行）

- 舍弃活动数、被舍弃/保留活动的平均优先级
- 使用天线总数、每任务平均天线数

### 3.7 `visualize_and_save()`（第 300–361 行）

#### CSV 输出

将 schedule_list 直接写入 `dsn_schedule.csv`（含 Coverage 和 ViewEnd 字段）。

#### 甘特图（新设计）

| 维度 | 旧设计 | 新设计 |
|------|--------|--------|
| 纵轴 | 天线 (Antenna) | 任务 (Mission) |
| 颜色 | 任务 | 天线 |
| 标注 | 任务名 | 天线名 |
| 图例 | 任务 | 天线（标题："天线"） |

- 灰色半透明条 = Setup / Teardown
- 彩色条 = Tracking 时段
- `matplotlib.use('Agg')` 确保无显示器环境也能保存
- 保存后通过系统查看器自动打开（`os.startfile` / `open` / `xdg-open`）

### 3.8 `Logger`（第 368–382 行）

```python
class Logger(object):
    def write(self, message):
        self.terminal.write(message)  # 终端
        self.log.write(message)        # 文件
```

将所有 `print()` 输出同时写入终端和 `Outputs/optimization_log.txt`。

### 3.9 `run_dynamic_optimization()` — Algorithm 2（第 384–510 行）

#### 初始化（第 386–398 行）

```python
scheduler = DeltaMILPScheduler(data_path)
weights = {m_id: 1.0}     # 初始等权重
eta = 0.15                 # 满意度阈值 15%
eta_plus = 0.05            # 每次提升 5%
k_max = 10                 # 最多 10 次迭代
```

#### 迭代循环（第 412–435 行）

```
for k in 0..k_max-1:
    sats, schedule = scheduler.solve(weights, eta)
    记录 min_sat, avg_sat, 调度活动数
    for 每个任务:
        if 满意度 < eta:
            weights[任务] *= 2.0    # 权重翻倍
    if 无欠调度任务:
        eta += 0.05                 # 提升阈值
```

#### 最终求解与报告（第 437–510 行）

1. **最终满意度表**：每个任务的 基础优先级 | 峰值优先级 | 满意度 | 达标/欠调度
2. **优先级冲突分析**：按基础优先级分组统计平均满意度
3. **舍弃分析**：
   - 若有未达标任务 → 比较被舍弃 vs 保留任务的平均优先级
   - 若全部达标 → 比较低满意度 (<30%) vs 高满意度 (≥80%) 任务的平均优先级
4. **调度统计**：成功调度任务数/活动数、使用天线数
5. **调用可视化** → CSV + 甘特图

#### 输出目的地

所有 print 通过 `Logger` 双写至：
- **终端**（`sys.stdout.terminal`）
- **日志文件**（`Outputs/optimization_log.txt`）

---

## 4. 完整输出内容清单

### 4.1 控制台输出（按出现顺序）

```
============================================================
地面探测站航天器检测任务调度优化 - Delta-MILP 算法
任务总数: 100 | 初始阈值: 15% | 最大迭代次数: 10
============================================================

任务优先级分布:
  优先级 1 (低优先级(常规监测)): N 个任务
  优先级 2 (中低优先级(常规通信)): N 个任务
  ...

  [冲突解决] 舍弃 N 个低优先级活动，保留 N 个活动     ← 每次 solve() 输出一次
  被舍弃活动平均优先级: X.XX, 保留活动平均优先级: X.XX
  [天线统计] 共使用 N 根天线，每任务平均天线数: X.X    ← 新

[迭代 0]
- 最小满意度 (U_MIN): XX.X%
- 平均满意度 (U_AVG): XX.X%
- 调度活动数: N
> 状态: 发现 N 个欠调度任务，已提升权重。
> 欠调度任务列表: MIS-001, MIS-005...

  [冲突解决] ...
  [天线统计] ...

[迭代 1]
...

============================================================
优化完成。最终满意度指标：
============================================================
任务ID        基础优先级   峰值优先级      满意度     状态
------------------------------------------------------------
DAWN                  4          4      92.3%   ✓ 达标
JNO                   5          5      88.1%   ✓ 达标
...
------------------------------------------------------------
最小满意度: XX.X%
平均满意度: XX.X%
调度活动数: N

--- 优先级冲突分析 ---
    优先级    任务数    平均满意度                 说明
       1       20        85.2%   低优先级(常规监测)
       2       25        78.3%   中低优先级(常规通信)
...

被舍弃任务(N个)的平均优先级: X.X
保留任务(M个)的平均优先级: X.X
结论: 高优先级任务得到优先保留 ✓

--- 调度统计 ---
成功调度任务数: N/100
成功调度活动数: N
使用天线数: N
============================================================

详细调度表已保存至: dsn_schedule.csv
甘特图已保存至: dsn_gantt_chart.png
```

### 4.2 文件输出

| 文件 | 内容 | 编码 |
|------|------|------|
| `Outputs/optimization_log.txt` | 以上所有控制台输出的完整副本 | UTF-8 |
| `dsn_schedule.csv` | Mission, Activity, Antenna, Start, End, ViewEnd, Coverage, Setup, Teardown | UTF-8 |
| `dsn_gantt_chart.png` | 甘特图，DPI=150，figsize=(18,10) | PNG |

---

## 5. 约束映射

| 论文公式 | 约束名称 | 实现位置 | 实现方式 |
|----------|----------|----------|----------|
| 6a | 目标函数 | `solve()` 步骤 2 (L235–246) | MILP 目标：max Σ(w·p²·x) |
| 6b | 视图窗口限制 | `solve()` 步骤 5 (L262–286) | Coverage 计算隐含：超出 vp_end 的部分不计入 |
| 6h | 天线资源互斥 | `_resolve_conflicts()` (L148–153) | 后处理：天线时间线区间重叠检测 |
| 6i | 持续时间限制 | `solve()` 步骤 3 (L248–256) | 全局容量约束；d_min/d_max 由数据保证 |
| 6j | 任务不重叠 | `_resolve_conflicts()` (L155–160) | 后处理：任务时间线区间重叠检测 |
| 6k/6l | 拆分任务成对 | `solve()` 步骤 1 (L226–227) | MILP 约束：`x[prime] == x[dprime]` |
| 6m | 拆分互斥 | `solve()` 步骤 1 (L228–229) | MILP 约束：`x + x[prime] <= 1` |

> **设计决策**：天线互斥和任务互斥（6h/6j）未在 MILP 中建模（避免了 40×672 的二维变量矩阵），改为 MILP 选择活动 → 后处理贪心分配天线的两步策略。这以牺牲部分最优性换取求解速度。

---

## 6. 执行流程

```
python Scripts/delta.py
  │
  ├─ set_ch_font()           # 配置 matplotlib 中文字体
  │
  └─ run_dynamic_optimization()
       │
       ├─ Logger() 激活         # stdout 重定向开始
       │
       ├─ DeltaMILPScheduler(data_path)
       │    └─ _load_data()     # 读取 JSONL
       │
       ├─ 打印系统标题 + 优先级分布
       │
       ├─ for k in 0..9:        # Algorithm 2 迭代
       │    └─ scheduler.solve(weights, eta)
       │         ├─ PuLP 建模    # 变量 + 目标 + 约束
       │         ├─ GLPK 求解    # ≤60s
       │         ├─ 候选生成     # 含 Coverage 计算
       │         └─ _resolve_conflicts()  # 天线选择 + 冲突消除
       │              ├─ 按活动分组
       │              ├─ Coverage 排序 → 最佳天线优先
       │              ├─ 双冲突检查
       │              └─ 天线统计
       │
       ├─ scheduler.solve() ×1  # 最终求解
       │
       ├─ 打印最终满意度表
       ├─ 打印优先级冲突分析
       ├─ 打印调度统计
       │
       └─ visualize_and_save()
            ├─ CSV 写入
            ├─ 甘特图绘制 (matplotlib Agg)
            ├─ PNG 保存
            └─ 系统查看器打开
```

---

## 7. 已知简化与限制

| # | 简化点 | 位置 | 影响 |
|---|--------|------|------|
| 1 | 天线/任务互斥在 MILP 外处理 | `_resolve_conflicts()` vs MILP | 解可能非全局最优；次优天线被选中的概率降低（新 Coverage 排序缓解） |
| 2 | 仅全局容量约束 | `solve()` L256 | 未建模每根天线的独立容量 |
| 3 | `d_max` 固定为活动时长 | `solve()` L273 | 未让 MILP 在 [d_min, d_max] 范围内优化时长 |
| 4 | GLPK 60 秒限时 | `solve()` L259 | 大规模实例可能未收敛至最优 |
| 5 | 仅处理原始活动（拆分逻辑中只查 `x[a_id]`） | `solve()` L269 | 拆分子活动（`_prime`, `_dprime`）虽参与 MILP 但不在候选生成中，拆分实际未完全生效 |
| 6 | `granularity_min` 仅作为参数存储 | `__init__()` L41 | 时间离散化未实际用于约束建模 |
| 7 | Coverage 评分简化 | `solve()` L273–275 | 仅考虑单窗口的可追踪时长，未考虑跨窗口组合 |
| 8 | 拆分任务权重 ×0.5 | `solve()` L244 | 简单折半，未根据实际拆分比例动态调整 |
