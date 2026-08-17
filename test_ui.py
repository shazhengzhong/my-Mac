#!/usr/bin/env python3
"""Simple test UI."""
import tkinter as tk
from tkinter import ttk

root = tk.Tk()
root.title("测试 - 运输单打印")
root.geometry("800x600")

# Top frame
top_frame = ttk.Frame(root, padding=10)
top_frame.pack(fill=tk.X)
ttk.Label(top_frame, text="打印机:").pack(side=tk.LEFT)

# Notebook
notebook = ttk.Notebook(root)
notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

# Tab 1
tab1 = ttk.Frame(notebook, padding=10)
notebook.add(tab1, text="新建运单")
ttk.Label(tab1, text="运单号:").pack()
entry = ttk.Entry(tab1, width=30)
entry.pack()

# Tab 2
tab2 = ttk.Frame(notebook, padding=10)
notebook.add(tab2, text="历史记录")
ttk.Label(tab2, text="暂无记录").pack()

print("窗口创建完成")
root.mainloop()
