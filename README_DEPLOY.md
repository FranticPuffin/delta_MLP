# DSN Delta-MILP — 离线部署与 Java 调用指南

本文档说明如何把 `delta.py` 算法封装成 HTTP 服务，**完全离线**部署到目标机器，
并由 Java（或任何语言）通过 Web 接口调用。

---

## 1. 总览

```
开发机 (有网)                          目标机 (无网)
─────────────                         ─────────────
package_offline.bat   ──打包──►  DSN_Delta_Offline_<时间戳>.zip
                                         │
                                         ▼
                                   解压 → install.bat → run_delta_api.bat
                                                            │
                                                            ▼
                                            http://<目标机IP>:8000
                                                            ▲
                                                            │ HTTP/JSON
                                                       Java 调用方
```

打包产物自带：
- **Python 3.11.9 embeddable**（`python\`，无需在目标机装 Python）
- **所有依赖 wheel**（`packages\`，含 fastapi / uvicorn / pulp / pandas …）
- **GLPK 4.65 求解器**（`glpk\glpsol.exe`）
- 项目源码、脚本、示例数据、文档

目标机要求：Windows 10/11 x64，**无需互联网**。

---

## 2. 在开发机上打包

前置条件：

1. 任意可用的 Python（仅用来执行 `pip download`，版本不限）
2. 已联网
3. Windows 10 1803+ 自带 `curl.exe`

执行：

```cmd
cd /d D:\Desktop\三院\算法建模
package_offline.bat
```

脚本流程（共 5 步）：

| 步骤 | 动作 |
| ---- | ---- |
| 1/5 | 下载并解压 `python-3.11.9-embed-amd64.zip` 到 `python\`，并 bootstrap pip |
| 2/5 | `pip download -r requirements.txt` 保存所有 cp311-win_amd64 wheel 到 `packages\` |
| 3/5 | 下载 `winglpk-4.65.zip`，解压 `w64\` 到 `glpk\` |
| 4/5 | 用 bundled Python + 离线 wheel **冒烟测试**安装是否完整 |
| 5/5 | 把 `python\ packages\ glpk\ Scripts\ Data\ Docs\ install.bat …` 拷贝到 `_build_offline\DSN_Delta_Offline_<时间戳>\`，并压缩为 `DSN_Delta_Offline_<时间戳>.zip` |

最终产物（开发机根目录）：

```
DSN_Delta_Offline_20260618_1430.zip
```

把这个 zip 拷到目标机即可。

> 重新打包：直接再跑一次。已经下载过的 Python embeddable / GLPK / wheels 会被复用，不会重复下载。

---

## 3. 在目标机上安装

1. 把 `DSN_Delta_Offline_<时间戳>.zip` 解压到任意目录，例如 `D:\delta\`。
2. 双击 `install.bat`：

   - 校验 `python\python.exe`、`packages\`、`glpk\glpsol.exe` 是否完整；
   - 用 bundled Python 执行
     `pip install --no-index --find-links packages -r requirements.txt`；
   - 验证 `pulp / pandas / numpy / matplotlib / fastapi / uvicorn / pydantic` 全部可导入；
   - 验证 `glpsol.exe` 存在；
   - 试着 import `delta.py` 模块本身。

   只要看到

   ```
   Installation complete.
   ```

   就说明安装成功，**整个过程不需要联网**。

---

## 4. 启动 HTTP 服务

```cmd
run_delta_api.bat
```

等价于：

```cmd
``
python\python.exe Scripts\delta.py --api --host 0.0.0.0 --port 8000`

启动成功后控制台会出现：

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

此时可在浏览器访问：

- 健康检查： <http://127.0.0.1:8000/health>
- OpenAPI： <http://127.0.0.1:8000/openapi.json>
- Swagger UI： <http://127.0.0.1:8000/docs>

---

## 5. HTTP API 接口

服务由 `Scripts/delta.py` 中的 `create_app()` 创建，原始算法保留在
`Scripts/delta_core.py`（不变）。所有接口返回 JSON。

### 5.1 GET `/health`

健康检查。

```json
{
  "status": "ok",
  "service": "delta-api",
  "core_file": ".../Scripts/delta_core.py",
  "core_exists": true
}
```

### 5.2 POST `/api/delta/run`  ★ 推荐 Java 使用

在子进程中执行 `delta_core.py`，每次请求互相隔离，最稳定。

请求体：

| 字段 | 类型 | 默认 | 说明 |
| ---- | ---- | ---- | ---- |
| `args` | string[] | `[]` | 传给 `delta_core.py` 的命令行参数 |
| `stdin` | string \| object \| null | `null` | 标准输入；object/array 会被序列化为 JSON |
| `timeout` | int | `300` | 超时（秒） |
| `cwd` | string \| null | 项目根目录 | 工作目录 |
| `parse_json` | bool | `true` | 尝试把 stdout 解析为 JSON |

响应：

```json
{
  "success": true,
  "return_code": 0,
  "command": ["python", ".../delta_core.py", ...],
  "cwd": "...",
  "stdout": "...",
  "stderr": "...",
  "stdout_json": null
}
```

### 5.3 GET `/api/delta/functions`

列出 `delta_core.py` 中可直接调用的公共函数（仅当模块 import-safe 时可用）。

### 5.4 POST `/api/delta/call/{function_name}`

直接调用 `delta_core.py` 的某个函数。请求体：

```json
{ "args": [1, 2], "kwargs": {"key": "value"} }
```

> 如果 `delta_core.py` 在 import 时会执行重活/调用 `sys.exit()`，请改用
> `/api/delta/run`，它通过子进程执行，最安全。

---

## 6. Java 调用示例

> 所有示例假设服务地址 `http://127.0.0.1:8000`。

### 6.1 纯 JDK（Java 11+，`java.net.http`）

```java
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

public class DeltaClient {
    public static void main(String[] args) throws Exception {
        HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();

        // 1) /health
        HttpRequest health = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:8000/health"))
                .GET().build();
        System.out.println(client.send(health, HttpResponse.BodyHandlers.ofString()).body());

        // 2) /api/delta/run
        String body = """
            {
              "args": [],
              "timeout": 300,
              "parse_json": true
            }
            """;
        HttpRequest run = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:8000/api/delta/run"))
                .timeout(Duration.ofMinutes(10))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();

        HttpResponse<String> resp = client.send(run, HttpResponse.BodyHandlers.ofString());
        System.out.println("status = " + resp.statusCode());
        System.out.println(resp.body());
    }
}
```

### 6.2 Spring Boot（`RestTemplate`）

```java
import org.springframework.http.*;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

public class DeltaService {

    private final RestTemplate rest = new RestTemplate();
    private final String baseUrl = "http://127.0.0.1:8000";

    @SuppressWarnings("unchecked")
    public Map<String, Object> runDelta(List<String> cliArgs, int timeoutSeconds) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        Map<String, Object> payload = Map.of(
                "args", cliArgs,
                "timeout", timeoutSeconds,
                "parse_json", true
        );

        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
        ResponseEntity<Map> resp = rest.postForEntity(
                baseUrl + "/api/delta/run", entity, Map.class);

        return (Map<String, Object>) resp.getBody();
    }
}
```

### 6.3 命令行快速验证

不写 Java 时，可用 `curl` 验证：

```cmd
curl -s http://127.0.0.1:8000/health

curl -s -X POST http://127.0.0.1:8000/api/delta/run ^
     -H "Content-Type: application/json" ^
     -d "{\"args\":[],\"timeout\":300,\"parse_json\":true}"
```

也可以直接双击 `quick_verify_delta_api.bat`。

---

## 7. 输出文件

求解完成后，输出位于：

```
Outputs\dsn_schedule.csv      # 任务排程结果
Outputs\dsn_gantt_chart.png   # 甘特图
Outputs\optimization_log.txt  # 求解器日志
```

Java 调用方拿到 `/api/delta/run` 的返回后，可按需从这些文件读取最终结果。

---

## 8. 常见问题

| 现象 | 原因 / 解决 |
| ---- | ---- |
| `install.bat` 报 `Bundled Python not found` | zip 没解压完整。重新解压，确认 `python\python.exe` 存在 |
| `Offline pip install failed` | `packages\` 里 wheel 缺失。回到开发机重新跑 `package_offline.bat` |
| 启动 API 后另一台机器访问不到 | Windows 防火墙拦了 8000 端口；或服务用了 `127.0.0.1`。`run_delta_api.bat` 默认绑 `0.0.0.0` |
| `/openapi.json` 500 | 不会再发生：Pydantic 模型已挪到模块顶层。如仍出现，确认运行的是最新 `Scripts/delta.py` |
| Java 端连接超时 | 求解时间长，把 `HttpClient` 的读超时调大（示例里设了 10 分钟） |
| 想走 GLPK 而不是默认求解器 | `delta_core.py` 中通过 PuLP 调求解器，可在脚本里指定 `pulp.GLPK_CMD(path=...)` 指向 `glpk\glpsol.exe` |

---

## 9. 目录结构（部署后）

```
<部署目录>\
├── python\                # bundled embeddable Python 3.11.9
├── packages\              # 离线 wheel 缓存
├── glpk\                  # GLPK 4.65 (含 glpsol.exe)
├── Scripts\
│   ├── delta.py           # HTTP API + CLI 入口
│   ├── delta_core.py      # 原始算法实现 (保持不变)
│   └── datapreprocess.py
├── Data\                  # 输入数据 (含 dsn_data.jsonl 示例)
├── Docs\                  # 算法/接口文档
├── Outputs\               # 求解输出 (CSV / PNG / log)
├── install.bat            # 离线安装
├── run_delta_api.bat      # 启动 HTTP 服务
├── run_solver.bat         # 一次性命令行求解
├── run_data_generator.bat # 生成示例数据
├── quick_verify_delta_api.bat  # curl 自检
├── requirements.txt
└── README_DEPLOY.md       # 本文档
```

---

## 10. 部署速查清单

开发机：

- [ ] `requirements.txt` 已更新
- [ ] 运行 `package_offline.bat`，看到 `SUCCESS` 与生成的 zip
- [ ] 把 `DSN_Delta_Offline_<时间戳>.zip` 拷给现场

目标机（无网）：

- [ ] 解压 zip
- [ ] 运行 `install.bat`，看到 `Installation complete.`
- [ ] 运行 `run_delta_api.bat`，看到 `Uvicorn running on http://0.0.0.0:8000`
- [ ] 浏览器访问 `http://127.0.0.1:8000/health` 返回 `"status":"ok"`
- [ ] Java 端通过 `POST /api/delta/run` 即可调用算法
