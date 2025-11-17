# NightReign Overlay Helper - Golang 重构方案

## 项目概述

NightReign Overlay Helper 是一个游戏辅助工具，通过屏幕覆盖层实时显示游戏信息，包括：
- 缩圈阶段和时间检测
- 血量监测
- 地图信息识别
- 绝招技能检测
- 雨天状态识别

当前版本使用 Python + PyQt6 实现，代码量约 4900 行。

## 重构目标

### 为什么选择 Golang

1. **性能提升**
   - 编译型语言，运行效率更高
   - 更低的内存占用
   - 更快的启动速度

2. **部署简化**
   - 单一可执行文件，无需 Python 运行时
   - 跨平台编译更简单
   - 减小分发包大小

3. **并发优势**
   - Goroutine 轻量级并发模型
   - 原生的并发支持，替代 QThread
   - 更好的多核利用率

4. **维护性**
   - 静态类型系统，减少运行时错误
   - 更好的代码补全和 IDE 支持
   - 简洁的语法和标准库

## 技术栈对比

### Python 技术栈 → Golang 技术栈

| 功能模块 | Python | Golang | 备注 |
|---------|--------|--------|------|
| GUI 框架 | PyQt6 | Fyne / Wails | Fyne: 跨平台原生; Wails: Web技术栈 |
| 图像识别 | OpenCV-Python | gocv | OpenCV 的官方 Go 绑定 |
| 屏幕截图 | MSS | kbinani/screenshot | 跨平台截图库 |
| 输入监听 | pynput | robotgo | 键盘鼠标事件监听 |
| 配置管理 | PyYAML | viper | YAML/JSON/TOML 配置 |
| 日志系统 | 自定义 logger | logrus / zap | 结构化日志 |
| 图像处理 | Pillow | gocv / imaging | 图像基础操作 |
| 系统托盘 | QSystemTrayIcon | getlantern/systray | 系统托盘图标 |

## 架构设计

### 模块划分

```
nightreign-overlay-helper/
├── cmd/
│   └── app/
│       └── main.go                 # 程序入口
├── internal/
│   ├── config/
│   │   ├── config.go              # 配置管理
│   │   └── loader.go              # 配置加载
│   ├── detector/
│   │   ├── base.go                # 检测器基础接口
│   │   ├── day_detector.go        # 日期/缩圈检测
│   │   ├── hp_detector.go         # 血量检测
│   │   ├── map_detector.go        # 地图检测
│   │   ├── art_detector.go        # 绝招检测
│   │   ├── rain_detector.go       # 雨天检测
│   │   └── utils.go               # 检测器工具函数
│   ├── ui/
│   │   ├── overlay.go             # 主覆盖层窗口
│   │   ├── map_overlay.go         # 地图覆盖层
│   │   ├── hp_overlay.go          # 血量覆盖层
│   │   ├── settings.go            # 设置窗口
│   │   ├── capture.go             # 截图区域选择
│   │   └── tray.go                # 系统托盘
│   ├── input/
│   │   └── listener.go            # 输入监听器
│   ├── updater/
│   │   └── updater.go             # 后台更新器
│   └── logger/
│       └── logger.go              # 日志系统
├── pkg/
│   └── version/
│       └── version.go             # 版本信息
├── assets/                        # 资源文件
├── data/                          # 数据文件
├── config.yaml                    # 配置文件
├── go.mod
├── go.sum
└── README.md
```

### 核心设计模式

#### 1. 检测器接口设计

```go
// Detector 检测器基础接口
type Detector interface {
    Name() string
    Detect(img image.Image) (interface{}, error)
    Initialize() error
    Cleanup() error
}

// 具体检测器实现
type DayDetector struct {
    config      *config.Config
    templates   map[string]gocv.Mat
    lastResult  *DayResult
}

func (d *DayDetector) Detect(img image.Image) (interface{}, error) {
    // 实现具体检测逻辑
    return result, nil
}
```

#### 2. 并发模型

```go
// 使用 Goroutine 和 Channel 替代 QThread
type Updater struct {
    detectors   []Detector
    stopChan    chan struct{}
    resultChan  chan DetectorResult
}

func (u *Updater) Run() {
    ticker := time.NewTicker(time.Millisecond * 100)
    defer ticker.Stop()

    for {
        select {
        case <-ticker.C:
            // 执行检测
            go u.runDetectors()
        case <-u.stopChan:
            return
        }
    }
}
```

#### 3. 事件总线

```go
// 用于模块间通信
type EventBus struct {
    subscribers map[string][]chan Event
    mu          sync.RWMutex
}

func (eb *EventBus) Subscribe(topic string) <-chan Event
func (eb *EventBus) Publish(topic string, event Event)
```

## 模块迁移计划

### Phase 1: 核心基础设施 (Week 1-2)

- [ ] 项目结构初始化
- [ ] 配置管理模块 (config)
- [ ] 日志系统 (logger)
- [ ] 基础工具函数
- [ ] 版本管理

**预期交付**: 可运行的基础框架，支持配置读取和日志输出

### Phase 2: 检测器层 (Week 3-5)

优先级顺序：

1. **检测器基础框架**
   - [ ] Detector 接口定义
   - [ ] 图像预处理工具
   - [ ] 模板匹配算法

2. **Day Detector (日期检测)**
   - [ ] 移植模板匹配逻辑
   - [ ] 多语言支持 (简中/繁中/英文/日文)
   - [ ] 缩圈时间计算

3. **HP Detector (血量检测)**
   - [ ] 血条区域识别
   - [ ] 颜色空间转换 (HLS)
   - [ ] 雨天状态判断

4. **Rain Detector (雨天检测)**
   - [ ] 血条颜色分析
   - [ ] 状态切换逻辑

5. **Map Detector (地图检测)**
   - [ ] 霍夫圆检测
   - [ ] 地图模式识别
   - [ ] 特殊地形检测

6. **Art Detector (绝招检测)**
   - [ ] 技能图标匹配
   - [ ] 多角色支持
   - [ ] 时间计算

**预期交付**: 所有检测器模块完成，通过单元测试

### Phase 3: UI 层 (Week 6-8)

GUI 框架选型：**Fyne** (推荐) 或 **Wails**

**Fyne 方案**:
- 优势: 真正的原生 Go，无需 Web 技术
- 劣势: 定制化能力有限

**Wails 方案**:
- 优势: 使用 Web 前端技术，UI 更灵活
- 劣势: 包体积较大

#### 实施步骤

1. **基础 UI 组件**
   - [ ] 透明窗口实现
   - [ ] 窗口置顶和鼠标穿透
   - [ ] 系统托盘集成

2. **覆盖层窗口**
   - [ ] 主覆盖层 (Overlay)
   - [ ] 地图覆盖层 (MapOverlay)
   - [ ] 血量覆盖层 (HpOverlay)
   - [ ] 进度条组件
   - [ ] 文本显示

3. **设置窗口**
   - [ ] 界面布局
   - [ ] 配置项绑定
   - [ ] 实时预览
   - [ ] 截图区域选择

4. **输入监听**
   - [ ] 全局热键支持
   - [ ] 鼠标事件监听
   - [ ] 右键菜单

**预期交付**: 完整的 UI 系统，与检测器集成

### Phase 4: 整合与优化 (Week 9-10)

1. **模块整合**
   - [ ] Updater 协调器
   - [ ] 事件总线
   - [ ] 数据流优化

2. **性能优化**
   - [ ] 内存池优化
   - [ ] Goroutine 数量控制
   - [ ] 图像处理性能优化

3. **错误处理**
   - [ ] 完善错误处理
   - [ ] 崩溃恢复机制
   - [ ] Bug 报告功能

**预期交付**: 稳定可用的 Beta 版本

### Phase 5: 测试与发布 (Week 11-12)

1. **测试**
   - [ ] 单元测试覆盖
   - [ ] 集成测试
   - [ ] 性能测试
   - [ ] 跨平台测试

2. **文档**
   - [ ] API 文档
   - [ ] 用户手册
   - [ ] 开发文档

3. **发布**
   - [ ] 构建脚本
   - [ ] CI/CD 配置
   - [ ] 版本发布

**预期交付**: 正式 v1.0 版本

## 关键技术要点

### 1. OpenCV 集成 (gocv)

```go
import "gocv.io/x/gocv"

// 初始化
func init() {
    // 确保 OpenCV 已安装
}

// 模板匹配示例
func templateMatch(img, template gocv.Mat) (float32, image.Point) {
    result := gocv.NewMat()
    defer result.Close()

    gocv.MatchTemplate(img, template, &result, gocv.TmCcoeffNormed, gocv.NewMat())
    _, maxVal, _, maxLoc := gocv.MinMaxLoc(result)

    return maxVal, maxLoc
}
```

### 2. 屏幕截图

```go
import "github.com/kbinani/screenshot"

func captureScreen(monitor int) (image.Image, error) {
    bounds := screenshot.GetDisplayBounds(monitor)
    img, err := screenshot.CaptureRect(bounds)
    return img, err
}
```

### 3. 透明窗口 (Fyne)

```go
import "fyne.io/fyne/v2/app"

func createOverlay() fyne.Window {
    a := app.New()
    w := a.NewWindow("Overlay")

    // 设置窗口属性
    w.SetFixedSize(true)
    w.Resize(fyne.NewSize(800, 100))

    return w
}
```

### 4. 配置管理 (Viper)

```go
import "github.com/spf13/viper"

func loadConfig() (*Config, error) {
    viper.SetConfigName("config")
    viper.SetConfigType("yaml")
    viper.AddConfigPath(".")

    if err := viper.ReadInConfig(); err != nil {
        return nil, err
    }

    var config Config
    if err := viper.Unmarshal(&config); err != nil {
        return nil, err
    }

    return &config, nil
}
```

## 依赖管理

### go.mod 核心依赖

```go
module github.com/yourusername/nightreign-overlay-helper

go 1.21

require (
    fyne.io/fyne/v2 v2.4.0              // GUI 框架
    gocv.io/x/gocv v0.35.0               // OpenCV 绑定
    github.com/kbinani/screenshot v0.0.0 // 屏幕截图
    github.com/robotn/gohook v0.41.0     // 输入监听
    github.com/getlantern/systray v1.2.2 // 系统托盘
    github.com/spf13/viper v1.18.0       // 配置管理
    github.com/sirupsen/logrus v1.9.3    // 日志系统
    gopkg.in/yaml.v3 v3.0.1              // YAML 解析
)
```

### 环境依赖

- **Go**: >= 1.21
- **OpenCV**: >= 4.6.0
- **GCC**: 用于 cgo 编译

## 风险与挑战

### 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| gocv 性能不如 Python OpenCV | 中 | 优化算法，使用 C++ 扩展 |
| GUI 框架学习曲线 | 中 | 选择文档丰富的 Fyne |
| 跨平台兼容性问题 | 高 | 早期多平台测试 |
| OpenCV 安装复杂 | 高 | 提供预编译版本和安装脚本 |

### 迁移风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 功能丢失 | 高 | 详细的功能清单和测试 |
| 用户配置迁移 | 中 | 提供配置转换工具 |
| 性能回退 | 中 | 建立性能基准测试 |

## 预期收益

### 性能指标

| 指标 | Python | Golang (预期) | 提升 |
|------|--------|---------------|------|
| 启动时间 | 3-5s | <1s | 3-5x |
| 内存占用 | 150-200MB | 50-80MB | 2-3x |
| CPU 占用 | 5-10% | 2-5% | 2x |
| 安装包大小 | 80-100MB | 30-50MB | 2x |

### 开发效率

- **类型安全**: 编译期错误检查，减少运行时错误
- **并发简化**: Goroutine 替代复杂的线程管理
- **依赖管理**: Go Modules 更简洁
- **工具链**: 更好的性能分析工具 (pprof)

## 实施建议

### 开发环境配置

```bash
# 1. 安装 Go
# 下载地址: https://golang.org/dl/

# 2. 安装 OpenCV
# macOS
brew install opencv

# Ubuntu/Debian
sudo apt-get install libopencv-dev

# Windows
# 下载预编译包或使用 MSYS2

# 3. 安装 gocv
go get -u gocv.io/x/gocv

# 4. 创建项目
mkdir nightreign-overlay-helper
cd nightreign-overlay-helper
go mod init github.com/yourusername/nightreign-overlay-helper

# 5. 安装依赖
go get fyne.io/fyne/v2
go get github.com/kbinani/screenshot
go get github.com/spf13/viper
```

### 代码风格

- 遵循 [Go Code Review Comments](https://github.com/golang/go/wiki/CodeReviewComments)
- 使用 `gofmt` 格式化代码
- 使用 `golangci-lint` 静态检查

### 测试策略

```bash
# 单元测试
go test ./...

# 测试覆盖率
go test -cover ./...

# 生成覆盖率报告
go test -coverprofile=coverage.out ./...
go tool cover -html=coverage.out
```

## 构建与发布

### 构建脚本

```bash
#!/bin/bash
# build.sh

VERSION=$(git describe --tags --always --dirty)
LDFLAGS="-X main.Version=$VERSION -s -w"

# Windows
GOOS=windows GOARCH=amd64 go build -ldflags="$LDFLAGS" -o dist/nightreign-overlay-helper-windows-amd64.exe ./cmd/app

# Linux
GOOS=linux GOARCH=amd64 go build -ldflags="$LDFLAGS" -o dist/nightreign-overlay-helper-linux-amd64 ./cmd/app

# macOS
GOOS=darwin GOARCH=amd64 go build -ldflags="$LDFLAGS" -o dist/nightreign-overlay-helper-darwin-amd64 ./cmd/app
GOOS=darwin GOARCH=arm64 go build -ldflags="$LDFLAGS" -o dist/nightreign-overlay-helper-darwin-arm64 ./cmd/app
```

### CI/CD (GitHub Actions)

```yaml
name: Build

on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-go@v4
        with:
          go-version: '1.21'

      - name: Install OpenCV
        run: sudo apt-get install libopencv-dev

      - name: Build
        run: go build -v ./...

      - name: Test
        run: go test -v ./...
```

## 项目时间表

| 阶段 | 时间 | 里程碑 |
|------|------|--------|
| Phase 1 | Week 1-2 | 基础框架完成 |
| Phase 2 | Week 3-5 | 检测器完成 |
| Phase 3 | Week 6-8 | UI 完成 |
| Phase 4 | Week 9-10 | 整合优化 |
| Phase 5 | Week 11-12 | 发布 v1.0 |

**总计**: 约 12 周 (3 个月)

## 后续规划

### v1.1 功能

- [ ] 自动更新支持
- [ ] 更多语言支持
- [ ] 云端配置同步
- [ ] 统计数据分析

### v2.0 功能

- [ ] 机器学习模型集成
- [ ] 更智能的检测算法
- [ ] 多游戏支持
- [ ] 社区功能

## 参考资源

### 文档

- [Go 官方文档](https://go.dev/doc/)
- [Fyne 文档](https://developer.fyne.io/)
- [gocv 文档](https://gocv.io/)
- [Viper 文档](https://github.com/spf13/viper)

### 示例项目

- [Fyne 示例](https://github.com/fyne-io/examples)
- [gocv 示例](https://github.com/hybridgroup/gocv/tree/release/cmd)

## 联系方式

- **Bug 报告**: nroh-report@qq.com
- **讨论**: GitHub Issues

---

**文档版本**: v0.9.0
**最后更新**: 2025-11-17
**作者**: Claude Code
