# Task Plan: 异环自动钓鱼方案设计

## Goal
为当前 `D:\AF\异环自动钓鱼` Python 项目整理一份完整、可落地的自动钓鱼实现方案，覆盖状态机、图像识别、按键控制、模块划分、调试验证与待补充信息；本轮不编写业务代码。

## Current Phase
Phase 2

## Phases

### Phase 1: Requirements & Discovery
- [x] 理解用户意图与截图中的钓鱼流程
- [x] 识别当前项目约束与现状
- [x] 将发现写入 `findings.md`
- **Status:** complete

### Phase 2: Planning & Structure
- [x] 定义自动钓鱼总体技术路线
- [x] 设计模块结构、配置结构与状态机
- [x] 记录关键技术决策与原因
- **Status:** in_progress

### Phase 3: Implementation Design
- [ ] 拆分识别、控制、调度、日志、调试模块
- [ ] 明确核心算法与伪代码级流程
- [ ] 定义后续代码编写顺序
- **Status:** pending

### Phase 4: Verification Design
- [ ] 设计标定与测试步骤
- [ ] 明确异常场景与回退策略
- [ ] 记录验证指标
- **Status:** pending

### Phase 5: Delivery
- [ ] 汇总方案
- [ ] 列出需要用户补充的信息
- [ ] 向用户交付中文说明
- **Status:** pending

## Key Questions
1. 是否固定使用窗口化/固定分辨率运行游戏，以便使用稳定 ROI？
2. 是否允许使用 OCR，还是更希望优先使用模板匹配与像素条检测？
3. 当前项目目标是仅支持单一钓点/机位，还是希望后续支持多钓点泛化？

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 本轮只输出方案，不写代码 | 用户明确要求现阶段先构思完整 Python 代码编写方案 |
| 先基于屏幕视觉识别 + 键盘模拟设计 | 用户给出的交互完全体现在 UI 和按键层，当前项目也无游戏内接口 |
| 需要建立明确状态机 | 钓鱼流程至少包含待机、抛竿、等待上钩、收杆判定、拉扯控制、结算回收等多状态 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| `git status` 失败：当前目录不是 Git 仓库 | 1 | 记为环境现状，不影响方案设计 |

## Notes
- 当前项目只有一个 `main.py`，内容仍是 PyCharm 默认模板。
- 后续若进入编码阶段，需要优先解决窗口定位、ROI 标定和日志可观测性。
