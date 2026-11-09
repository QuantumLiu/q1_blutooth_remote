# Q1 蓝牙遥控器（Magicsee R1）

用一只实体蓝牙游戏手柄遥控启元 Q1 机器人走路。项目基于 ROS 2 和启元官方 Q1 SDK，提供方向控制、横移、转向、站起/趴下和两个预制动作，并支持语音启动与开机自启。

> **安全警告**
>
> 本项目会直接向运控服务发送速度指令。首次实机测试必须让机器人处于空旷、平整、周围 2 米内无人的环境，并准备独立急停手段（急停开关、断开电源或强制下电）。不要仅依赖手柄按键或本程序停车。遥控器断连、程序崩溃或松开事件丢失时，机器人可能继续运动。

## 功能一览

| 功能 | 操作 |
| --- | --- |
| 前进 / 后退 | 方向键上 / 下 |
| 左转 / 右转 | 方向键左 / 右 |
| 向左平移 / 向右平移 | A / B |
| 站起 / 趴下（语音确认） | O 键序列 |
| 招手 / 碰拳 | C / D |
| 语音连接手柄 | 说“启动R1遥控” |
| 首次绑定手柄 | 说“绑定蓝牙遥控器” |
| 开机自启 | 安装语音监督服务后随机器人启动 |

默认是**无运动模式**：只打印目标速度，不调用运控服务。必须显式加 `execute:=true` 才会让机器人运动。

## 1. 准备清单

| 项目 | 要求 |
| --- | --- |
| 机器人 | 启元 Q1，固件与所用官方 SDK 版本匹配 |
| 手柄 | Magicsee R1 蓝牙游戏手柄（本项目只支持这一型号） |
| 机器人系统 | Ubuntu 22.04、ROS 2 Humble |
| 官方 SDK | 与机器人固件匹配的 Q1 SDK，已编译出 `install/setup.bash` |
| 运行位置 | 推荐机器人大脑板；也可在开发 PC 上运行 |

手柄需要先和机器人配对，并切换到**游戏模式**。这两步见第 3 节。

## 2. 机器人设置

### 2.1 切换到开发者模式

机器人出厂运行在“标准生产模式”，外部程序无法发现它的 ROS 2 节点。必须先在手机 APP 中切换：

1. 打开 PrimeBot APP，连接机器人。
2. 进入「设置」→「开发者功能」。
3. 阅读《二次开发功能启用须知》。开启开发者功能后**不再享受维保服务**，确认后再继续。
4. 运行模式选择「开发者模式」，开发层级选择「基础开发模式」。
5. 点击「保存配置」。
6. 给机器人**重新上下电**，配置才会生效。

本项目只使用官方公开的 ROS 2 服务，不需要「高级开发模式」，也不需要关闭官方运控模块。

如果 APP 提示切换失败，重启机器人后重试；仍失败请联系售后。

### 2.2 确认 ROS 2 通讯

在机器人板卡上运行时，登录后执行：

```bash
source /opt/ros/humble/setup.bash
ros2 node list
```

能看到 `/mc_ros2_node`、`/hal_camera` 等节点，说明通讯正常。

在开发 PC 上运行时，还需要：

1. 用网线直连机器人，PC 有线网卡设为静态 IP `10.1.1.99`，掩码 `255.255.255.0`。
2. 机器人默认地址：大脑板 `10.1.1.101`，运控板 `10.1.1.100`，以实际为准。
3. `ping 10.1.1.101` 和 `ping 10.1.1.100` 均能通。
4. PC 上执行 `ros2 node list` 能看到机器人节点。

PC 与机器人必须使用同一 `ROS_DOMAIN_ID`，防火墙需允许 DDS 的 UDP 通信。

### 2.3 机器人姿态

- **站立或走跑状态**：控制器启动后会自动切到 `BIPED_WALK_RUN`，方向输入立即生效。
- **趴下状态**：控制器保持趴下，方向输入不生效，需要用 O 键序列确认站起。
- 启动前先让机器人稳定站立或平躺，不要在半蹲、被吊起晃动或正在执行其他动作时启动。

### 2.4 避免其他控制源抢占

系统自带的 `rc` 进程会读取同一只手柄，可能让机器人在进入走跑后自动前进。控制器启动实机模式时会：

1. 注册独立输入源 `magicsee_r1`，优先级 30。
2. 通过 `SetMcInputSource` 禁用 `rc`；禁用失败会拒绝运动。
3. 退出时如果机器人仍站立或走跑，保持 `rc` 禁用，避免恢复瞬间被接管。

测试期间不要同时打开 APP 遥控、其他手柄或其它会发送速度指令的程序。

## 3. 手柄设置

### 3.1 首次配对

推荐用语音绑定（需要先完成第 6 节的监督服务安装），它会自动搜索、配对、信任并记忆地址：

1. 手柄开机，按说明书进入可被发现状态。
2. 对机器人说“绑定蓝牙遥控器”。
3. 听到“搜索到可用的 R1 遥控器，是否连接？”后说“确认连接”。

也可以手动配对：

```bash
bluetoothctl
power on
agent on
default-agent
scan on
```

看到 `Magicsee R1` 后记下地址，然后：

```bash
pair <R1_BT_ADDR>
trust <R1_BT_ADDR>
connect <R1_BT_ADDR>
info <R1_BT_ADDR>
```

`info` 中出现 `Connected: yes` 即连接成功。配对失败时先 `remove <R1_BT_ADDR>` 删除旧记录，让手柄重新进入配对状态后再试。

### 3.2 切换到游戏模式

手柄有普通、鼠标、游戏等模式。本项目只支持**游戏模式**，方向和 A/B/C/D 的键码在不同模式下完全不同。

按说明书使用 `M + A/B/C/D` 组合切换模式。切换后建议用第 3.3 节的采集工具确认键码。

手柄重连或换电池后可能回到默认模式；如果语音启动成功但按键没反应，先检查模式。

### 3.3 确认输入节点和键码

列出系统输入设备：

```bash
./scripts/run_key_capture.sh --list
```

应能看到类似 `Magicsee R1` 和 `Magicsee R1 Consumer Control` 的节点。然后采集按键：

```bash
./scripts/run_key_capture.sh
```

依次按方向、A、B、C、D、O，终端会打印 `code=...`、`value=1`（按下）、`value=0`（松开）。按 `Ctrl+C` 结束。该工具只读，不会让机器人运动。

如果提示权限不足，把当前用户加入 `input` 组并重新登录：

```bash
sudo usermod -aG input "$USER"
```

### 3.4 键位表（游戏模式）

| 操作 | 事件 | 行为 |
| --- | --- | --- |
| 上 / 下 | `ABS_Y=0 / 2`，回中 `1` | 前进 `+0.20 m/s` / 后退 `-0.20 m/s` |
| 左 / 右 | `ABS_X=0 / 2`，回中 `1` | 左转 `+0.40 rad/s` / 右转 `-0.40 rad/s` |
| A | `BTN_WEST` 308 | 向左平移 `+0.20 m/s` |
| B | `BTN_SOUTH` 304 | 向右平移 `-0.20 m/s` |
| C | `BTN_NORTH` 307 | 招手（预制动作 3001） |
| D | `BTN_EAST` 305 | 碰拳（预制动作 3003） |
| O | 310 | 站起 / 趴下序列 |
| M | — | 只用于切换模式，不映射功能 |

方向键是“拨到方向持续运动，回中停车”，不是按住才动。A/B 是按住生效、松开停车；相反方向同时按下时该通道为零。

不同批次或固件的键码可能不同。以 `run_key_capture.sh` 的实测结果为准，必要时修改 `config/remotes.json`。

## 4. 安装

### 4.1 准备官方 SDK

向启元售后获取与机器人固件匹配的 Q1 SDK 压缩包，解压到机器人或开发 PC 的全英文路径，例如：

```bash
cd ~
tar -xf primebot-q1-sdk-*.tar.gz
cd primebot-q1-sdk-main
source /opt/ros/humble/setup.bash
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
```

确认 `~/primebot-q1-sdk-main/install/setup.bash` 存在。构建必须在实际运行程序的机器上进行：机器人的板卡是 aarch64，不能直接复制 PC 上的 `build/`、`install/`。

### 4.2 获取本项目

把仓库放到 SDK 同级目录，或任意全英文、无空格路径：

```bash
cd ~
git clone <本项目仓库地址> q1_bluetooth_remote
```

机器人不能联网时，在开发 PC 上克隆后复制到板卡：

```bash
scp -r q1_bluetooth_remote <SSH_USER>@<SOC1_IP>:~/
```

目录布局建议：

```text
~
├── primebot-q1-sdk-main/   # 官方 SDK
└── q1_bluetooth_remote/    # 本项目
```

如果 SDK 不在同级目录，运行前设置：

```bash
export Q1_SDK_ROOT=/absolute/path/to/primebot-q1-sdk-main
```

脚本按以下顺序查找 SDK：`Q1_SDK_ROOT` → 同级 `primebot-q1-sdk-main` → `deps/primebot_sdk`。

### 4.3 写入遥控器地址

```bash
cd ~/q1_bluetooth_remote
cp config/remotes.example.json config/remotes.json
chmod 600 config/remotes.json
```

编辑 `config/remotes.json`：

- 把两处 `<R1_BT_ADDR>` 替换为手柄真实蓝牙地址，例如 `AA:BB:CC:DD:EE:FF`。
- `active_address` 和 `profiles` 里的地址必须一致。
- `inputs` 必须与 `/proc/bus/input/devices` 中的 `Name=` 完全一致，默认 `Magicsee R1`。
- 如果使用了不同的输入源名，同步修改 `input_source`。

`config/remotes.json` 含真实蓝牙地址，已被 `.gitignore` 忽略，不要提交。

### 4.4 构建

```bash
./scripts/build.sh
```

构建成功后会输出可用的启动脚本。如果报“请设置 Q1_SDK_ROOT”，说明 SDK 路径不对或尚未编译。

### 4.5 部署到机器人（可选）

直接在机器人上安装并运行，可以避免 PC 与机器人之间的网络和 DDS 问题。

1. 把 SDK 和本项目复制到机器人板卡：

   ```bash
   scp -r primebot-q1-sdk-main q1_bluetooth_remote <SSH_USER>@<SOC1_IP>:~/
   ```

2. SSH 登录机器人，按 4.1 在板卡上重新构建 SDK，再按 4.2–4.4 构建设备本项目。
3. 如果希望开机自启，继续第 6 节。

## 5. 运行

### 5.1 无运动试跑

```bash
./scripts/run_walk_control.sh
```

该模式只读取手柄并打印目标速度，不注册输入源、不发布速度、不切换运控 Action。适合确认手柄、键位和配置是否正确。

### 5.2 实机运行

确认机器人周围安全、已准备急停后：

```bash
./scripts/run_walk_control.sh --ros-args -p execute:=true
```

启动过程：

1. 按配置的名字和蓝牙地址找到唯一输入节点；找不到会直接退出。
2. 机器人站立时切到 `BIPED_WALK_RUN`；趴下时保持趴下并等待 O 序列。
3. 注册输入源 `magicsee_r1`，禁用 `rc`，发送几次零速度。
4. 复核控制权，通过后开始 50 Hz 发布速度。

机器人开始运动后，日志会打印每个按键和当前目标速度。`Ctrl+C` 退出时会发送零速度并释放输入源；如果机器人仍在站立/走跑，`rc` 会保持禁用。

### 5.3 动作序列

**站起 / 趴下**（O 键）：

1. 短按 O，并在 0.8 秒内松开。
2. 1.5 秒内再次按住 O 约 2 秒。
3. 机器人语音询问“是否执行站起/趴下”，日志同时打印提示。
4. 松开 O。
5. 15 秒内短按 O 确认；超时自动取消。

趴下时该序列执行 `STAND_UP`，等待进入 `BIPED_WALK_RUN`；站立时执行 `LIE_FACE_DOWN`，等待进入 `PASSIVE_DEFAULT`。语音服务不可用时仍可看日志完成确认，不会跳过二次确认。

**招手 / 碰拳**（C / D）：

- 仅在站立状态生效。
- 触发前先停车，切到 `BIPED_WHOLE_BODY_CTRL`，再调用预制动作。
- `interrupt=false`，不会打断正在播放的其他动画。
- 动作结束后控制器不会自动切回走跑；要继续走路，`Ctrl+C` 后重新运行控制器，它会重新进入 `BIPED_WALK_RUN`。

### 5.4 参数

通过 `--ros-args -p 名称:=值` 传入：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `execute` | `false` | `true` 才驱动机器人 |
| `remote_address` | 配置中的 `active_address` | 临时指定遥控器地址 |
| `device` | 空 | 手动指定输入节点，如 `/dev/input/event1` |
| `input_source` | 档案中的 `magicsee_r1` | 运控输入源名称 |
| `priority` | `30` | 输入源优先级 |
| `event_timeout` | `0`（关闭） | 无新事件多少秒后自动停车；建议实机设为 `1.0` |
| `forward_speed` | `0.20` | 前进/后退速度上限，m/s |
| `lateral_speed` | `0.20` | 横移速度上限，m/s |
| `angular_speed` | `0.40` | 转向速度上限，rad/s |
| `forward_acceleration` | `0.50` | 前后加速度平滑 |
| `lateral_acceleration` | `0.50` | 横移加速度平滑 |
| `angular_acceleration` | `1.00` | 转向加速度平滑 |
| `action_hold_time` | 档案中的 `hold_seconds`（2 秒） | O 键长按时间 |
| `confirmation_timeout` | `15` | 动作确认等待，秒 |

速度参数只能调低，超过默认上限会被限制回默认值。

示例：降低速度并启用 1 秒无事件停车：

```bash
./scripts/run_walk_control.sh --ros-args -p execute:=true \
  -p forward_speed:=0.1 -p lateral_speed:=0.1 -p angular_speed:=0.2 \
  -p event_timeout:=1.0
```

### 5.5 遥控器档案

`config/remotes.json` 按蓝牙地址保存按键和轴映射。常用命令：

```bash
./scripts/remote_profiles.sh list
./scripts/remote_profiles.sh show
./scripts/remote_profiles.sh use <R1_BT_ADDR>
./scripts/remote_profiles.sh set-key <R1_BT_ADDR> lateral_left none
```

`set-key` 的功能名为 `forward`、`backward`、`turn_left`、`turn_right`、`lateral_right`、`lateral_left`，键码用 Linux 十进制值。修改后重启控制器生效。

## 6. 语音启动与开机自启

### 6.1 安装监督服务

`remote_supervisor` 订阅机器人语音识别结果，负责连接手柄并拉起控制器。安装脚本会：

1. 构建并把项目部署到 `/robot/software/r1_remote`。
2. 备份 process_manager 配置到 `/robot/persist/config/`。
3. 把 `r1_remote` 加入第二阶段开机启动列表。

在机器人上执行：

```bash
export Q1_SDK_ROOT=/path/to/primebot-q1-sdk-main
sudo Q1_SDK_ROOT="$Q1_SDK_ROOT" ./scripts/install_remote_supervisor.sh
```

脚本需要写入 `/robot/software`、`/robot/persist/config` 和 process_manager 配置。`sudo` 默认不继承环境变量，所以要在命令里显式带上 `Q1_SDK_ROOT`。脚本内部还会构建一次，建议先用普通用户执行 `./scripts/build.sh` 确认构建通过；用 root 构建可能留下 root 权限的 `build/`、`install/`，必要时执行 `sudo chown -R "$USER":"$USER" build install log`。

不同固件的配置路径可能不同，可用 `Q1_PROCESS_CONFIG` 覆盖：

```bash
sudo Q1_SDK_ROOT="$Q1_SDK_ROOT" Q1_PROCESS_CONFIG=/path/to/q1_*_config.yaml \
  ./scripts/install_remote_supervisor.sh
```

如果提示找不到预期的启动阶段，说明固件配置格式不同，脚本不会修改文件；请按官方 SDK 的板载模块接入指南手动添加启动项。

安装后**下次开机生效**。开机只启动监督服务，不会自动连接手柄，也不会自动运动。

### 6.2 语音指令

| 说法 | 作用 |
| --- | --- |
| 启动R1遥控 / 启动R1遥控器 | 连接已绑定的手柄并启动控制器 |
| 绑定蓝牙遥控器 / 绑定遥控器 / 绑定蓝牙手柄 / 绑定手柄 | 首次绑定：搜索 → 询问 → 确认 |
| 确认连接 / 确认 / 确定 / 是 | 确认绑定 |
| 取消 / 取消绑定 / 取消连接 | 取消当前绑定操作 |

首次使用：先说“绑定蓝牙遥控器”，确认连接成功后，再说“启动R1遥控”。

注意：

- “启动R1遥控”只连接已绑定的手柄；未绑定时会提示先绑定。
- 不要用“连接蓝牙遥控器”代替“启动R1遥控”。云端语音服务可能把它识别成设备绑定任务，弹出验证码流程。
- 云端仍可能把自定义短语当普通问答并播报无关内容。监督服务会在收到指令后的 12 秒内拦截非本项目播报，自己的提示不受影响。
- 语音启动成功后如果按键没反应，先检查手柄是否还在游戏模式。

### 6.3 日志与卸载

监督服务输出：

```bash
tail -f /tmp/r1_remote.err
```

ROS 节点日志在 `~/.ros/log/`。

卸载：

1. 恢复最近一次 process_manager 配置备份：

   ```bash
   ls -t /robot/persist/config/q1_*_config.yaml.*.bak | head
   sudo cp <备份文件> /robot/software/process_manager/bin/cfg/q1_v2d0_soc1_config.yaml
   ```

2. 删除部署目录：

   ```bash
   sudo rm -rf /robot/software/r1_remote
   ```

3. 重启机器人。如需解除手柄配对，执行 `bluetoothctl remove <R1_BT_ADDR>`。

## 7. 常见问题

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 提示“未找到唯一输入节点” | 手柄未连接、名字或地址不匹配 | `bluetoothctl info` 确认已连接；`/proc/bus/input/devices` 核对 `Name=` 和 `Uniq`；必要时改 `inputs` |
| 语音启动成功但按键无反应 | 手柄不在游戏模式 | 按说明书 `M + A/B/C/D` 切到游戏模式 |
| 进入走跑后自动前进 | 系统 `rc` 读取了同一手柄 | 确认日志里 `rc` 已禁用；不要同时开 APP 遥控；必要时重启机器人 |
| 无法进入 `BIPED_WALK_RUN` | 机器人不在可站立状态，或运控服务异常 | 让机器人稳定站立或趴下；`ros2 service list` 检查运控服务 |
| 服务不存在或超时 | 开发者模式未生效、SDK 与固件不匹配 | 重新上下电；用匹配版本的 SDK 重新构建 |
| 构建报 `Q1_SDK_ROOT` | SDK 路径错误或未编译 | 设置正确路径，确认 `$Q1_SDK_ROOT/install/setup.bash` |
| 采集按键提示权限不足 | 当前用户不能读 `/dev/input` | 加入 `input` 组后重新登录 |
| 机器人不停 | 松开事件丢失、手柄断连 | 立即用独立急停；下次运行加 `event_timeout:=1.0` |
| 语音指令没反应 | 云端 NLU 抢答或未识别 | 看 `/tmp/r1_remote.err`；使用 6.2 节的标准说法 |

## 8. 兼容性

- 只支持 **Magicsee R1** 蓝牙游戏手柄，且必须处于**游戏模式**。
- 不同固件或批次可能上报不同设备名或键码。用 `run_key_capture.sh` 实测后修改 `config/remotes.json`。
- 方向轴只提供 `0 / 1 / 2` 三档，不是连续模拟量，因此不支持按摇杆幅度调速。
- 手柄的 A+B、M+O 等组合键在实测中只上报后按下的一个键，所以站起/趴下采用 O 键“短按 + 长按 + 短按确认”的序列，而不是组合键。
- 本项目不控制头部、手臂、灯光和语音对话，只使用走跑、输入源、Action 和预制动作接口。

## 9. 目录结构

```text
q1_bluetooth_remote/
├── config/
│   ├── remotes.example.json   # 脱敏配置模板（只含 R1）
│   └── remotes.json           # 本地真实配置，已被 Git 忽略
├── src/
│   ├── q1_cpp_template/       # C++ BMS 只读示例
│   ├── q1_python_template/    # Python BMS 只读示例
│   └── q1_bluetooth_remote/   # 手柄采集、运动控制、语音监督
├── scripts/
│   ├── env.sh                 # 加载 ROS 2 与 Q1 SDK 环境
│   ├── build.sh               # 构建工作区
│   ├── run_key_capture.sh     # 采集手柄按键
│   ├── remote_profiles.sh     # 管理遥控器档案
│   ├── run_walk_control.sh    # 运行运动控制器
│   ├── run_remote_supervisor.sh   # 手动运行语音监督服务
│   ├── start_remote_supervisor.sh # 板载 process_manager 启动入口
│   └── install_remote_supervisor.sh # 部署开机语音监督服务
├── docs/
│   └── R1遥控器验证记录.md    # 实机键位、模式与限制
├── LICENSE                    # Apache License 2.0
├── NOTICE                     # 引用与版权声明
└── README.md
```

## 10. 许可

- 本项目源代码、脚本和文档采用 [Apache License 2.0](LICENSE) 授权。
- 依赖与引用说明见 [NOTICE](NOTICE)。官方 SDK 不随本仓库分发。
- 使用前请阅读启元官方《友好用户使用声明》，实机操作必须遵守其中的安全规范。
