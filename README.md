# 常熟市中伟物流有限公司 - 运输单打印软件

## 功能

- 浏览器界面填写运输单信息
- 直接打印到 HP Smart Tank 510（A4 纸）
- 保存历史记录，支持重新打印
- 支持打印多份

## 技术栈

- Python 3（内置 http.server）
- HTML/CSS/JavaScript（浏览器界面）
- SQLite（数据存储）
- PostScript（打印输出）

## 使用方法

### 1. 启动程序

```bash
cd ~/logistics-printer
./run.sh
```

或

```bash
/usr/bin/python3 server.py
```

程序会自动打开浏览器窗口。

### 2. 填写运单

- 在"新建运单"页面填写信息
- 货物明细最多 2 行
- 选择打印机和份数
- 点击"保存并打印"

### 3. 历史记录

- 点击"历史记录"标签页查看已保存的运单
- 点击记录可加载到表单
- 点击"打印"按钮可直接重新打印

## 文件结构

```
logistics-printer/
├── server.py         # Web 服务器
── index.html        # 浏览器界面
├── printer.py        # 打印逻辑
── database.py       # 数据存储
├── run.sh            # 启动脚本
├── waybills.db       # 历史数据（自动生成）
└── README.md         # 说明文档
```

## 注意事项

- 纸张：A4
- 打印机：HP Smart Tank 510
- 首次使用可能需要调整打印位置（修改 printer.py 中的坐标）
- 服务端口：8899（如被占用可修改 server.py 中的 PORT）
