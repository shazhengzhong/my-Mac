#!/bin/bash
# 自动提交并推送到 GitHub

cd ~/logistics-printer

# 添加所有修改
git add -A

# 检查是否有修改
if git diff --cached --quiet; then
    echo "没有需要提交的修改"
    exit 0
fi

# 自动提交（带时间戳）
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
git commit -m "自动提交：$TIMESTAMP"

# 推送到 GitHub
git push

echo "✅ 已提交并推送到 GitHub"
