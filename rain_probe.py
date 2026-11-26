"""Personal Rain Classroom feasibility probe. No Rain Classroom endpoints are invented.

probe: observe the user's normal browser; log JSON field types, never cookies/payloads.
watch: ONLY after an observed WebSocket mapping has been configured and verified.
monitor: narrow live adapter for the single-question release observed in this test.
All timestamps UTC; no auto-answer, check-in, refresh, or protocol replay.
"""
import argparse
import asyncio
import hashlib
import json
import math
import re
import secrets
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log(event, **data):
    LOCAL.mkdir(exist_ok=True)
    row = {"time_utc": stamp(), "event": event, **data}
    with (LOCAL / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:24]


def field(obj, path):
    if not path:
        return None
    for name in path.split("."):
        if not isinstance(obj, dict) or name not in obj:
            return None
        obj = obj[name]
    return obj


def select_classroom_page(pages):
    candidates = [page for page in pages if not page.is_closed()
                  and urlsplit(page.url).hostname == "changjiang.yuketang.cn"]
    if not candidates:
        raise ValueError("工具新开的 Edge 中没有可用的长江雨课堂标签页。请保持该窗口打开并进入学生课堂，再启动探测。")
    return candidates[-1]


def observed_classroom_page(pages):
    candidates = [page for page in pages if not page.is_closed()]
    if len(candidates) > 1:
        raise ValueError("工具窗口中有多个实时课堂，请只保留本次学生课堂后重新启动。")
    return candidates[0] if candidates else None


def event_labels(obj, prefix="", depth=0):
    """Only protocol event labels, no question text, account details or auth values."""
    result = {}
    if not isinstance(obj, dict) or depth > 3:
        return result
    for key, value in list(obj.items())[:40]:
        path = f"{prefix}.{key}" if prefix else str(key)
        if key in ("event", "type", "cmd", "action", "op") and isinstance(value, str):
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", value):
                result[path] = value
        elif isinstance(value, dict) and key in ("data", "payload", "message"):
            result.update(event_labels(value, path, depth + 1))
    return result


def schema(obj, depth=0):
    # Only field names/types. No values, text, URLs, headers, screenshots or HAR.
    if depth > 4:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {str(k)[:80]: schema(v, depth + 1) for k, v in list(obj.items())[:40]}
    if isinstance(obj, list):
        return [schema(obj[0], depth + 1)] if obj else []
    return type(obj).__name__


def mapping(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    required = ("lesson", "ws_host", "ws_path", "event_path", "release_event",
                "lesson_path", "question_path", "publication_path", "published_at_path", "end_event")
    if cfg.get("verified") is not True or any(not cfg.get(k) for k in required):
        raise ValueError("真实课堂映射尚未验证；请先运行 probe，由开发者根据现场证据填写 adapter.json。")
    return cfg


def interpret(obj, cfg):
    if str(field(obj, cfg["lesson_path"])) != cfg["lesson"]:
        return None
    event = field(obj, cfg["event_path"])
    if event == cfg["end_event"]:
        return ("end", None, None)
    if event != cfg["release_event"]:
        return None
    qid, pub = field(obj, cfg["question_path"]), field(obj, cfg["publication_path"])
    if qid is None or pub is None or isinstance(qid, (dict, list)) or isinstance(pub, (dict, list)):
        return None
    published = field(obj, cfg["published_at_path"])
    if not isinstance(published, (int, float)) or isinstance(published, bool) or not math.isfinite(published):
        return None
    # Verified mapping must provide Unix SECONDS; other formats need an observed adapter change.
    if published > time.time() + 5 or published < 1000000000:
        return None
    return ("question", digest(json.dumps([cfg["lesson"], qid, pub], ensure_ascii=False)), published)


class ObservedProtocol:
    """Narrow adapter for hello/unlockproblem observed in the user's classroom.

    No problem text, HTTP replay, guessed end event, or lesson switching.
    """
    def __init__(self):
        self.lesson = None

    def consume(self, obj):
        if not isinstance(obj, dict):
            return None
        lesson = obj.get("lessonid")
        if not isinstance(lesson, str) or not lesson or len(lesson) > 128:
            return None
        if obj.get("op") == "hello":
            if self.lesson is None:
                self.lesson = lesson
            return None
        if self.lesson is None or lesson != self.lesson or obj.get("op") != "unlockproblem":
            return None
        problem = obj.get("problem")
        if not isinstance(problem, dict):
            return None
        qid, raw_dt = problem.get("prob"), problem.get("dt")
        if not isinstance(qid, str) or not qid or len(qid) > 128:
            return None
        if type(raw_dt) is not int:
            return None
        # Accept only a plausible absolute epoch; do not invent a teacher timestamp.
        published = raw_dt / 1000 if raw_dt >= 1000000000000 else raw_dt
        if published < 1000000000 or published > time.time() + 5:
            return None
        key = digest(json.dumps([lesson, qid, raw_dt], ensure_ascii=False))
        return ("question", key, published)


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, found REAL, status TEXT)")
        self.db.commit()

    def add(self, key, now, baseline=False):
        cur = self.db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?)",
                              (key, now, "baseline" if baseline else "pending"))
        self.db.commit()
        return bool(cur.rowcount)

    def pending(self):
        return self.db.execute("SELECT id,found FROM events WHERE status='pending'").fetchall()

    def status(self, key, state):
        self.db.execute("UPDATE events SET status=? WHERE id=?", (state, key))
        self.db.commit()


def push_config():
    sc3_path = LOCAL / "sc3.json"
    if sc3_path.exists():
        return json.loads(sc3_path.read_text(encoding="utf-8-sig"))
    path = LOCAL / "push.json"
    if not path.exists():
        raise ValueError("请先运行 init-push，再在手机订阅 local/push.json 中的 topic。")
    return json.loads(path.read_text(encoding="utf-8"))


def publish(cfg, message):
    if cfg.get("provider") == "sc3":
        return publish_sc3(cfg, message)
    if cfg.get("provider", "ntfy") != "ntfy":
        raise ValueError("未知推送渠道")
    server = cfg["server"].rstrip("/")
    if urlsplit(server).scheme != "https":
        raise ValueError("推送服务必须使用 HTTPS")
    body = json.dumps({"topic": cfg["topic"], "title": "Rain alert",
                       "message": message, "priority": 4}).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.get("token"):
        headers["Authorization"] = "Bearer " + cfg["token"]
    request = urllib.request.Request(server, body, headers, method="POST")
    with urllib.request.urlopen(request, timeout=3) as res:
        reply = json.loads(res.read(65536))
        if res.status != 200 or not reply.get("id"):
            raise ValueError("推送服务没有返回成功回执")
    return reply["id"]


def sc3_endpoint(sendkey):
    # Format and routing verified against the official serverchan-sdk 1.0.6.
    match = re.fullmatch(r"sctp(\d+)t[A-Za-z0-9_-]+", sendkey)
    if not match:
        raise ValueError("请填写 Server酱³ 的 SendKey（以 sctp 开头），不是 Turbo 的 SCT 密钥。")
    return f"https://{match.group(1)}.push.ft07.com/send/{sendkey}.send"


def publish_sc3(cfg, message):
    # Use stdlib HTTPS to enforce a timeout absent from official SDK 1.0.6.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    endpoint = sc3_endpoint(cfg.get("sendkey", ""))
    payload = json.dumps({"title": "雨课堂提醒验证", "desp": message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(endpoint, payload, {
        "Content-Type": "application/json;charset=utf-8",
        "User-Agent": "rain-alert-validation/0.1"
    }, method="POST")
    with urllib.request.build_opener(NoRedirect).open(request, timeout=3) as res:
        reply = json.loads(res.read(65536))
        if res.status != 200 or type(reply.get("code")) is not int or reply["code"] != 0:
            raise ValueError("Server酱³ 尚未确认接收；请检查本地账号、额度或配置。")
    # A service response is never a phone delivery acknowledgement.
    return "sc3-code-0"


async def deliver(store, cfg):
    for key, found in store.pending():
        if time.time() - found >= 55:
            store.status(key, "expired")
            log("expired_no_send", id=key)
            continue
        try:
            receipt = await asyncio.to_thread(publish, cfg,
                f"课堂可能有新题，请自行进入雨课堂查看。发布参考时间 UTC {datetime.fromtimestamp(found, timezone.utc).isoformat()}；事件 {key}")
            store.status(key, "sent")
            log("push_server_accepted_NOT_phone_received", id=key, receipt=receipt)
        except Exception as exc:
            # Never print request URLs/credentials or exception text.
            log("push_failed_will_retry", id=key, error_type=type(exc).__name__)


async def browse(args):
    from playwright.async_api import async_playwright
    cfg = mapping(args.adapter) if args.command == "watch" else None
    monitor = args.command == "monitor"
    native = ObservedProtocol() if monitor else None
    push = push_config() if cfg or monitor else None
    LOCAL.mkdir(exist_ok=True)
    store = Store(LOCAL / "state.sqlite")
    armed = False
    stopped = False
    baseline_until = float("inf")
    last_loop = time.monotonic()
    schema_counts = {}
    last_health = 0.0
    health = "waiting_for_user"
    selected = None
    attached_pages = set()
    classroom_socket_pages = set()
    classroom_hello = {}

    def set_health(state):
        nonlocal health
        if state != health:
            health = state
            log("health", state=state)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(LOCAL / "browser-profile"), channel="msedge", headless=False)

        def matched(ws):
            url = urlsplit(ws.url)
            if monitor:
                return url.hostname == "changjiang.yuketang.cn" and url.path == "/wsapp/"
            return cfg and url.hostname == cfg["ws_host"] and url.path == cfg["ws_path"]

        def attach(page):
            if page in attached_pages:
                return
            attached_pages.add(page)
            def socket(ws):
                nonlocal selected, stopped
                # Endpoint is hashed, with query string never logged.
                u = urlsplit(ws.url)
                channel = digest((u.hostname, u.path))
                channels_path = LOCAL / "channels.json"
                channels = json.loads(channels_path.read_text(encoding="utf-8")) if channels_path.exists() else {}
                channels[channel] = {"host": u.hostname, "path": u.path}
                channels_path.write_text(json.dumps(channels, indent=2), encoding="utf-8")
                log("ws_open", channel=channel, mapped=bool(matched(ws)))
                if u.hostname == "changjiang.yuketang.cn" and u.path == "/wsapp/":
                    classroom_socket_pages.add(page)
                    if armed and not cfg:
                        try:
                            detected = observed_classroom_page(classroom_socket_pages)
                            if detected is not selected:
                                selected = detected
                                log("classroom_tab_selected_from_observed_socket", channel=channel)
                        except ValueError:
                            stopped = True
                            set_health("multiple_classrooms_STOPPED_close_extra_tabs_and_restart")

                def frame(payload):
                    nonlocal stopped
                    if stopped or (armed and page != selected):
                        return
                    try:
                        if len(payload) > 1000000:
                            return
                        obj = json.loads(payload)
                    except (ValueError, TypeError, UnicodeError):
                        if armed:
                            log("ws_non_json", channel=channel)
                        return
                    if u.hostname == "changjiang.yuketang.cn" and u.path == "/wsapp/" and isinstance(obj, dict) and obj.get("op") == "hello":
                        classroom_hello[page] = {"op": "hello", "lessonid": obj.get("lessonid")}
                    if not armed:
                        return
                    shape = schema(obj)
                    identity = digest(json.dumps(shape, sort_keys=True))
                    log("ws_frame_received_NOT_confirmed_question", channel=channel, shape_id=identity,
                        event_labels=event_labels(obj))
                    count = schema_counts.get(identity, 0) + 1
                    schema_counts[identity] = count
                    if count <= 2:
                        log("ws_schema", channel=channel, shape_id=identity, schema=shape)
                    if not matched(ws):
                        return
                    was_bound = native.lesson if monitor else None
                    result = native.consume(obj) if monitor else interpret(obj, cfg)
                    if monitor and not was_bound and native.lesson:
                        log("monitor_classroom_scope_bound", lesson_hash=digest(native.lesson))
                    if monitor and isinstance(obj, dict) and obj.get("op") == "unlockproblem" and not result:
                        problem = obj.get("problem") if isinstance(obj.get("problem"), dict) else {}
                        raw_dt = problem.get("dt")
                        log("release_frame_rejected_check_scope_id_or_timestamp",
                            scope_bound=bool(native.lesson), timestamp_type=type(raw_dt).__name__,
                            timestamp_value=raw_dt if type(raw_dt) is int else None)
                    if not result:
                        return
                    kind, key, published = result
                    if kind == "end":
                        stopped = True
                        for pending_id, _ in store.pending():
                            store.status(pending_id, "cancelled_class_ended")
                        set_health("class_ended")
                    elif store.add(key, published, time.monotonic() < baseline_until):
                        log("baseline_question" if time.monotonic() < baseline_until else "new_question", id=key,
                            publication_time_reference_unix=published)

                ws.on("framereceived", frame)
                ws.on("close", lambda: set_health("socket_closed_needs_check")
                      if page == selected and (not cfg or matched(ws)) and not stopped else None)
                ws.on("socketerror", lambda _: set_health("socket_error_needs_check")
                      if page == selected and not stopped else None)
            page.on("websocket", socket)
            async def response(res):
                if not armed or stopped or page != selected:
                    return
                u = urlsplit(res.url)
                if u.hostname != "changjiang.yuketang.cn":
                    return
                if res.status in (401, 403):
                    set_health("authorization_failure_suspected")
                if res.request.resource_type not in ("xhr", "fetch"):
                    return
                if "json" not in res.headers.get("content-type", ""):
                    return
                try:
                    body = await res.body()
                    if len(body) <= 1000000:
                        shape = schema(json.loads(body))
                        identity = digest(json.dumps(shape, sort_keys=True))
                        if identity not in schema_counts:
                            schema_counts[identity] = 1
                            log("http_schema_NOT_question_detection", endpoint=digest((u.hostname, u.path)), schema=shape)
                except Exception:
                    pass
            page.on("response", response)
            page.on("close", lambda: set_health("page_closed") if page == selected else None)

        context.on("page", attach)
        page = context.pages[0] if context.pages else await context.new_page()
        attach(page)
        await page.goto("https://changjiang.yuketang.cn/web/", wait_until="domcontentloaded", timeout=60000)
        print("\n请在新开的 Edge 窗口亲自登录并进入唯一目标课堂。保持该课堂标签页为最后打开的页面。\n"
              "准备后回到此窗口按回车；接下来的 5 秒用于历史基线，请暂不要发测试题。", flush=True)
        await asyncio.to_thread(input)
        selected = observed_classroom_page(classroom_socket_pages) or select_classroom_page(context.pages)
        if monitor:
            native.consume(classroom_hello.get(selected))
            if native.lesson:
                log("monitor_classroom_scope_bound", lesson_hash=digest(native.lesson))
        armed = True
        last_loop = time.monotonic()
        baseline_until = time.monotonic() + 5
        log("armed", mode=args.command, baseline_seconds=5,
            note="仅观察新接收帧，不保证断线期间补发；不会自动刷新页面")
        print("5 秒后才开始发测试题。Ctrl+C 停止。时间标记可在另一窗口运行 mark。", flush=True)

        while context.pages and not selected.is_closed():
            now = time.monotonic()
            if now - last_loop > 10:
                set_health("loop_gap_possible_sleep_or_push_delay")
            last_loop = now
            try:
                online = await asyncio.wait_for(selected.evaluate("navigator.onLine"), 3)
                if not online:
                    set_health("browser_offline")
                elif health in ("browser_offline", "waiting_for_user"):
                    set_health("browser_online_transport_UNVERIFIED")
            except Exception:
                set_health("page_unresponsive")
            if now - last_health >= 10:
                log("heartbeat", state=health, monitoring_confirmed=False)
                last_health = now
            if (cfg or monitor) and not stopped and now >= baseline_until:
                await deliver(store, push)
            await asyncio.sleep(1)
        log("stopped")
        await context.close()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="长江雨课堂最小验证工具；已实测单题提醒，其他题型和故障恢复待验证")
    parser.add_argument("command", choices=["probe", "monitor", "watch", "init-push", "push-test", "mark"])
    parser.add_argument("--adapter", default=str(ROOT / "adapter.json"))
    parser.add_argument("--kind", choices=["teacher_release", "phone_received", "observation"], default="observation")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    LOCAL.mkdir(exist_ok=True)
    if args.command == "init-push":
        path = LOCAL / "push.json"
        if path.exists():
            print("配置已存在，未覆盖。请在本地打开 local/push.json 查看。")
        else:
            path.write_text(json.dumps({"server": "https://ntfy.sh", "topic": "rain-" + secrets.token_hex(20)}, indent=2), encoding="utf-8")
            print("已生成 local/push.json。topic 相当于收件地址密钥，只在本地查看；不要发进聊天。")
    elif args.command == "push-test":
        receipt = publish(push_config(), "Rain alert TEST " + stamp() + " — 这是通知通道测试，并非真实发题。")
        log("test_push_server_accepted_NOT_phone_received", receipt=receipt)
    elif args.command == "mark":
        if not re.fullmatch(r"[A-Za-z0-9_-]{0,40}", args.label):
            raise ValueError("label 只填 test01 这类短编号，不填个人信息。")
        log("manual_" + args.kind, label=args.label, note="手工标记时间含操作延迟，不是平台发题时间")
    else:
        asyncio.run(browse(args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("已停止。")
    except Exception as exc:
        # User-facing validation errors are safe; network/library exception bodies can contain URLs.
        print(str(exc) if type(exc) is ValueError else f"运行失败：{type(exc).__name__}。请保留本地文件联系开发者。")
        raise SystemExit(1)
