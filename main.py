import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import uuid
from datetime import date, timedelta

try:
    from PIL import Image, ImageTk, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "todos.json")
IMAGES_DIR = os.path.join(BASE_DIR, "images")

os.makedirs(IMAGES_DIR, exist_ok=True)


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, height=150, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bg="#f5f5f5")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg="#f5f5f5")

        self.inner_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.inner.bind("<MouseWheel>", self._on_mousewheel)

    def _on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.inner_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._on_mousewheel)


class TodoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📋 TODO List")
        self.root.geometry("480x720")
        self.root.minsize(460, 560)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#f0f0f0")

        self.filter_var = tk.StringVar(value="全部")
        self.todos = []
        self._pending_images = []   # [(tmp_path, PhotoImage), ...]
        self._click_timer = None    # for single/double click disambiguation

        self.load_data()
        self.build_ui()
        self.refresh_all_views()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        # Clean up any pending temp images that were never saved
        for tmp_path, _ in self._pending_images:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
        self.root.destroy()

    # ── Data ──────────────────────────────────────────────
    def load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                self.todos = json.load(f)
            # Migrate old format (text -> title/content)
            for t in self.todos:
                if "title" not in t:
                    t["title"] = t.get("text", "")
                if "content" not in t:
                    t["content"] = t.get("text", "")
                if "images" not in t:
                    t["images"] = []
        else:
            self.todos = []

    def save_data(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.todos, f, ensure_ascii=False, indent=2)

    def next_id(self):
        return max((t["id"] for t in self.todos), default=0) + 1

    def get_title(self, t):
        return t.get("title") or t.get("text", "(无标题)")

    # ── UI Builder ────────────────────────────────────────
    def build_ui(self):
        self._build_input_area()
        self._build_today_area()
        self._build_all_area()
        self._build_status_bar()

    def _build_input_area(self):
        frame = tk.LabelFrame(self.root, text=" 添加任务 ", bg="#f0f0f0",
                              font=("Microsoft YaHei", 9, "bold"), padx=8, pady=6)
        frame.pack(fill="x", padx=10, pady=(10, 4))

        hint = "第一行为标题   Ctrl+V 可粘贴截图   Ctrl+Enter 添加"
        tk.Label(frame, text=hint, bg="#f0f0f0", fg="#aaa",
                 font=("Microsoft YaHei", 7)).pack(anchor="w", pady=(0, 2))

        self.task_text = tk.Text(frame, height=4, font=("Microsoft YaHei", 10),
                                 wrap="word", relief="solid", bd=1,
                                 bg="white", padx=4, pady=4)
        self.task_text.pack(fill="x", pady=(0, 6))
        self.task_text.bind("<Control-v>", self.paste_image)
        self.task_text.bind("<Control-Return>", lambda e: self.add_todo())

        date_row = tk.Frame(frame, bg="#f0f0f0")
        date_row.pack(fill="x")

        tk.Label(date_row, text="日期:", bg="#f0f0f0",
                 font=("Microsoft YaHei", 9)).pack(side="left")

        self.date_entry = tk.Entry(date_row, width=14, font=("Microsoft YaHei", 10))
        self.date_entry.insert(0, str(date.today()))
        self.date_entry.pack(side="left", padx=(4, 0))

        add_btn = tk.Button(date_row, text="+ 添加", command=self.add_todo,
                            bg="#4CAF50", fg="white", font=("Microsoft YaHei", 9, "bold"),
                            relief="flat", padx=12, cursor="hand2")
        add_btn.pack(side="right")

    def _build_today_area(self):
        lf = tk.LabelFrame(self.root, text=" 今日提醒 ", bg="#f0f0f0",
                           font=("Microsoft YaHei", 9, "bold"), padx=6, pady=4)
        lf.pack(fill="x", padx=10, pady=4)
        self.today_scroll = ScrollableFrame(lf, height=150, bg="#f5f5f5")
        self.today_scroll.pack(fill="both", expand=True)

    def _build_all_area(self):
        outer = tk.Frame(self.root, bg="#f0f0f0")
        outer.pack(fill="both", expand=True, padx=10, pady=(4, 4))

        hdr = tk.Frame(outer, bg="#f0f0f0")
        hdr.pack(fill="x")
        tk.Label(hdr, text=" 全部任务", bg="#f0f0f0",
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        tk.Label(hdr, text="Filter:", bg="#f0f0f0",
                 font=("Microsoft YaHei", 9)).pack(side="right", padx=(0, 4))
        filter_combo = ttk.Combobox(hdr, textvariable=self.filter_var,
                                    values=["全部", "待完成", "已完成"],
                                    state="readonly", width=6,
                                    font=("Microsoft YaHei", 9))
        filter_combo.pack(side="right")
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_all_list())

        lf = tk.LabelFrame(outer, bg="#f0f0f0", padx=6, pady=4)
        lf.pack(fill="both", expand=True, pady=(2, 0))
        self.all_scroll = ScrollableFrame(lf, height=200, bg="#f5f5f5")
        self.all_scroll.pack(fill="both", expand=True)

    def _build_status_bar(self):
        self.status_var = tk.StringVar()
        tk.Label(self.root, textvariable=self.status_var, bg="#ddd",
                 font=("Microsoft YaHei", 8), anchor="w", padx=8).pack(fill="x", side="bottom")

    # ── Image Paste ───────────────────────────────────────
    def paste_image(self, event):
        if not PIL_AVAILABLE:
            return  # fall through to default paste
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image):
                tmp_name = f"tmp_{uuid.uuid4().hex}.png"
                tmp_path = os.path.join(IMAGES_DIR, tmp_name)
                img.save(tmp_path, "PNG")

                # Thumbnail for display in input area
                thumb = img.copy()
                thumb.thumbnail((280, 180))
                photo = ImageTk.PhotoImage(thumb)

                self._pending_images.append((tmp_path, photo))

                self.task_text.image_create(tk.INSERT, image=photo, padx=2, pady=2)
                self.task_text.insert(tk.INSERT, "\n")
                return "break"
        except Exception:
            pass
        # Return None → allow default text paste

    # ── Actions ───────────────────────────────────────────
    def _get_date_str(self):
        val = self.date_entry.get().strip()
        try:
            date.fromisoformat(val)
            return val
        except ValueError:
            return None

    def add_todo(self):
        raw = self.task_text.get("1.0", "end-1c")
        # Strip image placeholder characters (U+FFFC inserted by tkinter)
        content = raw.replace("\ufffc", "").strip()

        has_images = bool(self._pending_images)
        if not content and not has_images:
            messagebox.showwarning("提示", "请输入任务内容")
            return

        date_str = self._get_date_str()
        if not date_str:
            messagebox.showwarning("提示", "日期格式错误，请使用 YYYY-MM-DD")
            return

        first_line = next((ln.strip() for ln in content.split("\n") if ln.strip()), "")
        title = (first_line[:50] if first_line else "(图片任务)")

        task_id = self.next_id()

        # Finalize images: rename tmp → {id}_{n}.png
        images = []
        for i, (tmp_path, _) in enumerate(self._pending_images):
            new_name = f"{task_id}_{i}.png"
            new_path = os.path.join(IMAGES_DIR, new_name)
            try:
                if os.path.exists(tmp_path):
                    os.rename(tmp_path, new_path)
                    images.append(os.path.join("images", new_name))
            except OSError:
                pass

        self.todos.append({
            "id": task_id,
            "title": title,
            "content": content,
            "images": images,
            "done": False,
            "date": date_str,
        })
        self.save_data()

        # Reset input
        self.task_text.delete("1.0", tk.END)
        self._pending_images.clear()
        self.date_entry.delete(0, "end")
        self.date_entry.insert(0, str(date.today()))

        self.refresh_all_views()

    def mark_done(self, todo_id):
        for t in self.todos:
            if t["id"] == todo_id:
                t["done"] = True
                break
        self.save_data()
        self.refresh_all_views()

    def delete_todo(self, todo_id):
        t = next((x for x in self.todos if x["id"] == todo_id), None)
        if t:
            for img_rel in t.get("images", []):
                try:
                    os.remove(os.path.join(BASE_DIR, img_rel))
                except OSError:
                    pass
        self.todos = [x for x in self.todos if x["id"] != todo_id]
        self.save_data()
        self.refresh_all_views()

    # ── Detail Popup ──────────────────────────────────────
    def show_detail(self, todo_id):
        t = next((x for x in self.todos if x["id"] == todo_id), None)
        if not t:
            return

        win = tk.Toplevel(self.root)
        win.title("任务详情")
        win.geometry("500x580")
        win.minsize(420, 420)
        win.attributes("-topmost", True)
        win.configure(bg="#f0f0f0")
        win._photo_refs = []
        win._image_map = {}   # str(photo) → absolute file path (for double-click open)

        # ── Header (editable) ──
        hdr = tk.Frame(win, bg="#f0f0f0", padx=12, pady=10)
        hdr.pack(fill="x")

        tk.Label(hdr, text="标题", bg="#f0f0f0", fg="#888",
                 font=("Microsoft YaHei", 8)).pack(anchor="w")
        title_var = tk.StringVar(value=self.get_title(t))
        title_entry = tk.Entry(hdr, textvariable=title_var,
                               font=("Microsoft YaHei", 12, "bold"),
                               relief="solid", bd=1, bg="white")
        title_entry.pack(fill="x", pady=(2, 6))

        info_row = tk.Frame(hdr, bg="#f0f0f0")
        info_row.pack(fill="x")
        tk.Label(info_row, text="📅 日期", bg="#f0f0f0", fg="#888",
                 font=("Microsoft YaHei", 8)).pack(side="left")
        date_var = tk.StringVar(value=t["date"])
        date_entry = tk.Entry(info_row, textvariable=date_var, width=14,
                              font=("Microsoft YaHei", 9), relief="solid", bd=1, bg="white")
        date_entry.pack(side="left", padx=(4, 16))

        done_var = tk.BooleanVar(value=t["done"])

        def toggle_status():
            is_done = done_var.get()
            status_btn.config(
                text="✓ 已完成" if is_done else "○ 待完成",
                fg="#4CAF50" if is_done else "#FF9800",
            )

        status_btn = tk.Checkbutton(
            info_row, variable=done_var, command=toggle_status,
            font=("Microsoft YaHei", 9), bg="#f0f0f0", activebackground="#f0f0f0",
            relief="flat", cursor="hand2", indicatoron=False, bd=0,
            text="✓ 已完成" if t["done"] else "○ 待完成",
            fg="#4CAF50" if t["done"] else "#FF9800",
            selectcolor="#f0f0f0",
        )
        status_btn.pack(side="left")

        ttk.Separator(win).pack(fill="x", padx=10)

        # ── Buttons — pack FIRST so they are always visible at bottom ──
        btn_row = tk.Frame(win, bg="#f0f0f0")
        btn_row.pack(side="bottom", pady=8)

        def save_detail():
            new_title = title_var.get().strip()
            new_date = date_var.get().strip()
            raw = content_text.get("1.0", "end-1c")
            new_content = raw.replace("\ufffc", "").strip()
            if not new_title:
                messagebox.showwarning("提示", "标题不能为空", parent=win)
                return
            try:
                date.fromisoformat(new_date)
            except ValueError:
                messagebox.showwarning("提示", "日期格式错误，请使用 YYYY-MM-DD", parent=win)
                return
            # Finalize newly pasted images
            kept_images = list(t.get("images", []))
            for tmp_path, _ in win._detail_pending:
                new_name = f"{todo_id}_{uuid.uuid4().hex[:8]}.png"
                new_path = os.path.join(IMAGES_DIR, new_name)
                try:
                    if os.path.exists(tmp_path):
                        os.rename(tmp_path, new_path)
                        kept_images.append(os.path.join("images", new_name))
                except OSError:
                    pass
            win._detail_pending.clear()
            for todo in self.todos:
                if todo["id"] == todo_id:
                    todo["title"] = new_title
                    todo["date"] = new_date
                    todo["content"] = new_content
                    todo["done"] = done_var.get()
                    todo["images"] = kept_images
                    break
            self.save_data()
            self.refresh_all_views()
            win.destroy()

        tk.Button(btn_row, text="保存", command=save_detail,
                  bg="#4CAF50", fg="white", font=("Microsoft YaHei", 9, "bold"),
                  relief="flat", padx=16, cursor="hand2").pack(side="left", padx=6)
        tk.Button(btn_row, text="关闭", command=lambda: on_detail_close(),
                  bg="#666", fg="white", font=("Microsoft YaHei", 9),
                  relief="flat", padx=16, cursor="hand2").pack(side="left", padx=6)

        # ── Content + Images (same editable widget as add-task view) ──
        tk.Label(win, text="内容  （Ctrl+V 可粘贴截图）", bg="#f0f0f0", fg="#888",
                 font=("Microsoft YaHei", 8), anchor="w").pack(anchor="w", padx=14, pady=(6, 0))

        content_text = tk.Text(win, font=("Microsoft YaHei", 10), wrap="word",
                               relief="solid", bd=1, bg="white", padx=6, pady=6)
        content_text.pack(fill="both", expand=True, padx=12, pady=(2, 4))

        # Insert existing text, then embed existing images inline
        content_text.insert("1.0", t.get("content", ""))
        if PIL_AVAILABLE:
            for img_rel in t.get("images", []):
                img_path = os.path.join(BASE_DIR, img_rel)
                if os.path.exists(img_path):
                    try:
                        img = Image.open(img_path)
                        img.thumbnail((280, 180))
                        photo = ImageTk.PhotoImage(img)
                        win._photo_refs.append(photo)
                        content_text.insert(tk.END, "\n")
                        content_text.image_create(tk.END, image=photo, padx=2, pady=2)
                        win._image_map[str(photo)] = img_path
                    except Exception:
                        pass
        elif t.get("images"):
            content_text.insert(tk.END, f"\n[{len(t['images'])} 张图片，需安装 Pillow 查看]")

        win._detail_pending = []  # temp images pasted in this window

        def paste_image_detail(_event):
            if not PIL_AVAILABLE:
                return
            try:
                img = ImageGrab.grabclipboard()
                if isinstance(img, Image.Image):
                    tmp_name = f"tmp_{uuid.uuid4().hex}.png"
                    tmp_path = os.path.join(IMAGES_DIR, tmp_name)
                    img.save(tmp_path, "PNG")
                    thumb = img.copy()
                    thumb.thumbnail((280, 180))
                    photo = ImageTk.PhotoImage(thumb)
                    win._detail_pending.append((tmp_path, photo))
                    win._photo_refs.append(photo)
                    win._image_map[str(photo)] = tmp_path
                    content_text.image_create(tk.INSERT, image=photo, padx=2, pady=2)
                    content_text.insert(tk.INSERT, "\n")
                    return "break"
            except Exception:
                pass

        content_text.bind("<Control-v>", paste_image_detail)

        def on_double_click(event):
            idx = content_text.index(f"@{event.x},{event.y}")
            items = content_text.dump(idx, content_text.index(f"{idx}+1c"), image=True)
            if not items:
                return
            photo_key = items[0][1]
            file_path = win._image_map.get(photo_key)
            if file_path and os.path.exists(file_path):
                os.startfile(file_path)
                return "break"

        content_text.bind("<Double-Button-1>", on_double_click)

        def on_detail_close():
            for tmp_path, _ in win._detail_pending:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_detail_close)

    # ── Render ────────────────────────────────────────────
    def refresh_all_views(self):
        self.refresh_today_list()
        self.refresh_all_list()
        self.update_status()

    def refresh_today_list(self):
        inner = self.today_scroll.inner
        for w in inner.winfo_children():
            w.destroy()

        today_str = str(date.today())
        tomorrow_str = str(date.today() + timedelta(days=1))
        groups = {today_str: [], tomorrow_str: []}

        for t in self.todos:
            if not t["done"] and t["date"] in (today_str, tomorrow_str):
                groups[t["date"]].append(t)

        if not any(groups.values()):
            tk.Label(inner, text="暂无今明两天的待完成任务", bg="#f5f5f5",
                     font=("Microsoft YaHei", 9), fg="#999").pack(pady=10)
            return

        for day_str, label_text in [(today_str, "今天"), (tomorrow_str, "明天")]:
            items = groups[day_str]
            if not items:
                continue
            hdr = tk.Label(inner, text=f"📅 {label_text} ({day_str})", bg="#e8f4e8",
                           font=("Microsoft YaHei", 9, "bold"), anchor="w", padx=6, pady=2)
            hdr.pack(fill="x", pady=(4, 0))
            self.today_scroll.bind_mousewheel(hdr)
            for t in items:
                self._render_today_row(inner, t)

    def _render_today_row(self, parent, t):
        row = tk.Frame(parent, bg="#f5f5f5")
        row.pack(fill="x", padx=4, pady=1)
        self.today_scroll.bind_mousewheel(row)

        lbl = tk.Label(row, text=self.get_title(t), bg="#f5f5f5",
                       font=("Microsoft YaHei", 9), anchor="w", wraplength=200,
                       cursor="hand2")
        lbl.pack(side="left", fill="x", expand=True)
        self.today_scroll.bind_mousewheel(lbl)

        done_btn = tk.Button(row, text="完成", bg="#2196F3", fg="white",
                             font=("Microsoft YaHei", 8), relief="flat", padx=6, cursor="hand2",
                             command=lambda tid=t["id"]: self.mark_done(tid))
        done_btn.pack(side="right", padx=(2, 0))
        del_btn = tk.Button(row, text="删除", bg="#f44336", fg="white",
                            font=("Microsoft YaHei", 8), relief="flat", padx=6, cursor="hand2",
                            command=lambda tid=t["id"]: self.delete_todo(tid))
        del_btn.pack(side="right", padx=(2, 0))

        # Double-click → detail
        for w in (row, lbl):
            w.bind("<Double-Button-1>", lambda e, tid=t["id"]: self.show_detail(tid))

    def refresh_all_list(self):
        inner = self.all_scroll.inner
        for w in inner.winfo_children():
            w.destroy()

        filt = self.filter_var.get()
        if filt == "待完成":
            items = [t for t in self.todos if not t["done"]]
        elif filt == "已完成":
            items = [t for t in self.todos if t["done"]]
        else:
            items = list(self.todos)

        items.sort(key=lambda t: t["date"])

        if not items:
            tk.Label(inner, text="暂无任务", bg="#f5f5f5",
                     font=("Microsoft YaHei", 9), fg="#999").pack(pady=10)
            return

        hdr = tk.Frame(inner, bg="#e0e0e0")
        hdr.pack(fill="x")
        tk.Label(hdr, text="日期", bg="#e0e0e0", font=("Microsoft YaHei", 8, "bold"),
                 anchor="w", padx=4, width=11).pack(side="left")
        tk.Label(hdr, text="标题", bg="#e0e0e0", font=("Microsoft YaHei", 8, "bold"),
                 anchor="w", padx=4).pack(side="left", fill="x", expand=True)
        tk.Label(hdr, text="  ", bg="#e0e0e0", width=4).pack(side="right")
        tk.Label(hdr, text="状态", bg="#e0e0e0", font=("Microsoft YaHei", 8, "bold"),
                 anchor="w", padx=4, width=8).pack(side="right")
        self.all_scroll.bind_mousewheel(hdr)

        for t in items:
            self._render_all_row(inner, t)

    def _render_all_row(self, parent, t):
        done = t["done"]
        bg = "#f5f5f5" if not done else "#eeeeee"
        fg = "#333" if not done else "#aaa"

        row = tk.Frame(parent, bg=bg, pady=1, cursor="hand2")
        row.pack(fill="x")
        self.all_scroll.bind_mousewheel(row)

        date_lbl = tk.Label(row, text=t["date"], bg=bg, fg=fg,
                            font=("Microsoft YaHei", 8), width=11, anchor="w", padx=4,
                            cursor="hand2")
        date_lbl.pack(side="left")

        task_font = ("Microsoft YaHei", 9, "overstrike") if done else ("Microsoft YaHei", 9)
        icon = " 📎" if t.get("images") else ""
        task_lbl = tk.Label(row, text=self.get_title(t) + icon, bg=bg, fg=fg,
                            font=task_font, anchor="w", wraplength=240, cursor="hand2")
        task_lbl.pack(side="left", fill="x", expand=True)

        del_btn = tk.Button(row, text="✕", bg="#f44336", fg="white",
                            font=("Microsoft YaHei", 8), relief="flat", padx=4,
                            cursor="hand2", command=lambda tid=t["id"]: self.delete_todo(tid))
        del_btn.pack(side="right", padx=(2, 2))

        status_text = "✓ 已完成" if done else "○ 待完成"
        status_fg = "#4CAF50" if done else "#FF9800"
        status_lbl = tk.Label(row, text=status_text, bg=bg, fg=status_fg,
                              font=("Microsoft YaHei", 8), width=8, anchor="w")
        status_lbl.pack(side="right", padx=4)

        for w in (row, date_lbl, task_lbl, status_lbl):
            self.all_scroll.bind_mousewheel(w)

        # Double-click → detail (cancels any pending single-click)
        for w in (row, date_lbl, task_lbl, status_lbl):
            w.bind("<Double-Button-1>", lambda e, tid=t["id"]: (
                self._cancel_click_timer(), self.show_detail(tid)))

        # Single-click on title → inline rename
        task_lbl.bind("<Button-1>", lambda e, tid=t["id"], lbl=task_lbl, r=row: (
            self._schedule_single_click(lambda: self.start_edit_title(tid, lbl, r))))

        # Single-click on date → inline date pick
        date_lbl.bind("<Button-1>", lambda e, tid=t["id"], lbl=date_lbl, r=row: (
            self._schedule_single_click(lambda: self.start_edit_date(tid, lbl, r))))

    # ── Inline Editing ────────────────────────────────────
    def _schedule_single_click(self, callback):
        """Delay single-click action so double-click can cancel it."""
        if self._click_timer:
            self.root.after_cancel(self._click_timer)
        self._click_timer = self.root.after(250, callback)

    def _cancel_click_timer(self):
        if self._click_timer:
            self.root.after_cancel(self._click_timer)
            self._click_timer = None

    def start_edit_title(self, todo_id, lbl, row):
        try:
            if not row.winfo_exists() or not lbl.winfo_exists():
                return
        except tk.TclError:
            return
        lbl.pack_forget()
        entry = tk.Entry(row, font=("Microsoft YaHei", 9), relief="solid", bd=1,
                         bg="#fffde7")
        entry.insert(0, self.get_title(next(t for t in self.todos if t["id"] == todo_id)))
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()
        entry.select_range(0, "end")
        committed = [False]
        _handler = [None]

        def cleanup():
            if _handler[0]:
                try:
                    self.root.unbind("<Button-1>", _handler[0])
                except Exception:
                    pass
                _handler[0] = None

        def commit(event=None):
            if committed[0]:
                return
            committed[0] = True
            cleanup()
            new_title = entry.get().strip()
            if new_title:
                for t in self.todos:
                    if t["id"] == todo_id:
                        t["title"] = new_title
                        lines = t.get("content", "").split("\n")
                        if lines:
                            lines[0] = new_title
                            t["content"] = "\n".join(lines)
                        break
                self.save_data()
            self.refresh_all_views()

        entry.bind("<Return>", commit)
        entry.bind("<Escape>", lambda e: (cleanup(), self.refresh_all_views()))
        entry.bind("<Destroy>", lambda e: cleanup())

        def on_root_click(e):
            if e.widget is entry:
                return
            if isinstance(e.widget, tk.Button):
                # Let the button's own command run; just cancel editing without saving
                committed[0] = True
                cleanup()
                self.root.after(0, self.refresh_all_views)
                return
            try:
                entry.get()
            except tk.TclError:
                cleanup()
                return
            commit()
        _handler[0] = self.root.bind("<Button-1>", on_root_click, add="+")

    def start_edit_date(self, todo_id, lbl, row):
        try:
            if not row.winfo_exists() or not lbl.winfo_exists():
                return
        except tk.TclError:
            return
        current_todo = next((t for t in self.todos if t["id"] == todo_id), None)
        if not current_todo:
            return
        current_date_str = current_todo["date"]
        committed = [False]
        _handler = [None]

        def cleanup():
            if _handler[0]:
                try:
                    self.root.unbind("<Button-1>", _handler[0])
                except Exception:
                    pass
                _handler[0] = None

        def commit_date(new_date_str):
            if committed[0]:
                return
            committed[0] = True
            cleanup()
            try:
                date.fromisoformat(new_date_str)
                for t in self.todos:
                    if t["id"] == todo_id:
                        t["date"] = new_date_str
                        break
                self.save_data()
            except ValueError:
                pass
            self.refresh_all_views()

        # Overlay the Entry directly on top of the date label (avoids pack ordering issues)
        lbl.update_idletasks()
        widget = tk.Entry(row, font=("Microsoft YaHei", 8), relief="solid", bd=1, bg="#fffde7")
        widget.insert(0, current_date_str)
        widget.place(x=lbl.winfo_x(), y=lbl.winfo_y(),
                     width=max(lbl.winfo_width(), 90),
                     height=max(lbl.winfo_height(), 22))
        widget.focus_set()
        widget.select_range(0, "end")

        widget.bind("<Return>", lambda e: commit_date(widget.get().strip()))
        widget.bind("<Escape>", lambda e: (cleanup(), self.refresh_all_views()))
        widget.bind("<Destroy>", lambda e: cleanup())

        # Commit when clicking anywhere outside the entry widget
        def on_root_click(e):
            if e.widget is widget:
                return
            if isinstance(e.widget, tk.Button):
                committed[0] = True
                cleanup()
                self.root.after(0, self.refresh_all_views)
                return
            try:
                val = widget.get().strip()
            except tk.TclError:
                cleanup()
                return
            commit_date(val)
        _handler[0] = self.root.bind("<Button-1>", on_root_click, add="+")

    def update_status(self):
        total = len(self.todos)
        done = sum(1 for t in self.todos if t["done"])
        self.status_var.set(f"  共 {total} 项，已完成 {done} 项，待完成 {total - done} 项")


if __name__ == "__main__":
    if not PIL_AVAILABLE:
        print("建议安装 Pillow 以启用图片粘贴功能：pip install pillow")

    root = tk.Tk()
    app = TodoApp(root)
    root.mainloop()
