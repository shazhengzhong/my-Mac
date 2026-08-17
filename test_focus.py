#!/usr/bin/env python3
"""Test UI with force focus."""
import tkinter as tk
from tkinter import ttk
import subprocess
import time

root = tk.Tk()
root.title("测试窗口 - 强制显示")
root.geometry("600x400+100+100")  # 明确位置

# 强制窗口到前台
root.attributes('-topmost', True)
root.lift()
root.focus_force()

# 添加内容
label = ttk.Label(root, text="这是一个测试窗口", font=('Arial', 16))
label.pack(pady=50)

btn = ttk.Button(root, text="点击我", command=lambda: print("按钮被点击"))
btn.pack(pady=20)

# 用 AppleScript 强制激活
time.sleep(0.5)
try:
    subprocess.run(['osascript', '-e', 'tell application "Python" to activate'], timeout=2)
except:
    pass

print("窗口已创建，应该显示在屏幕上")
root.mainloop()
