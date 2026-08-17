"""Tkinter UI for waybill printing."""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import json

from database import save_waybill, get_recent_waybills, get_waybill
from printer import print_waybill, list_printers


class WaybillApp:
    """Main application window."""

    def __init__(self, root):
        self.root = root
        self.root.title("常熟市中伟物流有限公司 - 运输单打印")
        self.root.geometry("900x700")

        # Printer selection
        self.printer_var = tk.StringVar()
        self.copies_var = tk.IntVar(value=1)

        self._create_widgets()
        self._load_printers()
        self._load_recent()

    def _create_widgets(self):
        """Create all UI widgets."""
        # Top frame: printer settings
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="打印机:").pack(side=tk.LEFT)
        self.printer_combo = ttk.Combobox(top_frame, textvariable=self.printer_var, width=30)
        self.printer_combo.pack(side=tk.LEFT, padx=5)

        ttk.Label(top_frame, text="份数:").pack(side=tk.LEFT, padx=(20, 0))
        ttk.Spinbox(top_frame, from_=1, to=10, textvariable=self.copies_var, width=5).pack(side=tk.LEFT, padx=5)

        ttk.Button(top_frame, text="刷新打印机", command=self._load_printers).pack(side=tk.LEFT, padx=5)

        # Notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Tab 1: New Waybill
        new_tab = ttk.Frame(notebook, padding=10)
        notebook.add(new_tab, text="新建运单")
        self._create_new_waybill_tab(new_tab)

        # Tab 2: History
        history_tab = ttk.Frame(notebook, padding=10)
        notebook.add(history_tab, text="历史记录")
        self._create_history_tab(history_tab)

    def _create_new_waybill_tab(self, parent):
        """Create the new waybill input form."""
        # Basic info frame
        basic_frame = ttk.LabelFrame(parent, text="基本信息", padding=10)
        basic_frame.pack(fill=tk.X, pady=5)

        # Row 1
        row1 = ttk.Frame(basic_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="运单号:", width=10).pack(side=tk.LEFT)
        self.waybill_no = ttk.Entry(row1, width=20)
        self.waybill_no.pack(side=tk.LEFT, padx=5)
        ttk.Label(row1, text="日期:", width=6).pack(side=tk.LEFT, padx=(20, 0))
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y年%m月%d日"))
        ttk.Entry(row1, textvariable=self.date_var, width=20).pack(side=tk.LEFT, padx=5)

        # Row 2
        row2 = ttk.Frame(basic_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="始发站:", width=10).pack(side=tk.LEFT)
        self.departure_station = ttk.Entry(row2, width=20)
        self.departure_station.pack(side=tk.LEFT, padx=5)
        ttk.Label(row2, text="到达站:", width=10).pack(side=tk.LEFT, padx=(20, 0))
        self.arrival_station = ttk.Entry(row2, width=20)
        self.arrival_station.pack(side=tk.LEFT, padx=5)

        # Shipper info
        shipper_frame = ttk.LabelFrame(parent, text="托运方信息", padding=10)
        shipper_frame.pack(fill=tk.X, pady=5)

        row3 = ttk.Frame(shipper_frame)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="托运单位:", width=10).pack(side=tk.LEFT)
        self.shipper = ttk.Entry(row3, width=30)
        self.shipper.pack(side=tk.LEFT, padx=5)
        ttk.Label(row3, text="电话:", width=6).pack(side=tk.LEFT, padx=(20, 0))
        self.shipper_phone = ttk.Entry(row3, width=20)
        self.shipper_phone.pack(side=tk.LEFT, padx=5)

        row4 = ttk.Frame(shipper_frame)
        row4.pack(fill=tk.X, pady=2)
        ttk.Label(row4, text="单位地址:", width=10).pack(side=tk.LEFT)
        self.shipper_address = ttk.Entry(row4, width=50)
        self.shipper_address.pack(side=tk.LEFT, padx=5)

        # Receiver info
        receiver_frame = ttk.LabelFrame(parent, text="收货方信息", padding=10)
        receiver_frame.pack(fill=tk.X, pady=5)

        row5 = ttk.Frame(receiver_frame)
        row5.pack(fill=tk.X, pady=2)
        ttk.Label(row5, text="收货单位:", width=10).pack(side=tk.LEFT)
        self.receiver = ttk.Entry(row5, width=30)
        self.receiver.pack(side=tk.LEFT, padx=5)

        row6 = ttk.Frame(receiver_frame)
        row6.pack(fill=tk.X, pady=2)
        ttk.Label(row6, text="单位地址:", width=10).pack(side=tk.LEFT)
        self.receiver_address = ttk.Entry(row6, width=50)
        self.receiver_address.pack(side=tk.LEFT, padx=5)

        row7 = ttk.Frame(receiver_frame)
        row7.pack(fill=tk.X, pady=2)
        ttk.Label(row7, text="联系人/电话:", width=10).pack(side=tk.LEFT)
        self.contact = ttk.Entry(row7, width=50)
        self.contact.pack(side=tk.LEFT, padx=5)

        # Cargo info
        cargo_frame = ttk.LabelFrame(parent, text="货物明细（最多 2 行）", padding=10)
        cargo_frame.pack(fill=tk.X, pady=5)

        # Headers
        headers = ["货物名称", "包装", "数量", "重量/体积", "运费", "提货费", "送货费", "保价", "保险费", "合计"]
        header_frame = ttk.Frame(cargo_frame)
        header_frame.pack(fill=tk.X)
        self.cargo_entries = []
        widths = [15, 8, 8, 12, 10, 8, 8, 10, 10, 10]
        for i, (h, w) in enumerate(zip(headers, widths)):
            ttk.Label(header_frame, text=h, width=w).pack(side=tk.LEFT, padx=2)

        # 2 rows of cargo entries
        for row_idx in range(2):
            row_frame = ttk.Frame(cargo_frame)
            row_frame.pack(fill=tk.X, pady=2)
            row_entries = []
            for w in widths:
                entry = ttk.Entry(row_frame, width=w)
                entry.pack(side=tk.LEFT, padx=2)
                row_entries.append(entry)
            self.cargo_entries.append(row_entries)

        # Bottom info
        bottom_frame = ttk.LabelFrame(parent, text="费用及其他", padding=10)
        bottom_frame.pack(fill=tk.X, pady=5)

        row8 = ttk.Frame(bottom_frame)
        row8.pack(fill=tk.X, pady=2)
        ttk.Label(row8, text="总运费（大写）:", width=12).pack(side=tk.LEFT)
        self.total_freight_words = ttk.Entry(row8, width=30)
        self.total_freight_words.pack(side=tk.LEFT, padx=5)
        ttk.Label(row8, text="小写¥:", width=8).pack(side=tk.LEFT, padx=(20, 0))
        self.total_freight_digits = ttk.Entry(row8, width=15)
        self.total_freight_digits.pack(side=tk.LEFT, padx=5)

        row9 = ttk.Frame(bottom_frame)
        row9.pack(fill=tk.X, pady=2)
        ttk.Label(row9, text="付款方式:", width=10).pack(side=tk.LEFT)
        self.payment_method = ttk.Entry(row9, width=20)
        self.payment_method.pack(side=tk.LEFT, padx=5)

        row10 = ttk.Frame(bottom_frame)
        row10.pack(fill=tk.X, pady=2)
        ttk.Label(row10, text="备注:", width=10).pack(side=tk.LEFT)
        self.remarks = ttk.Entry(row10, width=50)
        self.remarks.pack(side=tk.LEFT, padx=5)

        # Action buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="保存并打印", command=self._save_and_print).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="清空表单", command=self._clear_form).pack(side=tk.RIGHT, padx=5)

    def _create_history_tab(self, parent):
        """Create the history list tab."""
        # List frame
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True)

        # Treeview
        columns = ("ID", "运单号", "托运单位", "收货单位", "日期", "创建时间")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
        self.tree.column("ID", width=50)
        self.tree.column("创建时间", width=150)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Double-click to load
        self.tree.bind("<Double-1>", self._on_history_select)

        # Buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="刷新列表", command=self._load_recent).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="打印选中", command=self._print_selected).pack(side=tk.RIGHT, padx=5)

    def _load_printers(self):
        """Load available printers."""
        printers = list_printers()
        self.printer_combo["values"] = printers
        if printers:
            # Try to find HP printer
            for p in printers:
                if "HP" in p.upper() or "SMART" in p.upper():
                    self.printer_var.set(p)
                    return
            self.printer_var.set(printers[0])

    def _load_recent(self):
        """Load recent waybills into history tree."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Load from database
        waybills = get_recent_waybills()
        for wb in waybills:
            self.tree.insert("", tk.END, values=(
                wb["id"],
                wb["waybill_no"],
                wb["shipper"],
                wb["receiver"],
                wb["date"],
                wb["created_at"],
            ))

    def _get_form_data(self) -> dict:
        """Collect data from form."""
        cargo_data = []
        for row_entries in self.cargo_entries:
            row_data = {
                "name": row_entries[0].get(),
                "package": row_entries[1].get(),
                "quantity": row_entries[2].get(),
                "weight_volume": row_entries[3].get(),
                "freight": row_entries[4].get(),
                "pickup_fee": row_entries[5].get(),
                "delivery_fee": row_entries[6].get(),
                "insurance_value": row_entries[7].get(),
                "insurance_fee": row_entries[8].get(),
                "total": row_entries[9].get(),
            }
            # Only add if at least one field has data
            if any(v for v in row_data.values()):
                cargo_data.append(row_data)

        return {
            "waybill_no": self.waybill_no.get(),
            "departure_station": self.departure_station.get(),
            "arrival_station": self.arrival_station.get(),
            "date": self.date_var.get(),
            "shipper": self.shipper.get(),
            "shipper_address": self.shipper_address.get(),
            "shipper_phone": self.shipper_phone.get(),
            "receiver": self.receiver.get(),
            "receiver_address": self.receiver_address.get(),
            "contact": self.contact.get(),
            "cargo_data": json.dumps(cargo_data, ensure_ascii=False),
            "total_freight_words": self.total_freight_words.get(),
            "total_freight_digits": self.total_freight_digits.get(),
            "payment_method": self.payment_method.get(),
            "remarks": self.remarks.get(),
        }

    def _save_and_print(self):
        """Save form data and print."""
        data = self._get_form_data()

        # Validate required fields
        if not data["shipper"] and not data["receiver"]:
            messagebox.showwarning("提示", "请至少填写托运单位或收货单位")
            return

        # Save to database
        waybill_id = save_waybill(data)
        print(f"✅ 已保存，ID: {waybill_id}")

        # Print
        printer = self.printer_var.get()
        copies = self.copies_var.get()
        if printer:
            success = print_waybill(data, printer_name=printer, copies=copies)
            if success:
                messagebox.showinfo("成功", f"打印成功！\n已保存到历史记录 (ID: {waybill_id})")
                self._load_recent()
            else:
                messagebox.showerror("失败", "打印失败，请检查打印机连接")
        else:
            messagebox.showwarning("提示", "请先选择打印机")

    def _clear_form(self):
        """Clear all form fields."""
        self.waybill_no.delete(0, tk.END)
        self.departure_station.delete(0, tk.END)
        self.arrival_station.delete(0, tk.END)
        self.date_var.set(datetime.now().strftime("%Y年%m月%d日"))
        self.shipper.delete(0, tk.END)
        self.shipper_address.delete(0, tk.END)
        self.shipper_phone.delete(0, tk.END)
        self.receiver.delete(0, tk.END)
        self.receiver_address.delete(0, tk.END)
        self.contact.delete(0, tk.END)
        for row_entries in self.cargo_entries:
            for entry in row_entries:
                entry.delete(0, tk.END)
        self.total_freight_words.delete(0, tk.END)
        self.total_freight_digits.delete(0, tk.END)
        self.payment_method.delete(0, tk.END)
        self.remarks.delete(0, tk.END)

    def _on_history_select(self, event):
        """Load selected history item into form."""
        selection = self.tree.selection()
        if not selection:
            return
        item = self.tree.item(selection[0])
        waybill_id = item["values"][0]

        data = get_waybill(waybill_id)
        if not data:
            return

        # Fill form
        self._clear_form()
        self.waybill_no.insert(0, data["waybill_no"] or "")
        self.departure_station.insert(0, data["departure_station"] or "")
        self.arrival_station.insert(0, data["arrival_station"] or "")
        self.date_var.set(data["date"] or "")
        self.shipper.insert(0, data["shipper"] or "")
        self.shipper_address.insert(0, data["shipper_address"] or "")
        self.shipper_phone.insert(0, data["shipper_phone"] or "")
        self.receiver.insert(0, data["receiver"] or "")
        self.receiver_address.insert(0, data["receiver_address"] or "")
        self.contact.insert(0, data["contact"] or "")

        # Cargo data
        try:
            cargo_data = json.loads(data["cargo_data"] or "[]")
            for i, cargo in enumerate(cargo_data):
                if i < len(self.cargo_entries):
                    row_entries = self.cargo_entries[i]
                    row_entries[0].insert(0, cargo.get("name", ""))
                    row_entries[1].insert(0, cargo.get("package", ""))
                    row_entries[2].insert(0, cargo.get("quantity", ""))
                    row_entries[3].insert(0, cargo.get("weight_volume", ""))
                    row_entries[4].insert(0, cargo.get("freight", ""))
                    row_entries[5].insert(0, cargo.get("pickup_fee", ""))
                    row_entries[6].insert(0, cargo.get("delivery_fee", ""))
                    row_entries[7].insert(0, cargo.get("insurance_value", ""))
                    row_entries[8].insert(0, cargo.get("insurance_fee", ""))
                    row_entries[9].insert(0, cargo.get("total", ""))
        except json.JSONDecodeError:
            pass

        self.total_freight_words.insert(0, data["total_freight_words"] or "")
        self.total_freight_digits.insert(0, data["total_freight_digits"] or "")
        self.payment_method.insert(0, data["payment_method"] or "")
        self.remarks.insert(0, data["remarks"] or "")

        # Switch to new waybill tab
        self.root.nametowidget(".!notebook").select(0)

    def _print_selected(self):
        """Print selected history item."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一条记录")
            return
        item = self.tree.item(selection[0])
        waybill_id = item["values"][0]

        data = get_waybill(waybill_id)
        if not data:
            messagebox.showerror("错误", "记录不存在")
            return

        printer = self.printer_var.get()
        copies = self.copies_var.get()
        if printer:
            success = print_waybill(data, printer_name=printer, copies=copies)
            if success:
                messagebox.showinfo("成功", "打印成功！")
            else:
                messagebox.showerror("失败", "打印失败")
        else:
            messagebox.showwarning("提示", "请先选择打印机")


def main():
    """Launch the application."""
    root = tk.Tk()
    app = WaybillApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
