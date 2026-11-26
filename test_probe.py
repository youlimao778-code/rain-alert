"""Synthetic inputs only. These tests cannot prove classroom or phone delivery."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import rain_probe as app


class ProbeTests(unittest.TestCase):
    def test_no_classroom_page_has_clear_error(self):
        from types import SimpleNamespace
        with self.assertRaises(ValueError):
            app.select_classroom_page([])
        unrelated = SimpleNamespace(url="https://example.com", is_closed=lambda: False)
        closed = SimpleNamespace(url="https://changjiang.yuketang.cn/web/", is_closed=lambda: True)
        target = SimpleNamespace(url="https://changjiang.yuketang.cn/web/", is_closed=lambda: False)
        with self.assertRaises(ValueError):
            app.select_classroom_page([unrelated, closed])
        self.assertIs(target, app.select_classroom_page([target, unrelated]))

    def test_event_labels_do_not_copy_credentials_or_question(self):
        obj = {"type": "synthetic-release", "token": "SECRET", "text": "PRIVATE",
               "data": {"event": "synthetic-event", "sessionid": "SECRET"}}
        self.assertEqual({"type": "synthetic-release", "data.event": "synthetic-event"}, app.event_labels(obj))

    def test_observed_classroom_selects_new_tab_and_rejects_multiple(self):
        from types import SimpleNamespace
        opened = SimpleNamespace(is_closed=lambda: False)
        other = SimpleNamespace(is_closed=lambda: False)
        closed = SimpleNamespace(is_closed=lambda: True)
        self.assertIsNone(app.observed_classroom_page([]))
        self.assertIs(opened, app.observed_classroom_page([closed, opened]))
        with self.assertRaises(ValueError):
            app.observed_classroom_page([opened, other])

    def test_observed_release_protocol_and_dedup(self):
        adapter = app.ObservedProtocol()
        moment = int(time.time())
        release = {"op": "unlockproblem", "lessonid": "synthetic-lesson", "problem": {"prob": "q1", "dt": moment}}
        self.assertIsNone(adapter.consume(release))
        adapter.consume({"op": "hello", "lessonid": "synthetic-lesson"})
        first = adapter.consume(release)
        self.assertEqual("question", first[0])
        self.assertEqual(moment, first[2])
        self.assertTrue(self.store.add(first[1], first[2]))
        self.assertFalse(self.store.add(adapter.consume(release)[1], moment))
        another = {**release, "problem": {"prob": "q1", "dt": moment + 1}}
        self.assertNotEqual(first[1], adapter.consume(another)[1])
        self.assertIsNone(adapter.consume({**release, "op": "slidenav"}))
        self.assertIsNone(adapter.consume({**release, "op": "probleminfo"}))
        self.assertIsNone(adapter.consume({**release, "lessonid": "other"}))
        adapter.consume({"op": "hello", "lessonid": "other"})
        self.assertEqual("synthetic-lesson", adapter.lesson)

    def test_observed_protocol_rejects_unusable_clock_and_handles_ms(self):
        adapter = app.ObservedProtocol()
        adapter.consume({"op": "hello", "lessonid": "synthetic-lesson"})
        def release(dt):
            return {"op": "unlockproblem", "lessonid": "synthetic-lesson", "problem": {"prob": "q1", "dt": dt}}
        for dt in (None, True, "2026-10-18", 123, int(time.time()) + 100):
            self.assertIsNone(adapter.consume(release(dt)))
        moment_ms = int(time.time() * 1000)
        self.assertEqual(moment_ms / 1000, adapter.consume(release(moment_ms))[2])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = app.Store(self.root / "state.sqlite")
        self.cfg = dict(lesson="synthetic-class", event_path="event", release_event="synthetic-release",
                        lesson_path="lesson", question_path="question", publication_path="publication",
                        published_at_path="time", end_event="synthetic-end")
        self.msg = dict(lesson="synthetic-class", event="synthetic-release", question="q1",
                        publication="release1", time=time.time())

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_other_class_and_non_release_ignored(self):
        self.assertIsNone(app.interpret({**self.msg, "lesson": "someone-else"}, self.cfg))
        self.assertIsNone(app.interpret({**self.msg, "event": "heartbeat"}, self.cfg))

    def test_republish_distinct_but_duplicate_same(self):
        first = app.interpret(self.msg, self.cfg)[1]
        self.assertEqual(first, app.interpret(self.msg, self.cfg)[1])
        second = app.interpret({**self.msg, "publication": "release2"}, self.cfg)[1]
        self.assertNotEqual(first, second)
        self.assertTrue(self.store.add(first, time.time()))
        self.assertFalse(self.store.add(first, time.time()))
        self.assertTrue(self.store.add(second, time.time()))

    def test_restart_keeps_dedup(self):
        self.store.add("q", time.time())
        self.store.db.close()
        self.store = app.Store(self.root / "state.sqlite")
        self.assertFalse(self.store.add("q", time.time()))

    def test_baseline_never_sent(self):
        self.store.add("old", time.time(), baseline=True)
        self.assertEqual([], self.store.pending())

    def test_missing_publication_or_invalid_time_rejected(self):
        for change in ({"publication": None}, {"time": None}, {"time": float("nan")},
                       {"time": time.time() * 1000}, {"time": True}):
            self.assertIsNone(app.interpret({**self.msg, **change}, self.cfg))

    def test_end_needs_correct_class(self):
        self.assertEqual("end", app.interpret({**self.msg, "event": "synthetic-end"}, self.cfg)[0])
        self.assertIsNone(app.interpret({**self.msg, "event": "synthetic-end", "lesson": "other"}, self.cfg))

    def test_schema_excludes_secret_values(self):
        shape = json.dumps(app.schema({"token": "PRIVATE", "data": [{"text": "SECRET"}]}))
        self.assertNotIn("PRIVATE", shape)
        self.assertNotIn("SECRET", shape)

    def test_unverified_adapter_fails_closed(self):
        path = self.root / "adapter.json"
        path.write_text('{"verified": false}', encoding="utf-8")
        with self.assertRaises(ValueError):
            app.mapping(path)

    def test_push_failure_retry_then_success(self):
        self.store.add("q", time.time())
        with patch.object(app, "log"), patch.object(app, "publish", side_effect=TimeoutError):
            asyncio.run(app.deliver(self.store, {}))
        self.assertEqual(1, len(self.store.pending()))
        with patch.object(app, "log"), patch.object(app, "publish", return_value="mock-receipt") as sender:
            asyncio.run(app.deliver(self.store, {}))
            asyncio.run(app.deliver(self.store, {}))
            self.assertEqual(1, sender.call_count)
        self.assertEqual([], self.store.pending())

    def test_stale_release_not_sent(self):
        self.store.add("stale", time.time() - 61)
        with patch.object(app, "log"), patch.object(app, "publish") as sender:
            asyncio.run(app.deliver(self.store, {}))
            sender.assert_not_called()
        self.assertEqual("expired", self.store.db.execute("SELECT status FROM events").fetchone()[0])

    def test_sc3_key_format_and_routing(self):
        self.assertEqual("https://123.push.ft07.com/send/sctp123tSYNTHETIC.send", app.sc3_endpoint("sctp123tSYNTHETIC"))
        for invalid in ("SCTsynthetic", "", "https://elsewhere", "sctp123tsecret/redirect", "sctp123tsecret?x=1"):
            with self.assertRaises(ValueError):
                app.sc3_endpoint(invalid)

    def test_sc3_success_and_business_failure(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"code":0}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(app.urllib.request, "build_opener", return_value=opener):
            self.assertEqual("sc3-code-0", app.publish({"provider": "sc3", "sendkey": "sctp123tSYNTHETIC"}, "TEST"))
            self.assertEqual(3, opener.open.call_args.kwargs["timeout"])
            self.assertEqual("rain-alert-validation/0.1", opener.open.call_args.args[0].get_header("User-agent"))
            response.read.return_value = b'{"code":1}'
            with self.assertRaises(ValueError):
                app.publish({"provider": "sc3", "sendkey": "sctp123tSYNTHETIC"}, "TEST")

    def test_sc3_config_selection_stays_local(self):
        with patch.object(app, "LOCAL", self.root):
            (self.root / "push.json").write_text('{"provider":"ntfy"}', encoding="utf-8")
            self.assertEqual("ntfy", app.push_config()["provider"])
            (self.root / "sc3.json").write_text('{"provider":"sc3","sendkey":"synthetic"}', encoding="utf-8")
            self.assertEqual("sc3", app.push_config()["provider"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
