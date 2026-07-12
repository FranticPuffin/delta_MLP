# 项目更新说明

> 本文档汇总近期对 DSN Delta-MILP 调度项目的所有更新，包括数据格式、算法逻辑、新增分析功能以及依赖包说明。

---

## 1. 数据格式更新

### 1.1 去除时段优先级
- 原 `mission` 级别的 `priority_schedule` 已移除。
- 改为在活动级别使用 `prior` 字段表示活动优先级（1-5，5 最高），与 `d_min`、`d_max` 同级。

### 1.2 活动级别新增 `prefer` 字段
每个 activity 新增 `prefer` 字段，表示该活动对天线类型的倾向策略：

| `prefer` 值 | 含义 | 算法作用 |
|------------|------|---------|
| `0` | 倾向中继星（Relay Satellite） | 优先选择 `antenna_type=0` 的视图窗口 |
| `1` | 倾向地面站（Ground Station） | 优先选择 `antenna_type=1` 的视图窗口 |
| `2` | 默认策略 | 不强制倾向，按默认规则选择 |

在 `Scripts/delta_core.py` 的 `_resolve_conflicts()` 中，`prefer` 已被强化为**硬性约束**：
- `prefer=0` 时只保留中继星候选；
- `prefer=1` 时只保留地面站候选；
- `prefer=2` 时保留全部候选；
- 若过滤后无候选，则回退到全部候选，避免活动完全不可调度。

### 1.3 视图周期新增 `antenna_type` 字段
每个 `view_period` 新增 `antenna_type` 字段，标识天线属性：

| `antenna_type` 值 | 含义 |
|------------------|------|
| `0` | 中继星（Relay Satellite） |
| `1` | 地面站（Ground Station） |

数据生成脚本 `Scripts/datapreprocess.py` 已同步更新，随机生成 `prefer` 与 `antenna_type`。

---

## 2. 新增功能：活动级天线共同覆盖时段分析

### 2.1 功能位置
在 `Scripts/delta_core.py` 的 `DeltaMILPScheduler` 类中新增 `_compute_activity_antenna_overlaps()` 方法，数据加载后自动调用。

### 2.2 输出说明
为每个 activity 生成 JSONL 记录，输出到 `Data/activity_antenna_overlap.jsonl`，格式如下：

```json
{
  "mission": "DAWN",
  "activity_id": "DAWN_ACT_03",
  "antenna_coverages": [],
  "overlap_periods": [
    {"start_hr": 143.79, "end_hr": 144.67, "antennas": ["DSS-12", "DSS-42"]},
    {"start_hr": 144.67, "end_hr": 149.44, "antennas": ["DSS-12", "DSS-31", "DSS-42"]},
    {"start_hr": 149.44, "end_hr": 153.64, "antennas": ["DSS-31", "DSS-42"]}
  ]
}
```

- `antenna_coverages`：固定输出空列表（按需求不输出单天线覆盖）。
- `overlap_periods`：仅输出**多个天线同时可见**的重叠时段，以及在该时段内可见的天线列表。
- 若无重叠时段，`overlap_periods` 为空列表。

### 2.3 算法实现
使用扫描线算法（Sweep Line）处理每个 activity 的所有视图周期：
1. 将每个视图周期的 `start_hr` 和 `end_hr` 拆为事件点；
2. 按时间顺序扫描，维护当前可见天线集合；
3. 相邻事件点之间若存在多个天线可见，则生成一个重叠时段；
4. 合并相邻且天线集合相同的连续区间。

---

## 3. HTTP API 接口更新

`Scripts/delta.py` 中新增接口：

### 3.1 POST `/api/delta/dsn-data/view-periods`
用于根据前端请求的时间窗口截断指定 mission/activity 的视图周期。

请求体格式：
```json
{
  "mission_id": "DSCO",
  "activities": [
    {"activity_id": "DSCO_ACT_00", "ask_view": {"start_hr": 30.02, "end_hr": 50.43}}
  ]
}
```

处理规则：
- 若 `view_period` 完全不在 `ask_view` 范围内，则删除；
- 若部分重叠，则截断 `start_hr` / `end_hr` 到 `ask_view` 边界。

---

## 4. 依赖包说明

当前项目依赖已全部列在 `requirements.txt` 中：

```text
pandas==2.2.3
numpy==1.26.4
matplotlib==3.10.0
PuLP==3.3.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.0.0
```

### 4.1 是否包含整个项目运行？
**是的，当前 `requirements.txt` 已包含项目完整运行所需的所有 Python 第三方库。**

- `pandas`、`numpy`、`matplotlib`：数据处理与可视化；
- `PuLP`：MILP 建模；
- `fastapi`、`uvicorn`、`pydantic`：HTTP API 服务；
- `PuLP` 内部会调用 GLPK 求解器，离线部署包中已包含 `glpk/glpsol.exe`。

### 4.2 新增外部库情况
本次更新（`prefer` / `antenna_type` / 重叠时段分析 / 视图周期截断接口）**未引入任何新的 Python 第三方库**，仅使用 Python 标准库（`json`、`os` 等）和已有依赖（`pandas`、`numpy` 等）。

### 4.3 离线部署注意
- 开发机重新运行 `package_offline.bat` 后，`requirements.txt` 中的依赖会被完整下载到 `packages/`；
- 目标机运行 `install.bat` 即可在无网络环境下完成安装。

---

## 5. 相关文件清单

| 文件 | 说明 |
|------|------|
| `Scripts/datapreprocess.py` | 数据生成，新增 `prefer` 与 `antenna_type` |
| `Scripts/delta_core.py` | 核心算法，新增 `_compute_activity_antenna_overlaps()`，强化 `prefer` 约束 |
| `Scripts/delta.py` | HTTP API，新增视图周期截断接口 |
| `Docs/Data.md` | 数据字段说明文档 |
| `Docs/time.md` | 输入数据修改与接口说明 |
| `Docs/Update.md` | 本文档 |
| `Data/activity_antenna_overlap.jsonl` | 活动级天线共同覆盖时段分析结果 |

---

## 6. 快速验证命令

### 6.1 验证天线共同覆盖分析
```cmd
python -c "import json; [print(json.dumps(json.loads(l), ensure_ascii=False)) for l in open('Data/activity_antenna_overlap.jsonl').readlines()[:5]]"
```

### 6.2 运行完整求解
```cmd
run_solver.bat
```

### 6.3 启动 API 服务
```cmd
run_delta_api.bat
```
