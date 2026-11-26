"""Local-only SendKey entry. Never sends a test message or opens a web server."""
import json
import tkinter as tk
from tkinter import messagebox
import rain_probe as app


def main():
    window = tk.Tk()
    window.title("手机通知：Server酱³ 本地配置")
    window.geometry("560x260")
    tk.Label(window, text="先在 Server酱³ 官网注册，并在手机 App 登录同一账号。", anchor="w").pack(padx=18, pady=(18, 6), fill="x")
    tk.Label(window, text="把官网的 SendKey 粘贴在下方（以 sctp 开头）：", anchor="w").pack(padx=18, fill="x")
    entry = tk.Entry(window, show="*", width=65)
    entry.pack(padx=18, pady=12, fill="x")
    tk.Label(window, text="只保存到本机 local/sc3.json；不要把密钥发进聊天。\n保存后切换通知渠道；本窗口不会发送消息。", justify="left", anchor="w").pack(padx=18, fill="x")

    def save():
        key = entry.get().strip()
        try:
            app.sc3_endpoint(key)
        except ValueError as exc:
            messagebox.showerror("请检查密钥", str(exc))
            return
        app.LOCAL.mkdir(exist_ok=True)
        path = app.LOCAL / "sc3.json"
        path.write_text(json.dumps({"provider": "sc3", "sendkey": key}), encoding="utf-8")
        entry.delete(0, tk.END)
        messagebox.showinfo("已保存", "密钥已保存到本机。\n下一步：双击 test-notification.cmd，确认手机收到测试通知。\n通过后再双击 monitor.cmd 开始课堂验证。")
        window.destroy()

    tk.Button(window, text="保存到本机并使用此渠道", command=save).pack(pady=15)
    entry.focus_set()
    window.mainloop()


if __name__ == "__main__":
    main()
