import json
import pulp
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # 非交互后端，确保无显示器环境也能保存图片
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import platform
import os
import shutil
import subprocess
from matplotlib.font_manager import FontProperties

# 新增：标识符规范化辅助函数
# PuLP/GLPK 在变量名中使用非 ASCII 字符时，生成的 CPLEX LP 文件会
# 因编码问题导致 GLPK 无法解析。因此对所有 mission_id / activity_id
# 做内部 ASCII 编码，求解后再映射回原始中文名称。
import re as _re

_ID_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _encode_id(raw_id):
    """将任意字符串标识符编码为 GLPK/PuLP 安全的 ASCII 变量名。

    策略：
    - 仅包含 A-Z、a-z、0-9、下划线且不以数字开头的标识符保持不变。
    - 其他字符按 'u_' + ord(char) 串编码，解码可逆。
    """
    if isinstance(raw_id, str) and _ID_RE.match(raw_id):
        return raw_id
    if not isinstance(raw_id, str):
        raw_id = str(raw_id)
    return "u_" + "_".join(str(ord(c)) for c in raw_id)


def _decode_id(encoded_id):
    """将 _encode_id 编码后的 ASCII 名还原为原始标识符。"""
    if not isinstance(encoded_id, str):
        return str(encoded_id)
    if encoded_id.startswith("u_"):
        parts = encoded_id[2:].split("_")
        try:
            return "".join(chr(int(p)) for p in parts)
        except ValueError:
            return encoded_id
    return encoded_id


# 优先级等级定义 (1-5, 5为最高)
PRIORITY_LEVELS = {
    1: "低优先级(常规监测)",
    2: "中低优先级(常规通信)",
    3: "中优先级(科学数据下行)",
    4: "高优先级(关键事件/飞掠)",
    5: "最高优先级(紧急/不可重访)"
}

# --- GLPK solver path auto-detection (for offline deployment) ---
def _get_glpk_path():
    """Auto-detect the GLPK solver executable.

    Resolution order:
    1. Bundled: <project>/glpk/glpsol.exe (offline deployment)
    2. System PATH: glpsol.exe / glpsol (development convenience)
    3. Bare name: "glpsol" (let PuLP attempt PATH lookup)
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.normpath(os.path.join(script_dir, "..", "glpk", "glpsol.exe"))
    if os.path.isfile(bundled):
        return bundled
    found = shutil.which("glpsol.exe") or shutil.which("glpsol")
    if found:
        return found
    return "glpsol"

_GLPK_PATH = _get_glpk_path()


def set_ch_font():
    """配置 matplotlib 使用中文字体，保证甘特图标题/标签/任务名正常显示。"""
    system = platform.system()
    if system == "Windows":
        candidates = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    elif system == "Darwin":  # macOS
        candidates = ['Arial Unicode MS', 'PingFang SC', 'Heiti SC']
    else:  # Linux
        candidates = ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei',
                      'Noto Sans CJK SC', 'DejaVu Sans']

    # 查找实际可用的中文字体
    available_font = None
    for family in candidates:
        try:
            fp = FontProperties(family=family)
            # findfont 返回实际匹配的文件路径；fallback_to_default=True 会保证不抛错，
            # 因此需要额外检查返回字体是否属于候选字体族
            matched = matplotlib.font_manager.findfont(fp, fallback_to_default=True)
            # 若字体文件名包含候选名称的关键字，则认为可用（SimHei->simhei/simsun 等）
            lower_matched = os.path.basename(matched).lower()
            keywords = {
                'SimHei': ['simhei', 'simkai', 'simsun', '微软雅黑', 'microsoft yahei'],
                'Microsoft YaHei': ['yahei', 'microsoft yahei', 'msyh'],
                'Arial Unicode MS': ['arialunicodems', 'arial unicode'],
                'PingFang SC': ['pingfang'],
                'Heiti SC': ['heiti', 'stheiti'],
                'WenQuanYi Micro Hei': ['wqy-microhei', 'wenquanyi'],
                'WenQuanYi Zen Hei': ['wqy-zenhei', 'wenquanyi'],
                'Noto Sans CJK SC': ['noto sans cjk sc', 'noto'],
                'DejaVu Sans': ['dejavu'],
            }.get(family, [family.lower()])
            if any(kw in lower_matched for kw in keywords):
                available_font = family
                break
        except Exception:
            continue

    if available_font:
        plt.rcParams['font.sans-serif'] = [available_font] + [
            f for f in candidates if f != available_font
        ]
    else:
        # 未找到中文字体时，保留候选链，matplotlib 会回退到默认字体
        plt.rcParams['font.sans-serif'] = candidates

    # 防止中文字体生效后坐标轴负号变成方块
    plt.rcParams['axes.unicode_minus'] = False

# --- 算法实现核心类 ---
class DeltaMILPScheduler:
    def __init__(self, data_path, total_horizon_hr=168, granularity_min=15):
        self.data_path = data_path
        self.T = int(total_horizon_hr * 60 / granularity_min)  # 总时间帧数 (672) 
        self.gran = granularity_min
        self.missions_data = self._load_data()
        
    def _load_data(self):
        missions = []
        with open(self.data_path, 'r', encoding='utf-8') as f:
            for line in f:
                missions.append(json.loads(line))
        return missions

    def _compute_activity_antenna_overlaps(self, output_path=None):
        """
        针对每个任务(activity)计算所有天线的覆盖时段，以及多个天线共同可见的重叠时段。

        输出每个 activity 的结构：
        {
          "mission": 任务ID,
          "activity_id": 活动ID,
          "antenna_coverages": [ { "antenna", "antenna_type", "start_hr", "end_hr" } ],
          "overlap_periods": [ { "start_hr", "end_hr", "antennas": [...] } ]
        }
        """
        if output_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_path = os.path.join(script_dir, "..", "Data", "activity_antenna_overlap.jsonl")
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        results = []
        for mission in self.missions_data:
            m_id = mission.get("mission_id", "UNKNOWN")
            for act in mission.get("activities", []):
                a_id = act.get("activity_id", "UNKNOWN")
                view_periods = act.get("view_periods", [])

                # 1) 计算重叠时段：扫描线算法
                events = []
                for vp in view_periods:
                    events.append((vp["start_hr"], 1, vp["antenna"]))
                    events.append((vp["end_hr"], -1, vp["antenna"]))
                events.sort(key=lambda e: (e[0], -e[1]))  # 同一时刻先离开再进入，避免零长度区间

                active = set()
                overlap_periods = []
                prev_time = None
                for time, delta, antenna in events:
                    if prev_time is not None and time > prev_time and active:
                        overlap_periods.append({
                            "start_hr": prev_time,
                            "end_hr": time,
                            "antennas": sorted(active),
                        })
                    if delta == 1:
                        active.add(antenna)
                    else:
                        active.discard(antenna)
                    prev_time = time

                # 2) 合并相邻且可见天线集合相同的时段，并仅保留多天线可见的重叠部分
                merged = []
                for p in overlap_periods:
                    if merged and merged[-1]["antennas"] == p["antennas"] and abs(merged[-1]["end_hr"] - p["start_hr"]) < 1e-9:
                        merged[-1]["end_hr"] = p["end_hr"]
                    else:
                        merged.append(p)

                # 3) 只输出存在共同覆盖（至少两根天线可见）的时段；没有则输出空列表
                shared_periods = [p for p in merged if len(p["antennas"]) >= 2]

                results.append({
                    "mission": m_id,
                    "activity_id": a_id,
                    "antenna_coverages": [],
                    "overlap_periods": shared_periods,
                })

        with open(output_path, 'w', encoding='utf-8') as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        print(f"[天线共覆盖分析] 已生成 {len(results)} 条活动记录 -> {output_path}")
        return output_path, results

    def _get_priority_at_time(self, mission, time_hr):
        """获取任务在指定时间的优先级(1-5)"""
        pri_schedule = mission.get('priority_schedule', [])
        for seg in pri_schedule:
            if seg['start_hr'] <= time_hr < seg['end_hr']:
                return seg['priority']
        return mission.get('base_priority', 3)

    def _get_activity_priority(self, mission, act):
        """直接读取活动优先级 prior；缺省时回退到任务 base_priority。"""
        return act.get('prior', mission.get('base_priority', 3))

    def _resolve_conflicts(self, candidates):
        """
        冲突解决：当天线时间槽冲突时，优先保留高优先级任务，舍弃低优先级任务。
        天线选择策略：同一活动有多根天线可选时，按活动级 prefer 字段强制筛选对应类型的天线，
        同类型内优先选覆盖时长最长的天线（"看全程"），同一任务内尽量复用已选天线以减少天线使用数量。
        prefer 含义：0 倾向中继星、1 倾向地面站、2 默认策略（均可使用，无偏好）。
        注意：自本次更新起，prefer 由“排序偏好”强化为“硬性约束”；仅当约束导致无可用候选时才回退。
        """
        if not candidates:
            return []

        # 构建活动优先级映射：新版数据直接使用 activity["prior"]
        priority_map = {}
        # 构建活动天线策略倾向映射：prefer -> 0 中继星、1 地面站、2 默认
        prefer_map = {}
        for m in self.missions_data:
            for act in m['activities']:
                priority_map[act['activity_id']] = self._get_activity_priority(m, act)
                prefer_map[act['activity_id']] = act.get('prefer', 2)

        # 1. 按活动分组候选
        from collections import defaultdict
        by_activity = defaultdict(list)
        for c in candidates:
            by_activity[c['Activity']].append(c)

        # 2. 对各活动内的天线候选按 prefer 进行硬性过滤与排序：
        #    - prefer=0 时只保留 antenna_type=0（中继星）候选；
        #    - prefer=1 时只保留 antenna_type=1（地面站）候选；
        #    - prefer=2 时保留全部候选。
        #    若过滤后某活动无候选，则回退到全部候选，避免 prefer 策略导致活动完全不可调度。
        mission_antennas = defaultdict(set)  # mission -> 已使用的天线集合

        for act_key in by_activity:
            mission = by_activity[act_key][0]['Mission']
            prefer = prefer_map.get(act_key, 2)

            # --- 将 prefer 由排序偏好强化为硬性约束：过滤不符合类型要求的候选 ---
            filtered = []
            fallback = False
            if prefer == 0:
                filtered = [c for c in by_activity[act_key] if c.get('AntennaType', 1) == 0]
            elif prefer == 1:
                filtered = [c for c in by_activity[act_key] if c.get('AntennaType', 1) == 1]
            else:
                filtered = by_activity[act_key]

            # --- 回退机制：若硬性过滤后无候选，则保留原候选集合，避免活动被直接丢弃 ---
            if not filtered:
                filtered = by_activity[act_key]
                fallback = True

            def _candidate_sort_key(c):
                # 天线类型匹配：prefer=0 时中继星(antenna_type=0)排前；prefer=1 时地面站(antenna_type=1)排前；prefer=2 时无所谓
                antenna_type = c.get('AntennaType', 1)
                if prefer == 0:
                    type_match = 0 if antenna_type == 0 else 1
                elif prefer == 1:
                    type_match = 0 if antenna_type == 1 else 1
                else:
                    type_match = 0
                return (
                    type_match,                                  # 主排序：匹配 prefer 类型优先
                    -c['Coverage'],                              # 次排序：覆盖时长长 → 优先
                    0 if c['Antenna'] in mission_antennas[mission] else 1  # 第三排序：复用天线 → 优先
                )

            filtered.sort(key=_candidate_sort_key)
            by_activity[act_key] = filtered

        # 3. 按优先级降序排列活动（高优先级活动先分配资源），同优先级按开始时间升序
        def activity_sort_key(act_key):
            first = by_activity[act_key][0]
            return (-priority_map.get(act_key, 3), first['Start'])

        sorted_activities = sorted(by_activity.keys(), key=activity_sort_key)

        final_schedule = []
        antenna_timeline = {}   # antenna -> list of (start, end) 已占用区间
        mission_timeline = {}   # mission -> list of (start, end) 已占用区间

        dropped_count = 0
        dropped_by_priority = []  # 记录被舍弃的任务及优先级

        for act_key in sorted_activities:
            mission = by_activity[act_key][0]['Mission']
            scheduled = False

            # 按排序好的天线候选依次尝试（最佳天线优先）
            for item in by_activity[act_key]:
                antenna = item['Antenna']
                # 包含 setup 和 teardown 的完整占用区间
                item_start = item['Start'] - item['Setup']
                item_end = item['End'] + item['Teardown']

                # --- 检查天线级冲突 (Constraint 6h) ---
                antenna_conflict = False
                for (start, end) in antenna_timeline.get(antenna, []):
                    if item_start < end and start < item_end:
                        antenna_conflict = True
                        break

                # --- 检查任务级冲突 (Constraint 6j: 同一航天器不能同时占用两个天线) ---
                mission_conflict = False
                for (start, end) in mission_timeline.get(mission, []):
                    if item_start < end and start < item_end:
                        mission_conflict = True
                        break

                if not antenna_conflict and not mission_conflict:
                    # 无冲突，保留该活动
                    antenna_timeline.setdefault(antenna, []).append((item_start, item_end))
                    mission_timeline.setdefault(mission, []).append((item_start, item_end))
                    mission_antennas[mission].add(antenna)
                    final_schedule.append(item)
                    scheduled = True
                    break
                # 有冲突 → 继续尝试该活动的下一个天线候选

            if not scheduled:
                # 所有天线候选均冲突，舍弃该活动
                dropped_count += 1
                dropped_by_priority.append((mission, priority_map.get(act_key, 3)))

        if dropped_count > 0:
            avg_dropped_pri = sum(p for _, p in dropped_by_priority) / len(dropped_by_priority)
            kept_pri = [priority_map.get(item['Activity'], 3) for item in final_schedule]
            avg_kept_pri = sum(kept_pri) / len(kept_pri) if kept_pri else 0
            print(f"  [冲突解决] 舍弃 {dropped_count} 个低优先级活动，"
                  f"保留 {len(final_schedule)} 个活动")
            print(f"  被舍弃活动平均优先级: {avg_dropped_pri:.2f}, "
                  f"保留活动平均优先级: {avg_kept_pri:.2f}")

        # 统计天线复用情况
        total_antennas = set()
        for item in final_schedule:
            total_antennas.add(item['Antenna'])
        per_mission_antennas = {m_id: len(ants) for m_id, ants in mission_antennas.items()}
        avg_antennas = sum(per_mission_antennas.values()) / len(per_mission_antennas) if per_mission_antennas else 0
        print(f"  [天线统计] 共使用 {len(total_antennas)} 根天线，每任务平均天线数: {avg_antennas:.1f}")

        return final_schedule

    def solve(self, mission_weights, eta_threshold):
        """
        核心 MILP 求解逻辑 (Equation 6a-6m)
        集成优先级系统：高优先级任务在冲突时优先获得资源
        """
        # 为所有 mission / activity 建立中文<->ASCII 的双向映射
        mission_to_solver = {}
        solver_to_mission = {}
        activity_to_solver = {}
        solver_to_activity = {}

        for m in self.missions_data:
            mid = m['mission_id']
            mission_to_solver[mid] = _encode_id(mid)
            solver_to_mission[mission_to_solver[mid]] = mid
            for act in m['activities']:
                aid = act['activity_id']
                activity_to_solver[aid] = _encode_id(aid)
                solver_to_activity[activity_to_solver[aid]] = aid

        # 转换 mission_weights 的键为 solver 内部 ASCII 名
        solver_weights = {
            mission_to_solver.get(k, _encode_id(k)): v
            for k, v in mission_weights.items()
        }

        prob = pulp.LpProblem("Delta_MILP", pulp.LpMaximize)
        
        # 1. 定义变量
        x = {} 
        
        # 预处理任务拆分 (Algorithm 1)
        active_activities = []
        for m in self.missions_data:
            m_id = m['mission_id']
            solver_m_id = mission_to_solver[m_id]
            for act in m['activities']:
                a_id = act['activity_id']
                solver_a_id = activity_to_solver[a_id]
                
                # 基础变量（使用 ASCII 安全的 solver id）
                x[solver_a_id] = pulp.LpVariable(f"x_{solver_a_id}", cat='Binary')
                # 计算该活动的优先级权重
                act_priority = self._get_activity_priority(m, act)
                active_activities.append((solver_m_id, act, solver_a_id, False, act_priority))
                
                # XOR 拆分逻辑：如果满足拆分条件 (Algorithm 1)
                if act['can_split']:
                    a_prime = f"{solver_a_id}_prime"
                    a_dprime = f"{solver_a_id}_dprime"
                    x[a_prime] = pulp.LpVariable(f"x_{a_prime}", cat='Binary')
                    x[a_dprime] = pulp.LpVariable(f"x_{a_dprime}", cat='Binary')
                    
                    # 约束 6k, 6l: 子任务必须成对调度
                    prob += x[a_prime] == x[a_dprime]
                    # 约束 6m: 原始与拆分互斥
                    prob += x[solver_a_id] + x[a_prime] <= 1
                    
                    # 添加子活动到处理列表
                    active_activities.append((solver_m_id, act, a_prime, True, act_priority))
                    active_activities.append((solver_m_id, act, a_dprime, True, act_priority))

        # 2. 目标函数 (Equation 6a)
        # 权重 = 迭代权重 × 优先级权重
        # 优先级高的活动在目标函数中系数更大，冲突时求解器会优先保留
        obj_elements = []
        for m_id, act, a_name, is_split, act_priority in active_activities:
            iter_weight = solver_weights.get(m_id, 1.0)
            # 优先级权重: priority^2 使高优先级优势更明显
            priority_weight = act_priority ** 2  # 1,4,9,16,25
            # 如果是拆分任务，权重减半
            coeff = iter_weight * priority_weight * (0.5 if is_split else 1.0)
            obj_elements.append(coeff * x[a_name])
        prob += pulp.lpSum(obj_elements)

        # 3. 物理约束
        # 约束 6i: 持续时间限制
        total_resource_usage = []
        for m_id, act, a_name, is_split, act_priority in active_activities:
            dur = act['d_max'] / 2 if is_split else act['d_max']
            total_resource_usage.append(dur * x[a_name])
        
        # 总天线资源容量约束
        prob += pulp.lpSum(total_resource_usage) <= 40 * 168 * 0.7  # 40台天线, 70%利用率

        # 4. 执行求解 - 使用GLPK并设置时间限制
        solver = pulp.GLPK_CMD(msg=1, options=['--tmlim', '60'], path=_GLPK_PATH)  # 每次求解最多60秒
        prob.solve(solver) 
        
        # 5. 生成候选调度结果（为每个已调度活动生成所有可选视图窗口的候选）
        raw_candidates = []
        for m in self.missions_data:
            m_id = m['mission_id']
            solver_m_id = mission_to_solver[m_id]
            for act in m['activities']:
                a_id = act['activity_id']
                solver_a_id = activity_to_solver[a_id]
                # 检查是否被选中
                if pulp.value(x[solver_a_id]) is not None and pulp.value(x[solver_a_id]) > 0.5:
                    # 为该活动的每个视图窗口生成候选
                    for vp in act['view_periods']:
                        # 计算该天线窗口能实际覆盖的时长
                        desired_end = vp['start_hr'] + act['d_max']
                        trackable_end = min(vp['end_hr'], desired_end)
                        coverage = max(trackable_end - vp['start_hr'], 0)
                        raw_candidates.append({
                            "Mission": m_id,
                            "Activity": a_id,
                            "Antenna": vp['antenna'],
                            "AntennaType": vp.get('antenna_type', 1),  # 0 中继星, 1 地面站
                            "Start": vp['start_hr'],
                            "End": desired_end,
                            "ViewEnd": vp['end_hr'],
                            "Coverage": coverage,  # 该天线实际可追踪时长
                            "Setup": act['setup_min'] / 60,
                            "Teardown": act['teardown_min'] / 60
                        })

        # 6. 冲突解决：优先保留高优先级，舍弃低优先级
        schedule_results = self._resolve_conflicts(raw_candidates)

        # 7. 计算满意度结果
        satisfaction = {}
        for m in self.missions_data:
            m_id = m['mission_id']
            scheduled_hr = sum(r['End'] - r['Start'] for r in schedule_results if r['Mission'] == m_id)
            satisfaction[m_id] = scheduled_hr / m['total_requested_hr'] if m['total_requested_hr'] > 0 else 0

        return satisfaction, schedule_results

def visualize_and_save(schedule_list, filename="dsn_schedule.csv"):
    if not schedule_list:
        print("没有可生成的调度数据。")
        return

    # 1. 保存为 CSV
    df = pd.DataFrame(schedule_list)
    df.to_csv(filename, index=False)
    print(f"详细调度表已保存至: {filename}")

    # 2. 绘制甘特图 — 纵轴为任务(Mission)，颜色表示天线(Antenna)
    plt.figure(figsize=(18, 10))
    missions = sorted(df['Mission'].unique())
    antennas = sorted(df['Antenna'].unique())
    colors = plt.cm.tab20(np.linspace(0, 1, len(antennas)))
    color_map = dict(zip(antennas, colors))

    for i, row in df.iterrows():
        mission_idx = missions.index(row['Mission'])

        # 绘制准备时间 (Setup) - 灰色
        plt.barh(mission_idx, row['Setup'], left=row['Start'] - row['Setup'],
                 color='lightgrey', edgecolor='gray', alpha=0.5)

        # 绘制跟踪时间 (Tracking) - 天线颜色
        plt.barh(mission_idx, row['End'] - row['Start'], left=row['Start'],
                 color=color_map[row['Antenna']], edgecolor='black', label=row['Antenna'])

        # 绘制拆除时间 (Teardown) - 灰色
        plt.barh(mission_idx, row['Teardown'], left=row['End'],
                 color='lightgrey', edgecolor='gray', alpha=0.5)

        # 标注天线名
        plt.text(row['Start'], mission_idx, row['Antenna'], va='center', ha='left', fontsize=6)

    plt.yticks(range(len(missions)), missions, fontsize=7)
    plt.xlabel("时间 (小时, 从周一 00:00 开始)")
    plt.title("地面探测站航天器检测任务调度甘特图 (Delta-MILP 优先级调度)")
    plt.grid(axis='x', linestyle='--', alpha=0.7)

    # 防止图例重复
    handles, labels = plt.gca().get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    plt.legend(by_label.values(), by_label.keys(), loc='upper right',
               bbox_to_anchor=(1.15, 1), fontsize=7, title="天线")
    
    plt.tight_layout()
    img_path = "dsn_gantt_chart.png"
    plt.savefig(img_path, dpi=150)
    plt.close()
    print(f"甘特图已保存至: {img_path}")

    # 使用系统默认图片查看器打开 (仅在直接命令行运行时；通过 API 调用时禁用)
    if os.environ.get("DELTA_OPEN_VIEWER", "0") == "1":
        try:
            if platform.system() == "Windows":
                os.startfile(img_path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", img_path])
            else:
                subprocess.Popen(["xdg-open", img_path])
        except Exception as e:
            print(f"无法自动打开图片查看器: {e}")

# --- 3. 动态权重迭代逻辑 (Algorithm 2) ---
import sys
import numpy as np

# --- 新增：日志记录类 ---
class Logger(object):
    def __init__(self, filename=None):
        if filename is None:
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            filename = os.path.join(script_dir, "..", "Outputs", "optimization_log.txt")
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding="utf-8")

    def write(self, message):
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            # Windows GBK console can't handle ✓/✗ — replace with ASCII
            import re
            safe = message.replace('✓', '[OK]').replace('✗', '[XX]')
            self.terminal.write(safe)
        self.log.write(message)

    def flush(self):
        pass

def _default_data_path():
    """Return the default JSONL input path bundled with the project."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "..", "Data", "dsn_data.jsonl")


def run_dynamic_optimization(data_path=None,
                             eta=0.15,
                             eta_plus=0.05,
                             k_max=10,
                             output_csv="dsn_schedule.csv",
                             redirect_stdout_to_log=True,
                             open_viewer=False):
    """运行 Delta-MILP 动态权重优化流程。

    可被外部直接调用 (例如 FastAPI 的 /api/delta/call/run_dynamic_optimization)，
    亦可在脚本以 ``__main__`` 直接运行时启动。

    返回:
        dict: 结构化结果，包含每个任务的满意度、最终调度列表、统计信息等。
    """
    # 将标准输出重定向至文件 (可选)
    original_stdout = sys.stdout
    logger_obj = None
    if redirect_stdout_to_log:
        logger_obj = Logger()
        sys.stdout = logger_obj

    # 控制是否打开图片查看器（API 模式必须为 False）
    os.environ["DELTA_OPEN_VIEWER"] = "1" if open_viewer else "0"

    if data_path is None:
        data_path = _default_data_path()

    try:
        scheduler = DeltaMILPScheduler(data_path)
        scheduler._compute_activity_antenna_overlaps()
        mission_ids = [m['mission_id'] for m in scheduler.missions_data]
        weights = {m_id: 1.0 for m_id in mission_ids}

        print("="*60)
        print(f"地面探测站航天器检测任务调度优化 - Delta-MILP 算法")
        print(f"任务总数: {len(mission_ids)} | 初始阈值: {eta*100}% | 最大迭代次数: {k_max}")
        print("="*60)

        # 打印优先级分布
        pri_dist = {}
        for m in scheduler.missions_data:
            bp = m.get('base_priority', 3)
            pri_dist[bp] = pri_dist.get(bp, 0) + 1
        print(f"\n任务优先级分布:")
        for pri in sorted(pri_dist.keys()):
            desc = PRIORITY_LEVELS.get(pri, "")
            print(f"  优先级 {pri} ({desc}): {pri_dist[pri]} 个任务")
        print()

        final_schedule = None
        for k in range(k_max):
            sats, schedule = scheduler.solve(weights, eta)
            if k == k_max - 1:
                final_schedule = schedule
            min_sat = min(sats.values())
            avg_sat = float(np.mean(list(sats.values())))

            print(f"\n[迭代 {k}]")
            print(f"- 最小满意度 (U_MIN): {min_sat:.2%}")
            print(f"- 平均满意度 (U_AVG): {avg_sat:.2%}")
            print(f"- 调度活动数: {len(schedule)}")

            under_satisfied = []
            for m_id, sat_val in sats.items():
                if sat_val < eta:
                    weights[m_id] *= 2.0
                    under_satisfied.append(m_id)

            if not under_satisfied:
                print(f"> 状态: 所有任务达到阈值 {eta*100:.1f}%, 提升阈值。")
                eta += eta_plus
            else:
                print(f"> 状态: 发现 {len(under_satisfied)} 个欠调度任务，已提升权重。")
                print(f"> 欠调度任务列表: {', '.join(under_satisfied[:5])}...")

        # 获取最终调度结果
        final_sats, final_schedule = scheduler.solve(weights, eta)

        # 构建任务优先级映射：新版数据的峰值优先级来自 activities[*]["prior"]
        mission_priorities = {}
        for m in scheduler.missions_data:
            m_id = m['mission_id']
            base_pri = m.get('base_priority', 3)
            max_pri = max(
                (act.get('prior', base_pri) for act in m.get('activities', [])),
                default=base_pri,
            )
            mission_priorities[m_id] = (base_pri, max_pri)

        print("\n" + "="*60)
        print("优化完成。最终满意度指标：")
        print("="*60)
        print(f"{'任务ID':<12} {'基础优先级':>10} {'峰值优先级':>10} {'满意度':>10} {'状态':>8}")
        print("-"*60)
        for m_id, sat_val in sorted(final_sats.items()):
            base_pri, max_pri = mission_priorities.get(m_id, (3, 3))
            status = "✓ 达标" if sat_val >= eta else "✗ 欠调度"
            print(f"{m_id:<12} {base_pri:>10} {max_pri:>10} {sat_val:>9.1%} {status:>8}")
        print("-"*60)
        print(f"最小满意度: {min(final_sats.values()):.1%}")
        print(f"平均满意度: {np.mean(list(final_sats.values())):.1%}")
        print(f"调度活动数: {len(final_schedule)}")

        # 优先级-满意度相关性分析
        print(f"\n--- 优先级冲突分析 ---")
        pri_groups = {}
        for m_id, sat_val in final_sats.items():
            base_pri = mission_priorities.get(m_id, (3, 3))[0]
            pri_groups.setdefault(base_pri, []).append(sat_val)

        print(f"{'优先级':>8} {'任务数':>6} {'平均满意度':>10} {'说明':>20}")
        for pri in sorted(pri_groups.keys()):
            sats_list = pri_groups[pri]
            desc = PRIORITY_LEVELS.get(pri, "")
            print(f"{pri:>8} {len(sats_list):>6} {np.mean(sats_list):>10.1%} {desc:>20}")

        # 被舍弃的任务分析
        dropped = [m_id for m_id, sat in final_sats.items() if sat < eta]
        if dropped:
            dropped_pri = [mission_priorities.get(m_id, (3, 3))[0] for m_id in dropped]
            kept_pri = [mission_priorities.get(m_id, (3, 3))[0] for m_id in final_sats if m_id not in dropped]
            print(f"\n被舍弃任务({len(dropped)}个)的平均优先级: {np.mean(dropped_pri):.1f}")
            print(f"保留任务({len(final_sats)-len(dropped)}个)的平均优先级: {np.mean(kept_pri):.1f}")
            print(f"结论: {'高优先级任务得到优先保留 ✓' if np.mean(kept_pri) > np.mean(dropped_pri) else '需调整优先级权重'}")
        else:
            low_sat = [m_id for m_id, sat in final_sats.items() if sat < 0.3]
            high_sat = [m_id for m_id, sat in final_sats.items() if sat >= 0.8]
            if low_sat and high_sat:
                low_pri = [mission_priorities.get(m_id, (3, 3))[0] for m_id in low_sat]
                high_pri = [mission_priorities.get(m_id, (3, 3))[0] for m_id in high_sat]
                print(f"\n低满意度(<30%)任务({len(low_sat)}个)平均优先级: {np.mean(low_pri):.1f}")
                print(f"高满意度(≥80%)任务({len(high_sat)}个)平均优先级: {np.mean(high_pri):.1f}")
                if np.mean(high_pri) > np.mean(low_pri):
                    print(f"结论: 高优先级任务在冲突中优先获得资源 ✓")
                else:
                    print(f"结论: 优先级权重需进一步调整")

        # 调度活动数统计
        scheduled_missions = set(r['Mission'] for r in final_schedule)
        print(f"\n--- 调度统计 ---")
        print(f"成功调度任务数: {len(scheduled_missions)}/{len(final_sats)}")
        print(f"成功调度活动数: {len(final_schedule)}")
        print(f"使用天线数: {len(set(r['Antenna'] for r in final_schedule))}")
        print("="*60)

        # 可视化并保存
        visualize_and_save(final_schedule, filename=output_csv)

        # 构建结构化返回结果 (JSON 可序列化)
        result = {
            "success": True,
            "data_path": data_path,
            "final_eta": eta,
            "iterations": k_max,
            "satisfaction": {m_id: float(v) for m_id, v in final_sats.items()},
            "min_satisfaction": float(min(final_sats.values())) if final_sats else 0.0,
            "avg_satisfaction": float(np.mean(list(final_sats.values()))) if final_sats else 0.0,
            "schedule": [
                {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in r.items()}
                for r in (final_schedule or [])
            ],
            "scheduled_mission_count": len(scheduled_missions),
            "total_missions": len(final_sats),
            "antennas_used": sorted({r["Antenna"] for r in (final_schedule or [])}),
            "mission_priorities": {
                m_id: {"base": int(bp), "peak": int(mp)}
                for m_id, (bp, mp) in mission_priorities.items()
            },
            "output_csv": os.path.abspath(output_csv),
            "output_chart": os.path.abspath("dsn_gantt_chart.png"),
        }
        return result
    finally:
        # 还原标准输出
        if logger_obj is not None:
            try:
                logger_obj.log.close()
            except Exception:
                pass
        sys.stdout = original_stdout


if __name__ == "__main__":
    set_ch_font()
    # 命令行入口：使用项目内默认数据集，启用日志和图片查看器
    _data_path = _default_data_path()
    _result = run_dynamic_optimization(
        _data_path,
        redirect_stdout_to_log=True,
        open_viewer=True,
    )
    # 以 JSON 形式输出最终结果（供子进程调用方解析）
    try:
        print(json.dumps(_result, ensure_ascii=False))
    except Exception:
        pass
