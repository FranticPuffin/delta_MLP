import pandas as pd
import json
import random
import numpy as np
import os

# 确保目录存在
Data_path = "../Data/dsn_data.jsonl"
os.makedirs(os.path.dirname(Data_path), exist_ok=True)

# 优先级等级定义 (1-5, 5为最高)
PRIORITY_LEVELS = {
    1: "低优先级(常规监测)",
    2: "中低优先级(常规通信)",
    3: "中优先级(科学数据下行)",
    4: "高优先级(关键事件/飞掠)",
    5: "最高优先级(紧急/不可重访)"
}

def generate_priority_schedule(base_priority, horizon_hr=168):
    """
    为任务生成优先级时段表 priority_schedule
    - 将168小时划分为若干时段，每时段赋予优先级
    - 基础优先级作为底色，部分时段会因关键事件提升优先级
    """
    schedule = []
    t = 0.0
    while t < horizon_hr:
        # 段长度: 8~48小时随机
        seg_len = random.uniform(8, 48)
        seg_end = min(t + seg_len, horizon_hr)
        
        # 大部分时段使用 base_priority，有概率提升
        if random.random() < 0.3:  # 30%概率出现优先级提升
            # 提升幅度: +1 或 +2，不超过5
            boost = random.choice([1, 2])
            seg_pri = min(base_priority + boost, 5)
        else:
            seg_pri = base_priority
        
        schedule.append({
            "start_hr": round(t, 2),
            "end_hr": round(seg_end, 2),
            "priority": seg_pri
        })
        t = seg_end
    return schedule

def generate_dsn_jsonl(output_file=Data_path, num_missions=100):
    """
    生成扩充版的 DSN 调度数据集
    - 天线数量: 40
    - 任务数量: 100
    - 包含 base_priority 和 priority_schedule 字段
    """
    # 1. 扩充天线池至 40 个 (模拟全球三个综合体的编号)
    antennas = [f"DSS-{i}" for i in range(10, 50)] 
    
    # 典型任务配置采样 —— 前4个任务使用人工定义的有意义的优先级
    mission_templates = [
        {"name": "DAWN", "tr_hr": 168.0, "n_act": 21, "d_min": 6.4, "d_max": 8.0, "base_priority": 4},  # 高优先级：关键飞掠事件
        {"name": "JNO",  "tr_hr": 128.0, "n_act": 18, "d_min": 5.9, "d_max": 7.1, "base_priority": 5},  # 最高优先级：木星不可重访
        {"name": "MRO",  "tr_hr": 112.0, "n_act": 14, "d_min": 6.4, "d_max": 8.0, "base_priority": 3},  # 中优先级：科学数据下行
        {"name": "DSCO", "tr_hr": 1.0,   "n_act": 1,  "d_min": 1.0, "d_max": 1.0, "base_priority": 2},  # 中低优先级：常规通信
    ]

    with open(output_file, 'w', encoding='utf-8') as f:
        for i in range(num_missions):
            # 前几个任务使用经典模板，其余随机生成
            if i < len(mission_templates):
                template = mission_templates[i]
            else:
                # 随机生成任务参数
                tr_hr = random.uniform(20, 100)
                # 优先级分布: 1(20%), 2(25%), 3(30%), 4(15%), 5(10%) —— 低优先级更多，制造冲突
                base_priority = random.choices([1, 2, 3, 4, 5], weights=[20, 25, 30, 15, 10])[0]
                template = {
                    "name": f"MIS-{i+1:03d}",
                    "tr_hr": round(tr_hr, 1),
                    "n_act": random.randint(5, 15),
                    "d_min": round(random.uniform(2.0, 4.0), 1),
                    "d_max": round(random.uniform(5.0, 9.0), 1),
                    "base_priority": base_priority
                }

            mission_entry = {
                "mission_id": template["name"],
                "total_requested_hr": template["tr_hr"],
                "base_priority": template["base_priority"],
                "priority_schedule": generate_priority_schedule(template["base_priority"]),
                "activities": []
            }

            for a_idx in range(template["n_act"]):
                # 模拟每个活动的视图窗口 (View Periods)
                view_periods = []
                # 每个活动随机分配 1-4 个可选的天线窗口
                for v_idx in range(random.randint(1, 4)):
                    start_hr = random.uniform(0, 168) # 模拟一周 168 小时内的跨度
                    duration = random.uniform(template["d_max"], template["d_max"] + 6)
                    view_periods.append({
                        "antenna": random.choice(antennas),
                        "start_hr": round(start_hr, 2),
                        "end_hr": round(start_hr + duration, 2)
                    })

                mission_entry["activities"].append({
                    "activity_id": f"{template['name']}_ACT_{a_idx:02d}",
                    "d_min": template["d_min"],
                    "d_max": template["d_max"],
                    "setup_min": 60,
                    "teardown_min": 15,
                    "can_split": template["d_max"] >= 8.0,
                    "view_periods": view_periods
                })

            # 写入 JSONL
            f.write(json.dumps(mission_entry, ensure_ascii=False) + "\n")
    
    print(f"--- 数据生成完毕 ---")
    print(f"目标文件: {output_file}")
    print(f"任务总数: {num_missions}")
    print(f"可用天线数: {len(antennas)}")

# --- 执行生成 ---
generate_dsn_jsonl()

# --- 验证生成的数据 ---
total_activities = 0
mission_count = 0
priority_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

print("\n--- 数据概览 (部分) ---")
with open(Data_path, 'r', encoding='utf-8') as f:
    for line in f:
        mission = json.loads(line)
        mission_count += 1
        num_acts = len(mission['activities'])
        total_activities += num_acts
        base_pri = mission.get('base_priority', 3)
        priority_dist[base_pri] = priority_dist.get(base_pri, 0) + 1
        
        # 仅打印前 5 个和最后 1 个任务进行观察
        if mission_count <= 5 or mission_count == 100:
            print(f"[{mission_count:03d}] 任务ID: {mission['mission_id']}, "
                  f"活动数: {num_acts}, "
                  f"需求时长: {mission['total_requested_hr']} hr, "
                  f"基础优先级: {base_pri}({PRIORITY_LEVELS.get(base_pri, '')})")

print(f"\n总结: 共处理 {mission_count} 个任务，生成 {total_activities} 条活动记录。")
print(f"\n优先级分布:")
for pri in sorted(priority_dist.keys()):
    desc = PRIORITY_LEVELS.get(pri, "")
    print(f"  优先级 {pri} ({desc}): {priority_dist[pri]} 个任务")