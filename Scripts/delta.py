import json
import pulp
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import platform

# 优先级等级定义 (1-5, 5为最高)
PRIORITY_LEVELS = {
    1: "低优先级(常规监测)",
    2: "中低优先级(常规通信)",
    3: "中优先级(科学数据下行)",
    4: "高优先级(关键事件/飞掠)",
    5: "最高优先级(紧急/不可重访)"
}

def set_ch_font():
    # 1. 解决中文显示问题
    system = platform.system()
    if system == "Windows":
        # Windows 下常用的黑体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial'] 
    elif system == "Darwin": # macOS
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']
    else: # Linux
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
    
    # 2. 必须设置这个参数，否则中文字体生效后，坐标轴的负号 '-' 会变成方框
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

    def _get_priority_at_time(self, mission, time_hr):
        """获取任务在指定时间的优先级(1-5)"""
        pri_schedule = mission.get('priority_schedule', [])
        for seg in pri_schedule:
            if seg['start_hr'] <= time_hr < seg['end_hr']:
                return seg['priority']
        return mission.get('base_priority', 3)

    def _get_activity_priority(self, mission, act):
        """获取活动的加权优先级 - 基于其视图窗口的时间覆盖"""
        pri_schedule = mission.get('priority_schedule', [])
        base_pri = mission.get('base_priority', 3)
        
        if not pri_schedule:
            return base_pri
        
        # 计算活动在各优先级时段的覆盖时长，取加权平均
        total_weight = 0
        total_duration = 0
        for vp in act['view_periods']:
            vp_start = vp['start_hr']
            vp_end = vp['end_hr']
            vp_dur = vp_end - vp_start
            if vp_dur <= 0:
                continue
            # 找该窗口覆盖的优先级时段
            for seg in pri_schedule:
                overlap_start = max(vp_start, seg['start_hr'])
                overlap_end = min(vp_end, seg['end_hr'])
                overlap = overlap_end - overlap_start
                if overlap > 0:
                    total_weight += seg['priority'] * overlap
                    total_duration += overlap
        
        if total_duration > 0:
            return total_weight / total_duration
        return base_pri

    def _resolve_conflicts(self, candidates):
        """
        冲突解决：当天线时间槽冲突时，优先保留高优先级任务，舍弃低优先级任务
        同时检查任务级互斥（同一航天器不能同时占用两个天线）
        """
        if not candidates:
            return []

        # 构建任务优先级映射
        priority_map = {}
        for m in self.missions_data:
            m_id = m['mission_id']
            base_pri = m.get('base_priority', 3)
            pri_schedule = m.get('priority_schedule', [])
            max_pri = max((s['priority'] for s in pri_schedule), default=base_pri)
            priority_map[m_id] = max_pri

        # 按优先级降序排列（高优先级先分配资源），同优先级按开始时间升序
        sorted_candidates = sorted(candidates,
                                   key=lambda x: (-priority_map.get(x['Mission'], 3), x['Start']))

        final_schedule = []
        antenna_timeline = {}   # antenna -> list of (start, end) 已占用区间
        mission_timeline = {}   # mission -> list of (start, end) 已占用区间
        scheduled_activities = set()  # 已调度的活动ID

        dropped_count = 0
        dropped_by_priority = []  # 记录被舍弃的任务及优先级

        for item in sorted_candidates:
            act_key = item['Activity']
            if act_key in scheduled_activities:
                continue  # 该活动已调度，跳过

            antenna = item['Antenna']
            mission = item['Mission']
            # 包含 setup 和 teardown 的完整占用区间
            item_start = item['Start'] - item['Setup']
            item_end = item['End'] + item['Teardown']

            # --- 检查天线级冲突 (Constraint 6h) ---
            if antenna not in antenna_timeline:
                antenna_timeline[antenna] = []
            antenna_conflict = False
            for (start, end) in antenna_timeline[antenna]:
                if item_start < end and start < item_end:
                    antenna_conflict = True
                    break

            # --- 检查任务级冲突 (Constraint 6j: 同一航天器不能同时占用两个天线) ---
            if mission not in mission_timeline:
                mission_timeline[mission] = []
            mission_conflict = False
            for (start, end) in mission_timeline[mission]:
                if item_start < end and start < item_end:
                    mission_conflict = True
                    break

            if not antenna_conflict and not mission_conflict:
                # 无冲突，保留该活动
                antenna_timeline[antenna].append((item_start, item_end))
                mission_timeline[mission].append((item_start, item_end))
                scheduled_activities.add(act_key)
                final_schedule.append(item)
            else:
                # 有冲突，舍弃该活动（因为高优先级已先处理，此处舍弃的必然是低优先级）
                dropped_count += 1
                dropped_by_priority.append((mission, priority_map.get(mission, 3)))

        if dropped_count > 0:
            avg_dropped_pri = sum(p for _, p in dropped_by_priority) / len(dropped_by_priority)
            kept_pri = [priority_map.get(item['Mission'], 3) for item in final_schedule]
            avg_kept_pri = sum(kept_pri) / len(kept_pri) if kept_pri else 0
            print(f"  [冲突解决] 舍弃 {dropped_count} 个低优先级活动，"
                  f"保留 {len(final_schedule)} 个活动")
            print(f"  被舍弃活动平均优先级: {avg_dropped_pri:.2f}, "
                  f"保留活动平均优先级: {avg_kept_pri:.2f}")

        return final_schedule

    def solve(self, mission_weights, eta_threshold):
        """
        核心 MILP 求解逻辑 (Equation 6a-6m)
        集成优先级系统：高优先级任务在冲突时优先获得资源
        """
        prob = pulp.LpProblem("Delta_MILP", pulp.LpMaximize)
        
        # 1. 定义变量
        x = {} 
        
        # 预处理任务拆分 (Algorithm 1)
        active_activities = []
        for m in self.missions_data:
            m_id = m['mission_id']
            for act in m['activities']:
                a_id = act['activity_id']
                
                # 基础变量
                x[a_id] = pulp.LpVariable(f"x_{a_id}", cat='Binary')
                # 计算该活动的优先级权重
                act_priority = self._get_activity_priority(m, act)
                active_activities.append((m_id, act, a_id, False, act_priority))
                
                # XOR 拆分逻辑：如果满足拆分条件 (Algorithm 1)
                if act['can_split']:
                    a_prime = f"{a_id}_prime"
                    a_dprime = f"{a_id}_dprime"
                    x[a_prime] = pulp.LpVariable(f"x_{a_prime}", cat='Binary')
                    x[a_dprime] = pulp.LpVariable(f"x_{a_dprime}", cat='Binary')
                    
                    # 约束 6k, 6l: 子任务必须成对调度
                    prob += x[a_prime] == x[a_dprime]
                    # 约束 6m: 原始与拆分互斥
                    prob += x[a_id] + x[a_prime] <= 1
                    
                    # 添加子活动到处理列表
                    active_activities.append((m_id, act, a_prime, True, act_priority))
                    active_activities.append((m_id, act, a_dprime, True, act_priority))

        # 2. 目标函数 (Equation 6a)
        # 权重 = 迭代权重 × 优先级权重
        # 优先级高的活动在目标函数中系数更大，冲突时求解器会优先保留
        obj_elements = []
        for m_id, act, a_name, is_split, act_priority in active_activities:
            iter_weight = mission_weights.get(m_id, 1.0)
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
        solver = pulp.GLPK_CMD(msg=1, options=['--tmlim', '60'])  # 每次求解最多60秒
        prob.solve(solver) 
        
        # 5. 生成候选调度结果（为每个已调度活动生成所有可选视图窗口的候选）
        raw_candidates = []
        for m in self.missions_data:
            m_id = m['mission_id']
            for act in m['activities']:
                a_id = act['activity_id']
                # 检查是否被选中
                if pulp.value(x[a_id]) is not None and pulp.value(x[a_id]) > 0.5:
                    # 为该活动的每个视图窗口生成候选
                    for vp in act['view_periods']:
                        raw_candidates.append({
                            "Mission": m_id,
                            "Activity": a_id,
                            "Antenna": vp['antenna'],
                            "Start": vp['start_hr'],
                            "End": vp['start_hr'] + act['d_max'],
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

    # 2. 绘制甘特图
    plt.figure(figsize=(18, 10))
    antennas = sorted(df['Antenna'].unique())
    missions = df['Mission'].unique()
    colors = plt.cm.tab20(np.linspace(0, 1, len(missions)))
    color_map = dict(zip(missions, colors))

    for i, row in df.iterrows():
        ant_idx = antennas.index(row['Antenna'])
        
        # 绘制准备时间 (Setup) - 灰色
        plt.barh(ant_idx, row['Setup'], left=row['Start'] - row['Setup'], 
                 color='lightgrey', edgecolor='gray', alpha=0.5)
        
        # 绘制跟踪时间 (Tracking) - 任务颜色
        plt.barh(ant_idx, row['End'] - row['Start'], left=row['Start'], 
                 color=color_map[row['Mission']], edgecolor='black', label=row['Mission'])
        
        # 绘制拆除时间 (Teardown) - 灰色
        plt.barh(ant_idx, row['Teardown'], left=row['End'], 
                 color='lightgrey', edgecolor='gray', alpha=0.5)
        
        # 标注任务名
        plt.text(row['Start'], ant_idx, row['Mission'], va='center', ha='left', fontsize=6)

    plt.yticks(range(len(antennas)), antennas, fontsize=7)
    plt.xlabel("时间 (小时, 从周一 00:00 开始)")
    plt.title("地面探测站航天器检测任务调度甘特图 (Delta-MILP 优先级调度)")
    plt.grid(axis='x', linestyle='--', alpha=0.7)
    
    # 防止图例重复
    handles, labels = plt.gca().get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    plt.legend(by_label.values(), by_label.keys(), loc='upper right', 
               bbox_to_anchor=(1.15, 1), fontsize=7)
    
    plt.tight_layout()
    plt.savefig("dsn_gantt_chart.png", dpi=150)
    plt.show()

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
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        pass

def run_dynamic_optimization(data_path):
    # 将标准输出重定向至文件
    sys.stdout = Logger()
    
    scheduler = DeltaMILPScheduler(data_path)
    mission_ids = [m['mission_id'] for m in scheduler.missions_data]
    weights = {m_id: 1.0 for m_id in mission_ids}
    eta = 0.15  
    eta_plus = 0.05 
    k_max = 10 

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
        avg_sat = np.mean(list(sats.values()))
        
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

    # 构建任务优先级映射
    mission_priorities = {}
    for m in scheduler.missions_data:
        m_id = m['mission_id']
        base_pri = m.get('base_priority', 3)
        pri_schedule = m.get('priority_schedule', [])
        max_pri = max((s['priority'] for s in pri_schedule), default=base_pri)
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
    # 按基础优先级分组统计平均满意度
    pri_groups = {}
    for m_id, sat_val in final_sats.items():
        base_pri = mission_priorities.get(m_id, (3,3))[0]
        if base_pri not in pri_groups:
            pri_groups[base_pri] = []
        pri_groups[base_pri].append(sat_val)
    
    print(f"{'优先级':>8} {'任务数':>6} {'平均满意度':>10} {'说明':>20}")
    for pri in sorted(pri_groups.keys()):
        sats_list = pri_groups[pri]
        desc = PRIORITY_LEVELS.get(pri, "")
        print(f"{pri:>8} {len(sats_list):>6} {np.mean(sats_list):>10.1%} {desc:>20}")
    
    # 被舍弃的任务分析
    dropped = [m_id for m_id, sat in final_sats.items() if sat < eta]
    if dropped:
        dropped_pri = [mission_priorities.get(m_id, (3,3))[0] for m_id in dropped]
        kept_pri = [mission_priorities.get(m_id, (3,3))[0] for m_id in final_sats if m_id not in dropped]
        print(f"\n被舍弃任务({len(dropped)}个)的平均优先级: {np.mean(dropped_pri):.1f}")
        print(f"保留任务({len(final_sats)-len(dropped)}个)的平均优先级: {np.mean(kept_pri):.1f}")
        print(f"结论: {'高优先级任务得到优先保留 ✓' if np.mean(kept_pri) > np.mean(dropped_pri) else '需调整优先级权重'}")
    else:
        # 分析低满意度vs高满意度任务的优先级差异
        low_sat = [m_id for m_id, sat in final_sats.items() if sat < 0.3]
        high_sat = [m_id for m_id, sat in final_sats.items() if sat >= 0.8]
        if low_sat and high_sat:
            low_pri = [mission_priorities.get(m_id, (3,3))[0] for m_id in low_sat]
            high_pri = [mission_priorities.get(m_id, (3,3))[0] for m_id in high_sat]
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
    visualize_and_save(final_schedule)


set_ch_font()
# 运行模拟 - 使用绝对路径
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
data_path = os.path.join(script_dir, "..", "Data", "dsn_data.jsonl")
run_dynamic_optimization(data_path)