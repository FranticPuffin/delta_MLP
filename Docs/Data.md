根据你生成的 JSONL 数据结构以及论文中的描述，这些参数共同构成了 NASA 深空网络（DSN）调度问题的数学模型输入。以下是每个关键参数的物理意义及其在算法中的作用：

### 1. 任务级别参数 (Mission Level)
这些参数定义了谁在申请资源以及总需求量。
* [cite_start]**`mission_id`**: 任务的唯一标识符（如 DAWN, JNO, MRO） [cite: 116][cite_start]。在算法中用于识别属于同一任务的不同活动，以确保满足“同一任务不能在不同天线同时运行”的约束（Constraint 5 / 6j） [cite: 198, 264]。
* [cite_start]**`total_requested_hr`**: 该任务在一周内请求的总通信时长 [cite: 320][cite_start]。这是衡量**满意度**的分母：$\text{满意度} = \frac{\text{已调度时长}}{\text{请求总时长}}$ [cite: 301, 305]。

---

### 2. 活动级别参数 (Activity Level)
[cite_start]活动（Activity）是调度的最小单位，代表一次具体的通信请求 [cite: 116]。
* [cite_start]**`activity_id`**: 活动的唯一编号 [cite: 29]。
* **`d_min` (Minimum Tracking Time)**: 
    * [cite_start]**物理意义**：任务完成所需的最小连续通信时间 [cite: 130]。
    * [cite_start]**算法意义**：如果调度该活动，其持续时间必须 $\ge d_{min}$。它是硬性约束（Equation 6i）的一部分 [cite: 193, 262]。
* **`d_max` (Maximum Tracking Time)**: 
    * [cite_start]**物理意义**：任务理想状态下的最长通信时间 [cite: 164]。
    * [cite_start]**算法意义**：调度时间不能超过此上限，以防止单一任务过度占用稀缺资源（Equation 6i） [cite: 262]。
* **`setup_min` (准备时间)**:
    * [cite_start]**物理意义**：天线在开始通信前进行对准、配置所需的准备时间 [cite: 131, 194]。
    * [cite_start]**算法意义**：在跟踪时间（Tracking time）之前，天线资源必须被标记为占用（Equation 6f） [cite: 277]。
* **`teardown_min` (拆除时间)**:
    * [cite_start]**物理意义**：通信结束后，天线释放资源、重置状态所需的时间 [cite: 131, 135]。
    * [cite_start]**算法意义**：在跟踪时间之后，天线资源仍需保持占用状态一段时间（Equation 6g） [cite: 277]。
* **`can_split` (可拆分标记)**:
    * [cite_start]**物理意义**：标记该活动是否允许被分割成两个较小的段 [cite: 139]。
    * [cite_start]**算法逻辑**：对应论文的 **Algorithm 1**。如果为 `True`（通常 $d_{max} \ge 8$ 小时），算法会引入 XOR 逻辑变量来决定是调度一个长任务还是两个短任务 [cite: 140, 206, 221]。
* **`prefer` (天线策略倾向)**:
    * **物理意义**：活动对使用天线类型的倾向性策略。
        * `0`：倾向中继星（Relay Satellite）
        * `1`：倾向地面站（Ground Station）
        * `2`：默认策略，不强制倾向
    * **算法作用**：在生成候选调度时，可作为偏好排序或软约束依据。例如，当 `prefer=0` 时，优先选择 `antenna_type=0` 的视图窗口；`prefer=1` 时优先选择 `antenna_type=1` 的窗口；`prefer=2` 时保持原有默认行为。

---

### 3. 视图周期参数 (View Periods)
[cite_start]视图周期定义了飞船“何时”以及“在哪里”对天线可见 [cite: 137]。
* [cite_start]**`antenna` (Resource)**: 执行通信的具体硬件（如 DSS-43 是澳大利亚的 70 米天线） [cite: 93, 128]。
* **`antenna_type` (天线属性)**: 标识该天线的类型。
    * `0`：中继星（Relay Satellite）
    * `1`：地面站（Ground Station）
    * **算法作用**：配合活动级别的 `prefer` 字段，用于判断视图窗口是否满足任务的天线类型偏好。
* **`start_hr` & `end_hr`**: 
    * [cite_start]**物理意义**：由于地球自转和飞船轨道运动，飞船出现在该天线地平线之上和落下的时刻 [cite: 135, 136]。
    * [cite_start]**算法意义**：这定义了决策变量 $X_{v,t}$ 的取值范围。所有的跟踪、准备和拆除时间都必须落在 $[start\_hr, end\_hr]$ 窗口内（Equation 6b） [cite: 192, 243, 274]。

### 4. 数据参数的宏观作用：满足物理约束
这些参数输入到 $\Delta$-MILP 模型中后，主要用于解决以下冲突：

| 约束类型 | 涉及参数 | 论文公式参考 |
| :--- | :--- | :--- |
| **资源互斥** | `antenna`, `start/end_hr` | [cite_start]$R(Y^{\perp}+X+Y^{\dagger})\le1$ (同一时间天线只能连一个飞船) [cite: 260] |
| **任务互斥** | `mission_id`, `start/end_hr` | [cite_start]$MA(Y^{\perp}+X+Y^{\dagger})\le1$ (同一飞船不能同时连两个天线) [cite: 264] |
| **时长合规** | `d_min`, `d_max`, `setup`, `teardown` | [cite_start]$diag\{d_{min}\}x\le AX1\le diag\{d_{max}\}x$ [cite: 262] |

[cite_start]这些数据是算法实现 100% 有效音轨（Valid Tracks）的基础，确保生成的调度表在物理上是可执行的 [cite: 15, 120]。