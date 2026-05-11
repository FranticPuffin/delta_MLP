import pandas as pd
import json
import random
import numpy as np
import os

# 输出路径 - 使用绝对路径确保正确
script_dir = os.path.dirname(os.path.abspath(__file__))
Data_path = os.path.join(script_dir, "..", "Data", "dsn_data3.jsonl")


# DSN 三大深空通信复合站 [cite: 93]
ANTENNA_COMPLEXES = {
    "Goldstone":  ["DSS-14", "DSS-15", "DSS-24", "DSS-25", "DSS-26"],
    "Canberra":   ["DSS-34", "DSS-35", "DSS-36", "DSS-43", "DSS-45"],
    "Madrid":     ["DSS-54", "DSS-55", "DSS-63", "DSS-65"]
}
ALL_ANTENNAS = [a for complex_ants in ANTENNA_COMPLEXES.values() for a in complex_ants]

# 每个复合站对应的高峰子时段 (模拟地球自转，每站约8-10小时可见)
# 关键改进：三个站的高峰时段有显著重叠，制造跨站资源竞争
def get_complex_peak_hours(complex_name, day_start):
    """返回某复合站在某天的高峰可视时段 (小时偏移)
    故意让三个站的高峰时段有2-4小时重叠，增加调度冲突"""
    offsets = {
        "Goldstone": (0, 10),    # 0:00-10:00
        "Canberra":  (6, 16),    # 6:00-16:00 (与Goldstone重叠6-10)
        "Madrid":    (12, 24)    # 12:00-24:00 (与Canberra重叠12-16)
    }
    s, e = offsets[complex_name]
    return (day_start + s, day_start + e)


# 优先级等级定义 (1-5, 5为最高)
PRIORITY_LEVELS = {
    1: "低优先级(常规监测)",
    2: "中低优先级(常规通信)",
    3: "中优先级(科学数据下行)",
    4: "高优先级(关键事件/飞掠)",
    5: "最高优先级(紧急/不可重访)"
}

def generate_priority_schedule(base_priority, mission_name):
    """
    为任务生成时间变化的优先级排程
    模拟真实场景：任务在不同时间段有不同重要程度
    例如：飞掠事件期间优先级飙升，常规巡航期间优先级较低
    
    返回: list of {"start_hr", "end_hr", "priority", "reason"}
    """
    schedule = []
    
    # 将一周分为若干时段，每个时段可能有不同优先级
    # 基础策略：1-2个关键窗口(优先级提升1-2级) + 其余时段为基础优先级
    critical_windows = random.randint(1, 3)  # 1-3个关键窗口
    
    # 生成关键窗口时段
    critical_periods = []
    for _ in range(critical_windows):
        crit_start = random.choice([0, 24, 48, 72, 96, 120, 144])  # 从某天开始
        crit_duration = random.randint(8, 24)  # 持续8-24小时
        crit_end = min(crit_start + crit_duration, 168)
        priority_boost = random.randint(1, 2)  # 提升1-2级
        critical_periods.append((crit_start, crit_end, priority_boost))
    
    # 构建完整优先级排程
    # 先用基础优先级填充整周
    time_points = set([0, 168])
    for cs, ce, _ in critical_periods:
        time_points.add(cs)
        time_points.add(ce)
    time_points = sorted(time_points)
    
    for i in range(len(time_points) - 1):
        seg_start = time_points[i]
        seg_end = time_points[i + 1]
        
        # 检查该时段是否在某个关键窗口内
        seg_priority = base_priority
        reason = "常规时段"
        for cs, ce, boost in critical_periods:
            if seg_start >= cs and seg_end <= ce:
                seg_priority = min(base_priority + boost, 5)
                reason = "关键事件窗口" if boost == 2 else "重要操作时段"
                break
        
        schedule.append({
            "start_hr": seg_start,
            "end_hr": seg_end,
            "priority": seg_priority,
            "reason": reason
        })
    
    return schedule


def generate_dsn_jsonl(output_file=Data_path, num_missions=30, oversubscribe_ratio=2.0):
    """
    生成分布密集的 DSN 调度数据集并保存为 JSONL 格式
    
    核心改进：
    1. 更多任务数量 + 超额订阅比 (2.0x)
    2. 时间聚集：活动集中在1-2个高峰日
    3. 天线偏好聚集：80%概率使用偏好站
    4. 窗口紧凑化：视图窗口仅比d_max多0.5-2小时
    5. 更多活动数：每个任务8-25个活动
    6. 高峰时段重叠：三个复合站的可见窗口有2-4小时重叠
    7. 优先级系统：每个任务在不同时段有不同优先级(1-5)
    
    oversubscribe_ratio: 超额订阅比，总需求/总容量
    """
    random.seed(42)  # 可复现性
    np.random.seed(42)
    
    # 典型任务配置采样自 Table 3 [cite: 333]
    # 增加 base_priority 字段模拟手动设置的重要程度
    mission_templates = [
        {"name": "DAWN", "tr_hr": 180.0, "n_act": 25, "d_min": 6.4, "d_max": 8.0,
         "preferred_complex": "Goldstone", "base_priority": 4},  # 矮行星飞掠-高优先级
        {"name": "JNO",  "tr_hr": 150.0, "n_act": 22, "d_min": 5.9, "d_max": 7.1,
         "preferred_complex": "Canberra", "base_priority": 5},   # 木星轨道插入-最高优先级
        {"name": "MRO",  "tr_hr": 140.0, "n_act": 20, "d_min": 6.4, "d_max": 8.0,
         "preferred_complex": "Madrid", "base_priority": 3},     # 火星侦察-中优先级
        {"name": "VGR",  "tr_hr": 120.0, "n_act": 18, "d_min": 5.0, "d_max": 7.0,
         "preferred_complex": "Goldstone", "base_priority": 2},  # 旅行者号-中低(延寿任务)
        {"name": "CASS", "tr_hr": 110.0, "n_act": 16, "d_min": 5.5, "d_max": 7.5,
         "preferred_complex": "Canberra", "base_priority": 4},   # 卡西尼-高优先级
        {"name": "NH",   "tr_hr": 100.0, "n_act": 15, "d_min": 4.0, "d_max": 6.0,
         "preferred_complex": "Madrid", "base_priority": 5},     # 新视野号飞掠-最高优先级
        {"name": "DSCO", "tr_hr": 2.0,   "n_act": 2,  "d_min": 1.0, "d_max": 1.0,
         "preferred_complex": "Goldstone", "base_priority": 1},  # 深空气候观测-低优先级
    ]

    # 总天线容量: 14天线 × 168小时 × 70%利用率 ≈ 1646.4 小时
    total_capacity = 14 * 168 * 0.7
    target_demand = total_capacity * oversubscribe_ratio  # 目标总需求

    with open(output_file, 'w', encoding='utf-8') as f:
        total_generated_demand = 0

        for i in range(num_missions):
            # 优先使用论文中的典型任务模板 [cite: 333, 348]
            if i < len(mission_templates):
                template = mission_templates[i]
            else:
                # 随机任务：大幅增加活动数和请求时长以制造密集排布
                template = {
                    "name": f"MIS-{i+1:02d}",
                    "tr_hr": random.uniform(40, 100),  # 提高请求时长范围
                    "n_act": random.randint(8, 18),     # 增加活动数量
                    "d_min": random.uniform(2.0, 4.0),
                    "d_max": random.uniform(4.0, 7.0),
                    "preferred_complex": random.choice(list(ANTENNA_COMPLEXES.keys())),
                    "base_priority": random.randint(1, 5)  # 随机基础优先级
                }

            # 生成时间变化的优先级排程
            base_pri = template.get("base_priority", 3)
            priority_schedule = generate_priority_schedule(base_pri, template["name"])

            mission_entry = {
                "mission_id": template["name"],
                "total_requested_hr": template["tr_hr"],
                "base_priority": base_pri,
                "priority_schedule": priority_schedule,
                "activities": []
            }
            total_generated_demand += template["tr_hr"]

            for a_idx in range(template["n_act"]):
                view_periods = []
                
                # 每个活动生成 3-6 个视图窗口 (增加重叠概率)
                num_vp = random.randint(3, 6)
                
                # 关键改进：选择该活动的时间聚集中心
                # 从一周7天中只选1-2天作为主要窗口（而非3-5天）
                # 这样大量活动会挤在同一两天，制造时间冲突
                preferred_days = random.sample(range(7), k=min(random.randint(1, 2), 7))
                
                for v_idx in range(num_vp):
                    # 确定使用哪个复合站的天线
                    # 80%概率使用偏好复合站（提高聚集度）
                    if random.random() < 0.8:
                        complex_name = template.get("preferred_complex", random.choice(list(ANTENNA_COMPLEXES.keys())))
                    else:
                        complex_name = random.choice(list(ANTENNA_COMPLEXES.keys()))
                    
                    # 关键改进：在同一复合站内，偏好使用同一组天线
                    # 70%概率选择该站的前2个天线（制造同天线竞争）
                    antennas_in_complex = ANTENNA_COMPLEXES[complex_name]
                    if random.random() < 0.7:
                        antenna = random.choice(antennas_in_complex[:2])  # 偏好前2个
                    else:
                        antenna = random.choice(antennas_in_complex)
                    
                    # 在该复合站的高峰时段内生成窗口
                    day = preferred_days[v_idx % len(preferred_days)]
                    day_start = day * 24
                    peak_start, peak_end = get_complex_peak_hours(complex_name, day_start)
                    
                    # 关键改进：窗口持续时间极度紧凑化
                    # 仅比 d_max 多 0.5-2 小时（而非之前的1-4小时）
                    # 这样窗口内几乎刚好能放下活动，制造强烈资源竞争
                    vp_duration = random.uniform(
                        template["d_max"] + 0.5,   # 仅多0.5小时
                        template["d_max"] + 2.0    # 最多多2小时余量
                    )
                    
                    # 在高峰时段内随机放置窗口起点
                    latest_start = max(peak_start, peak_end - vp_duration)
                    if latest_start <= peak_start:
                        start_hr = peak_start
                    else:
                        start_hr = random.uniform(peak_start, latest_start)
                    
                    # 确保不超出168小时
                    end_hr = min(start_hr + vp_duration, 168.0)
                    
                    view_periods.append({
                        "antenna": antenna,
                        "start_hr": round(start_hr, 2),
                        "end_hr": round(end_hr, 2)
                    })

                mission_entry["activities"].append({
                    "activity_id": f"{template['name']}_ACT_{a_idx}",
                    "d_min": template["d_min"],
                    "d_max": template["d_max"],
                    "setup_min": 60,   # 论文中 setup 均值约为 60 分钟 [cite: 332, 333]
                    "teardown_min": 15, # 论文中 teardown 均值约为 15 分钟 [cite: 332, 333]
                    "can_split": template["d_max"] >= 8.0, # 符合 Algorithm 1 拆分条件 [cite: 206, 222]
                    "view_periods": view_periods
                })

            # 将每个 Mission 序列化为一行 JSON
            f.write(json.dumps(mission_entry, ensure_ascii=False) + "\n")
    
    print(f"成功生成密集分布 JSONL 数据: {output_file}")
    print(f"目标超额订阅比: {oversubscribe_ratio:.1f}x")
    print(f"总天线容量: {total_capacity:.0f} 小时")
    print(f"生成总需求: {total_generated_demand:.0f} 小时")
    print(f"实际超额比: {total_generated_demand/total_capacity:.2f}x")

# 执行
generate_dsn_jsonl()

# 生成数据并统计
total_activities = 0
total_view_periods = 0

with open(Data_path, 'r', encoding='utf-8') as f:
    for line in f:
        mission = json.loads(line)
        num_acts = len(mission['activities'])
        total_activities += num_acts
        for act in mission['activities']:
            total_view_periods += len(act['view_periods'])
        
        base_pri = mission.get('base_priority', 3)
        pri_schedule = mission.get('priority_schedule', [])
        max_pri = max((s['priority'] for s in pri_schedule), default=base_pri)
        print(f"任务ID: {mission['mission_id']}, "
              f"基础优先级: {base_pri}, 峰值优先级: {max_pri}, "
              f"活动数: {num_acts}, "
              f"请求总时长: {mission['total_requested_hr']:.1f}小时, "
              f"视图窗口总数: {sum(len(a['view_periods']) for a in mission['activities'])}")

print(f"\n生成的总活动记录数: {total_activities}")
print(f"生成的总视图窗口数: {total_view_periods}")
print(f"平均每活动窗口数: {total_view_periods/total_activities:.1f}")

# --- 密集度分析 ---
print("\n" + "="*50)
print("密集度分析")
print("="*50)

# 分析每个时间槽(1小时)的活动需求数
time_slot_demand = [0] * 168  # 168小时
with open(Data_path, 'r', encoding='utf-8') as f:
    for line in f:
        mission = json.loads(line)
        for act in mission['activities']:
            for vp in act['view_periods']:
                start = int(vp['start_hr'])
                end = int(vp['end_hr']) + 1
                for t in range(max(0, start), min(168, end)):
                    time_slot_demand[t] += 1

# 按天统计
for day in range(7):
    day_start = day * 24
    day_end = (day + 1) * 24
    day_demand = time_slot_demand[day_start:day_end]
    print(f"周{day+1}: 平均需求密度={np.mean(day_demand):.1f}, 峰值={max(day_demand)}, 最低={min(day_demand)}")

print(f"\n全局: 平均需求密度={np.mean(time_slot_demand):.1f}, 峰值={max(time_slot_demand)}")
print(f"需求>14(天线数)的时间槽占比: {sum(1 for d in time_slot_demand if d > 14)/168:.1%}")
print(f"需求>10的时间槽占比: {sum(1 for d in time_slot_demand if d > 10)/168:.1%}")